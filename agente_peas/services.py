"""Serviços determinísticos para o ambiente simulado do quarto."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from typing import (
    Final,
    Literal,
    NoReturn,
    NotRequired,
    TypeAlias,
    TypedDict,
    cast,
)
from uuid import NAMESPACE_URL, uuid4, uuid5

from .config import (
    Binary,
    Luminosity,
    Mode,
    PresetDevices,
    PresetError,
    PresetName,
    RoomState,
    append_trace_event,
    apply_preset as apply_config_preset,
    estado_quarto,
    invalidate_decision,
    reset_state as reset_config_state,
    validate_trace,
)
from .shared import peas_protocol as protocol
from .shared.peas_protocol import MAX_TRACE_PAGE_LIMIT, CycleMetrics, RunSummary


DeviceName: TypeAlias = Literal[
    "janela",
    "ar",
    "ventilador",
    "umidificador",
    "lampada",
]
ActionName: TypeAlias = Literal[
    "manter",
    "fechar",
    "ventilar",
    "resfriar",
    "ventilacao_natural",
    "ventilacao_assistida",
    "circulacao_interna",
    "resfriamento",
    "resfriamento_assistido",
    "umidificar",
    "iluminar",
]
StrategyId: TypeAlias = Literal[
    "manter",
    "ventilacao_natural",
    "ventilacao_assistida",
    "circulacao_interna",
    "resfriamento",
    "resfriamento_assistido",
    "umidificacao",
    "iluminacao",
]
TemperatureBand: TypeAlias = Literal["frio", "conforto", "calor"]
TimeBand: TypeAlias = Literal["madrugada", "amanhecer", "dia", "noite"]
CognitiveMode: TypeAlias = Literal["cognitivo"]
FeedbackType: TypeAlias = Literal["aceitar", "rejeitar", "corrigir"]
PreferenceKey: TypeAlias = str
DecisionObjective: TypeAlias = Literal[
    "seguranca",
    "umidade",
    "termico",
    "iluminacao",
    "manutencao",
]
PlanStatus: TypeAlias = Literal["pendente", "confirmado", "falhou"]
PlanTransition: TypeAlias = Literal["executando", "confirmado", "falhou"]
ConfirmationStatus: TypeAlias = Literal["confirmado"]
DecisionStatus: TypeAlias = Literal["prevista", "confirmada", "invalidada"]


class SensorReadings(TypedDict):
    """Leituras escalares entregues pelo conjunto de sensores simulados."""

    temperatura_interna: float
    temperatura_externa: float
    umidade: float
    luminosidade: Luminosity
    chuva: Binary
    presenca_interna: Binary
    presenca_externa: Binary
    dormir: Binary


class DeviceConfirmation(TypedDict):
    """Confirmação devolvida por um atuador simulado local."""

    dispositivo: DeviceName
    comando: Binary
    status: ConfirmationStatus


class PlanStep(TypedDict):
    """Etapa binária de um plano com confirmação observável."""

    ordem: int
    comando_id: str | None
    dispositivo: DeviceName
    comando: Binary
    status: PlanStatus
    transicoes: list[PlanTransition]
    estado_anterior: NotRequired[Binary | None]
    estado_novo: NotRequired[Binary]


class LearningContext(TypedDict):
    """Context snapshot retained for explanation and decision correlation."""

    hora: NotRequired[int]
    preset: PresetName
    modo: CognitiveMode
    faixa_horario: TimeBand
    dormir: Binary
    faixa_temperatura: TemperatureBand
    luminosidade: Luminosity
    presenca_interna: Binary


class LearningIdentity(TypedDict):
    """Identidade congelada que delimita a reaplicação da aprendizagem."""

    preset: PresetName
    modo: CognitiveMode
    faixa_horario: TimeBand
    dormir: Binary
    faixa_temperatura: TemperatureBand
    luminosidade: Luminosity
    presenca_interna: Binary


class CorrectionCommand(TypedDict):
    """Comando manual permitido para contrariar uma ação confirmada."""

    rota: str
    dispositivo: DeviceName
    comando: Binary


class LearningResult(TypedDict):
    """Result of changing an objective and strategy preference."""

    contexto: LearningContext
    acao: ActionName
    delta: Literal[-1, 1]
    preferencia_anterior: int
    preferencia_atual: int


class DecisionAlternative(TypedDict):
    """Alternativa cognitiva avaliada pelo agente."""

    acao: ActionName
    strategy_id: str
    pontuacao_base: float | None
    preferencia_contextual: int
    pontuacao_total: float | None
    elegivel: bool
    influenciada: bool
    motivo_bloqueio: str | None
    correcoes_permitidas: list[CorrectionCommand]
    conforto: NotRequired[float | None]
    economia: NotRequired[float | None]
    custo: NotRequired[int | None]
    preferencia: NotRequired[float]
    utilidade: NotRequired[float | None]
    temperatura_projetada: NotRequired[float | None]
    temperatura_em_tres_horas: NotRequired[float | None]
    conforto_horizonte: NotRequired[float | None]
    penalidade_troca: NotRequired[float]
    preferencia_estrategia: NotRequired[int]
    ajuste_familia_ar: NotRequired[int]
    motivo_influencia: NotRequired[str]


class FeedbackResult(TypedDict):
    """Resultado completo do feedback aplicado a uma decisão."""

    decisao_id: str
    tipo: FeedbackType
    acao: ActionName
    identidade: LearningIdentity
    preferencia_anterior: int
    delta: Literal[-1, 1]
    preferencia_atual: int
    condicao_reaplicacao: str
    idempotente: bool


class Decision(TypedDict):
    """Decisão prevista ou confirmada antes e depois da execução do ciclo."""

    decisao_id: str
    identidade: LearningIdentity | None
    modo: Mode
    objetivo: DecisionObjective
    acao: ActionName
    strategy_id: str
    acoes: NotRequired[list[ActionName]]
    status: DecisionStatus
    alternativas: list[DecisionAlternative]
    plano: list[PlanStep]
    correcoes_permitidas: list[CorrectionCommand]
    motivo: NotRequired[str]
    contexto: NotRequired[LearningContext]


class EnvironmentRequest(TypedDict):
    """Parâmetros ambientais aceitos pelo ajuste da interface."""

    hora: int
    temperatura_externa: float
    umidade: float
    chuva: Binary
    presenca_interna: Binary
    presenca_externa: Binary
    dormir: Binary


class CycleRequest(TypedDict):
    """Corpo fechado para solicitar a validação de um ciclo."""

    modo: Mode


class PresetRequest(TypedDict):
    """Corpo fechado para selecionar um preset determinístico."""

    preset: PresetName


class ResetRequest(TypedDict):
    """Corpo vazio aceito pela operação de reset."""


class TraceQueryRequest(TypedDict):
    """Validated parameters for one trace page."""

    run_id: str
    cursor: int | None
    limit: int


class ManualRequest(TypedDict, total=False):
    """Corpo opcional para correlacionar um comando a uma decisão."""

    decisao_id: str


class CommonFeedbackRequest(TypedDict):
    """Feedback comum associado a uma decisão confirmada."""

    decisao_id: str
    tipo: Literal["aceitar", "rejeitar"]


class CorrectionFeedbackRequest(TypedDict):
    """Feedback de correção associado a um comando confirmado."""

    decisao_id: str
    tipo: Literal["corrigir"]
    comando_id: str


FeedbackRequest: TypeAlias = CommonFeedbackRequest | CorrectionFeedbackRequest


class PublicRoomState(TypedDict):
    """Recorte público do estado autoritativo do quarto."""

    preset_atual: PresetName | None
    hora: int
    temperatura_externa: float
    temperatura_interna: float
    umidade: float
    luminosidade: Luminosity
    chuva: Binary
    presenca_interna: Binary
    presenca_externa: Binary
    dormir: Binary
    modo: Mode
    dispositivos: PresetDevices


ErrorCode: TypeAlias = Literal[
    "json_invalido",
    "campo_ausente",
    "campo_desconhecido",
    "tipo_invalido",
    "valor_invalido",
    "modo_invalido",
    "preset_invalido",
    "preset_nao_selecionado",
    "decisao_inexistente",
    "decisao_nao_confirmada",
    "decisao_obsoleta",
    "comando_nao_confirmado",
    "correcao_incompativel",
    "feedback_conflitante",
    "preferencia_no_limite",
    "acao_insegura",
    "run_inexistente",
    "trace_cursor_pruned",
    "erro_interno",
]


class ErrorResponse(TypedDict):
    """Envelope público de erro sem detalhes internos."""

    status: Literal["erro"]
    codigo: ErrorCode
    mensagem: str
    campos: list[str]
    estado: PublicRoomState


MIN_TEMPERATURE_C: Final[float] = 10.0
MAX_TEMPERATURE_C: Final[float] = 38.0
MIN_EXTERNAL_TEMPERATURE_C: Final[float] = 0.0
MAX_EXTERNAL_TEMPERATURE_C: Final[float] = 45.0
MIN_HUMIDITY_PCT: Final[float] = 0.0
MAX_HUMIDITY_PCT: Final[float] = 100.0
TEMP_COLD_LIMIT_C: Final[float] = 22.0
TEMP_CLIMATE_OFF_C: Final[float] = 23.0
TEMP_HOT_LIMIT_C: Final[float] = 25.0
COGNITIVE_COOL_ON_C: Final[float] = 26.0
COGNITIVE_CLIMATE_OFF_C: Final[float] = 23.0
LEARNED_HEAT_CEILING_C: Final[float] = 32.0
THERMAL_HORIZON_HOURS: Final[int] = 3
THERMAL_SWITCH_PENALTY: Final[float] = 0.04
TEMP_LIMIT_C: Final[float] = TEMP_HOT_LIMIT_C
PERCEIVED_AIRFLOW_COOLING_C: Final[float] = 0.3
PERCEIVED_EXCHANGE_COOLING_C: Final[float] = 0.7
_ENVIRONMENT_FIELDS: Final[tuple[str, ...]] = (
    "hora",
    "temperatura_externa",
    "umidade",
    "chuva",
    "presenca_interna",
    "presenca_externa",
    "dormir",
)
_PRESET_NAMES: Final[tuple[PresetName, ...]] = (
    "calor",
    "frio",
    "conforto",
)
_DEVICE_NAMES: Final[tuple[DeviceName, ...]] = (
    "janela",
    "ar",
    "ventilador",
    "umidificador",
    "lampada",
)
_ACTION_ALIASES: Final[dict[str, str]] = {
    "ventilar": "ventilacao_assistida",
    "resfriar": "resfriamento",
}
_LEGACY_THERMAL_ACTIONS: Final[dict[str, str]] = {
    "ventilacao_assistida": "ventilar",
    "resfriamento": "resfriar",
}
_THERMAL_STRATEGIES: Final[tuple[StrategyId, ...]] = (
    "manter",
    "ventilacao_natural",
    "ventilacao_assistida",
    "circulacao_interna",
    "resfriamento",
    "resfriamento_assistido",
)
_THERMAL_VECTORS: Final[dict[StrategyId, tuple[Binary, Binary, Binary]]] = {
    "ventilacao_natural": (1, 0, 0),
    "ventilacao_assistida": (1, 0, 1),
    "circulacao_interna": (0, 0, 1),
    "resfriamento": (0, 1, 0),
    "resfriamento_assistido": (0, 1, 1),
}
_THERMAL_MATCH_VECTORS: Final[
    dict[StrategyId, tuple[Binary, Binary, Binary]]
] = {
    "manter": (0, 0, 0),
    **_THERMAL_VECTORS,
}
_PLAN_STEPS: Final[
    dict[str, tuple[tuple[DeviceName, Binary], ...]]
] = {
    "manter": (),
    "ventilacao_natural": (("ar", 0), ("ventilador", 0), ("janela", 1)),
    "ventilacao_assistida": (("ar", 0), ("janela", 1), ("ventilador", 1)),
    "circulacao_interna": (("janela", 0), ("ar", 0), ("ventilador", 1)),
    "resfriamento": (("janela", 0), ("ventilador", 0), ("ar", 1)),
    "resfriamento_assistido": (("janela", 0), ("ar", 1), ("ventilador", 1)),
    "fechar": (("janela", 0), ("ar", 0), ("ventilador", 0)),
    "umidificar": (("umidificador", 1),),
    "iluminar": (("lampada", 1),),
}
_DEVICE_COSTS: Final[dict[DeviceName, int]] = {
    "janela": 0,
    "ar": 4,
    "ventilador": 1,
    "umidificador": 1,
    "lampada": 1,
}
_ACTION_ORDER: Final[dict[str, int]] = {
    "manter": 0,
    "ventilacao_natural": 1,
    "ventilacao_assistida": 2,
    "circulacao_interna": 3,
    "resfriamento": 4,
    "resfriamento_assistido": 5,
    "fechar": 6,
    "umidificar": 7,
    "iluminar": 8,
}
_FEEDBACK_DELTAS: Final[dict[str, tuple[FeedbackType, Literal[-1, 1]]]] = {
    "aceitar": ("aceitar", 1),
    "rejeitar": ("rejeitar", -1),
    "corrigir": ("corrigir", -1),
    "accept": ("aceitar", 1),
    "reject": ("rejeitar", -1),
    "manual_correction": ("corrigir", -1),
}
_FEEDBACK_REAPPLICATION_CONDITION: Final[str] = (
    "Reaplicável para o mesmo objetivo e a mesma estratégia."
)
_CORRECTION_MATRIX: Final[
    dict[str, tuple[tuple[str, DeviceName, Binary], ...]]
] = {
    "manter": (),
    "ventilacao_natural": (
        ("/interf/ligarar", "ar", 1),
        ("/interf/fechar", "janela", 0),
        ("/interf/desligarventilador", "ventilador", 0),
    ),
    "ventilacao_assistida": (
        ("/interf/ligarar", "ar", 1),
        ("/interf/fechar", "janela", 0),
        ("/interf/desligarventilador", "ventilador", 0),
    ),
    "circulacao_interna": (
        ("/interf/abrir", "janela", 1),
        ("/interf/ligarar", "ar", 1),
        ("/interf/desligarventilador", "ventilador", 0),
    ),
    "resfriamento": (
        ("/interf/abrir", "janela", 1),
        ("/interf/desligarar", "ar", 0),
        ("/interf/ligarventilador", "ventilador", 1),
    ),
    "resfriamento_assistido": (
        ("/interf/abrir", "janela", 1),
        ("/interf/desligarar", "ar", 0),
        ("/interf/desligarventilador", "ventilador", 0),
    ),
    "fechar": (
        ("/interf/abrir", "janela", 1),
        ("/interf/ligarar", "ar", 1),
        ("/interf/ligarventilador", "ventilador", 1),
    ),
    "umidificar": (
        ("/interf/desligarumidificador", "umidificador", 0),
    ),
    "iluminar": (
        ("/interf/desligarlampada", "lampada", 0),
    ),
}
_CORRECTION_OBJECTIVES: Final[dict[str, tuple[DecisionObjective, ...]]] = {
    "manter": ("umidade", "termico", "iluminacao", "manutencao"),
    "fechar": ("termico",),
    "ventilacao_natural": ("termico",),
    "ventilacao_assistida": ("termico",),
    "circulacao_interna": ("termico",),
    "resfriamento": ("termico",),
    "resfriamento_assistido": ("termico",),
    "umidificar": ("umidade",),
    "iluminar": ("iluminacao",),
}

JSON_INVALID: Final[ErrorCode] = "json_invalido"
MISSING_FIELD: Final[ErrorCode] = "campo_ausente"
UNKNOWN_FIELD: Final[ErrorCode] = "campo_desconhecido"
INVALID_TYPE: Final[ErrorCode] = "tipo_invalido"
INVALID_VALUE: Final[ErrorCode] = "valor_invalido"
INVALID_MODE: Final[ErrorCode] = "modo_invalido"
INVALID_PRESET: Final[ErrorCode] = "preset_invalido"
PRESET_NOT_SELECTED: Final[ErrorCode] = "preset_nao_selecionado"
DECISION_NOT_FOUND: Final[ErrorCode] = "decisao_inexistente"
DECISION_NOT_CONFIRMED: Final[ErrorCode] = "decisao_nao_confirmada"
DECISION_OBSOLETE: Final[ErrorCode] = "decisao_obsoleta"
COMMAND_NOT_CONFIRMED: Final[ErrorCode] = "comando_nao_confirmado"
CORRECTION_INCOMPATIBLE: Final[ErrorCode] = "correcao_incompativel"
FEEDBACK_CONFLICTING: Final[ErrorCode] = "feedback_conflitante"
PREFERENCE_AT_LIMIT: Final[ErrorCode] = "preferencia_no_limite"
UNSAFE_ACTION: Final[ErrorCode] = "acao_insegura"
RUN_NOT_FOUND: Final[ErrorCode] = "run_inexistente"
TRACE_CURSOR_PRUNED: Final[ErrorCode] = "trace_cursor_pruned"
INTERNAL_ERROR: Final[ErrorCode] = "erro_interno"

# Descriptive aliases retained for the naming variants used by integrations.
INCOMPATIBLE_CORRECTION: Final[ErrorCode] = CORRECTION_INCOMPATIBLE
CONFLICTING_FEEDBACK: Final[ErrorCode] = FEEDBACK_CONFLICTING
PREFERENCE_LIMIT: Final[ErrorCode] = PREFERENCE_AT_LIMIT

ERROR_CODES: Final[tuple[ErrorCode, ...]] = (
    JSON_INVALID,
    MISSING_FIELD,
    UNKNOWN_FIELD,
    INVALID_TYPE,
    INVALID_VALUE,
    INVALID_MODE,
    INVALID_PRESET,
    PRESET_NOT_SELECTED,
    DECISION_NOT_FOUND,
    DECISION_NOT_CONFIRMED,
    DECISION_OBSOLETE,
    COMMAND_NOT_CONFIRMED,
    CORRECTION_INCOMPATIBLE,
    FEEDBACK_CONFLICTING,
    PREFERENCE_AT_LIMIT,
    UNSAFE_ACTION,
    RUN_NOT_FOUND,
    TRACE_CURSOR_PRUNED,
    INTERNAL_ERROR,
)

_ERROR_STATUS_CODES: Final[dict[ErrorCode, int]] = {
    JSON_INVALID: 400,
    MISSING_FIELD: 400,
    UNKNOWN_FIELD: 400,
    INVALID_TYPE: 400,
    INVALID_VALUE: 400,
    INVALID_MODE: 400,
    INVALID_PRESET: 400,
    PRESET_NOT_SELECTED: 409,
    DECISION_NOT_FOUND: 409,
    DECISION_NOT_CONFIRMED: 409,
    DECISION_OBSOLETE: 409,
    COMMAND_NOT_CONFIRMED: 409,
    CORRECTION_INCOMPATIBLE: 409,
    FEEDBACK_CONFLICTING: 409,
    PREFERENCE_AT_LIMIT: 409,
    UNSAFE_ACTION: 409,
    RUN_NOT_FOUND: 404,
    TRACE_CURSOR_PRUNED: 410,
    INTERNAL_ERROR: 500,
}

# Kept as a symbol alias for callers that imported the pre-consolidation name.
# Its value is now the normative correction precondition code.
INCOMPATIBLE_FEEDBACK: Final[ErrorCode] = CORRECTION_INCOMPATIBLE

NO_BODY: Final[object] = object()
_CONFIRMED_COMMANDS_KEY: Final[str] = "_comandos_confirmados"


class ContractValidationError(ValueError):
    """Falha pública de contrato que pode ser serializada com segurança."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        fields: Iterable[str] | None = None,
        *,
        status_code: int | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError("Código de erro não pertence ao contrato público.")
        expected_status = _ERROR_STATUS_CODES[code]
        if status_code is not None and status_code != expected_status:
            raise ValueError("O status HTTP não corresponde ao código de erro.")
        self.code = code
        self.message = message
        self.fields = list(fields or [])
        self.status_code = expected_status
        super().__init__(message)


ValidationError = ContractValidationError


class PlanExecutionError(RuntimeError):
    """Falha de execução que conserva as etapas até o ponto da falha."""

    def __init__(self, message: str, failed_steps: Iterable[PlanStep]) -> None:
        self.failed_steps = deepcopy(list(failed_steps))
        super().__init__(message)


def _fail(
    code: ErrorCode,
    message: str,
    fields: Iterable[str] | None = None,
    *,
    status_code: int | None = None,
) -> NoReturn:
    raise ContractValidationError(
        code,
        message,
        fields,
        status_code=status_code,
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Restringe ``value`` ao intervalo fechado informado."""

    return max(minimum, min(maximum, value))


def advance_physics(
    current_temp: float,
    external_temp: float,
    window_open: bool,
    fan_on: bool,
    ac_on: bool,
) -> float:
    """Avança uma hora da temperatura de uma zona determinística.

    Args:
        current_temp: Temperatura interna atual em graus Celsius.
        external_temp: Temperatura externa em graus Celsius.
        window_open: Indica se a janela está aberta.
        fan_on: Indica se o ventilador está ligado.
        ac_on: Indica se o ar-condicionado está ligado.

    Returns:
        Temperatura interna limitada a 10..38 °C e arredondada a duas casas.
    """

    if window_open and fan_on:
        transfer_rate = 0.08
    elif window_open:
        transfer_rate = 0.06
    else:
        transfer_rate = 0.03

    air_effect = -0.75 if ac_on else 0.0
    next_temp = (
        current_temp + transfer_rate * (external_temp - current_temp) + air_effect
    )
    return round(_clamp(next_temp, MIN_TEMPERATURE_C, MAX_TEMPERATURE_C), 2)


def advance_humidity(
    current_humidity: float,
    window_open: bool,
    humidifier_on: bool,
) -> float:
    """Avança uma hora da umidade, saturando o resultado entre 0% e 100%.

    Args:
        current_humidity: Umidade relativa atual em porcentagem.
        window_open: Indica se a janela está aberta.
        humidifier_on: Indica se o umidificador está ligado.

    Returns:
        Umidade relativa limitada a 0..100%.

    Notes:
        Quando a umidade inicia o ciclo em 100% ou mais, o ciclo deve desligar
        o umidificador com ``apply_device_command`` antes de chamar esta
        evolução. Esta função recebe apenas os valores físicos necessários
        para calcular a variação e não altera o estado do quarto.
    """

    humidity_delta = (4.0 if humidifier_on else 0.0) + (
        -2.0 if window_open else 0.0
    )

    return _clamp(
        current_humidity + humidity_delta,
        MIN_HUMIDITY_PCT,
        MAX_HUMIDITY_PCT,
    )


def calculate_luminosity(
    hour: int,
    window_open: bool,
    rain: bool,
) -> Luminosity:
    """Calcula a classificação de luminosidade do quarto.

    Args:
        hour: Hora simulada entre 0 e 23.
        window_open: Indica se a janela está aberta.
        rain: Indica se está chovendo.

    Returns:
        ``escuro``, ``adequado`` ou ``claro`` após a redução causada pela
        chuva.

    Raises:
        ValueError: Se ``hour`` estiver fora do relógio simulado.
    """

    if not 0 <= hour <= 23:
        raise ValueError("hour must be between 0 and 23")

    if hour <= 5 or hour >= 18:
        luminosity: Luminosity = "escuro"
    elif hour <= 8 or hour == 17:
        luminosity = "adequado"
    else:
        luminosity = "claro" if window_open else "adequado"

    if not rain:
        return luminosity
    if luminosity == "claro":
        return "adequado"
    return "escuro"


def read_sensors(state: RoomState) -> SensorReadings:
    """Lê uma cópia dos valores observáveis do estado autoritativo.

    Args:
        state: Estado atual do quarto.

    Returns:
        Dicionário novo contendo as leituras ambientais e de contexto. Os
        valores são escalares e não compartilham estruturas mutáveis com o
        estado recebido.
    """

    return {
        "temperatura_interna": state["temperatura_interna"],
        "temperatura_externa": state["temperatura_externa"],
        "umidade": state["umidade"],
        "luminosidade": state["luminosidade"],
        "chuva": state["chuva"],
        "presenca_interna": state["presenca_interna"],
        "presenca_externa": state["presenca_externa"],
        "dormir": state["dormir"],
    }


def apply_device_command(
    state: RoomState,
    device: str,
    value: int,
) -> DeviceConfirmation:
    """Aplica e confirma um comando binário de um atuador local.

    Args:
        state: Estado autoritativo do quarto a atualizar.
        device: Um dos cinco dispositivos canônicos do simulador.
        value: Estado binário solicitado, ``0`` ou ``1``.

    Returns:
        Confirmação neutra quando o valor já era o atual ou confirmação da
        alteração aplicada, sempre com o mesmo formato.

    Raises:
        KeyError: Se ``device`` não for um dispositivo canônico.
        ValueError: Se ``value`` não for um inteiro binário.
    """

    if device not in _DEVICE_NAMES:
        raise KeyError(f"Dispositivo desconhecido: {device!r}")
    if type(value) is not int or value not in (0, 1):
        raise ValueError("O comando do dispositivo deve ser 0 ou 1")

    device_name = device
    command = cast(Binary, value)
    confirmation: DeviceConfirmation = {
        "dispositivo": device_name,
        "comando": command,
        "status": "confirmado",
    }
    if state["dispositivos"][device_name] == command:
        return confirmation
    state["dispositivos"][device_name] = command
    return confirmation


def _ensure_window_opening_is_safe(
    state: RoomState,
    device: DeviceName,
    command: Binary,
) -> None:
    """Reject a window opening that violates the room safety constraints."""

    if device != "janela" or command != 1:
        return

    reasons: list[str] = []
    if state["chuva"] == 1:
        reasons.append("chuva detectada")
    if state["presenca_externa"] == 1:
        reasons.append("presença externa detectada")
    if state["dispositivos"]["ar"] == 1:
        reasons.append("ar-condicionado ligado")
    if reasons:
        _fail(
            UNSAFE_ACTION,
            f"A abertura da janela é insegura: {', '.join(reasons)}.",
            ["dispositivo"],
        )


def _ensure_device_command_is_safe(
    state: RoomState,
    device: DeviceName,
    command: Binary,
) -> None:
    """Reject actuator commands that violate live interlocks or saturation."""

    devices = state["dispositivos"]
    unsafe_window = devices["janela"] == 1 and (
        state["chuva"] == 1 or state["presenca_externa"] == 1
    )
    interlock_conflict = devices["janela"] == 1 and devices["ar"] == 1
    if unsafe_window and not (device == "janela" and command == 0):
        _fail(
            UNSAFE_ACTION,
            "O estado atual exige fechar a janela antes de outros comandos.",
            ["dispositivo"],
        )
    if interlock_conflict and not (
        (device == "janela" and command == 0)
        or (device == "ar" and command == 0)
    ):
        _fail(
            UNSAFE_ACTION,
            "O estado atual viola o intertravamento entre janela e ar-condicionado.",
            ["dispositivo"],
        )
    _ensure_window_opening_is_safe(state, device, command)
    if device == "ar" and command == 1 and devices["janela"] == 1:
        _fail(
            UNSAFE_ACTION,
            "Ligar o ar-condicionado com a janela aberta é inseguro.",
            ["dispositivo"],
        )
    if (
        device == "umidificador"
        and command == 1
        and state["umidade"] >= MAX_HUMIDITY_PCT
    ):
        _fail(
            UNSAFE_ACTION,
            "Ligar o umidificador com a umidade em 100% é inseguro.",
            ["dispositivo"],
        )


def _ensure_preset_selected(state: RoomState) -> None:
    """Require an explicitly selected preset before a stateful journey step."""

    if state["preset_atual"] is None:
        _fail(
            PRESET_NOT_SELECTED,
            "Selecione um preset antes de executar esta operação.",
            ["preset"],
        )


def _normalise_action(action: ActionName | str) -> ActionName:
    """Valida e estreita o nome de ação usado pelo plano binário."""

    canonical_action = _ACTION_ALIASES.get(action, action)
    if canonical_action not in _PLAN_STEPS:
        raise ValueError(f"Ação desconhecida: {action!r}")
    return cast(ActionName, canonical_action)


def _normalise_mode(mode: Mode | str) -> Mode:
    """Validate and narrow a decision mode used by the cycle."""

    if mode not in {"reativo", "cognitivo"}:
        raise ValueError(f"Modo desconhecido: {mode!r}")
    return cast(Mode, mode)


def _temperature_band(
    temperature: float,
) -> TemperatureBand:
    """Classifica a temperatura nos limites térmicos da SPEC."""

    if temperature < TEMP_COLD_LIMIT_C:
        return "frio"
    if temperature > TEMP_HOT_LIMIT_C:
        return "calor"
    return "conforto"


def build_learning_context(state: RoomState) -> LearningContext:
    """Captura o contexto exato usado para indexar a aprendizagem.

    A identidade usa a linhagem do preset, o modo cognitivo e faixas
    observáveis, sem carregar a hora crua para a chave de preferência.
    """

    readings = read_sensors(state)
    preset = state["preset_atual"] or "conforto"
    return {
        "hora": state["hora"],
        "preset": preset,
        "modo": "cognitivo",
        "faixa_horario": _time_band(state["hora"]),
        "dormir": readings["dormir"],
        "faixa_temperatura": _temperature_band(readings["temperatura_interna"]),
        "luminosidade": readings["luminosidade"],
        "presenca_interna": readings["presenca_interna"],
    }


def _time_band(hour: int) -> TimeBand:
    """Classifica uma hora na faixa normativa da identidade."""

    if hour >= 23 or hour <= 4:
        return "madrugada"
    if hour <= 7:
        return "amanhecer"
    if hour <= 17:
        return "dia"
    return "noite"


def _learning_identity(
    state: RoomState,
    context: LearningContext,
    mode: Mode,
) -> LearningIdentity:
    """Materializa a identidade imutável observada no snapshot da decisão."""

    return {
        "preset": context["preset"],
        "modo": cast(CognitiveMode, mode),
        "faixa_horario": context["faixa_horario"],
        "dormir": context["dormir"],
        "faixa_temperatura": context["faixa_temperatura"],
        "luminosidade": context["luminosidade"],
        "presenca_interna": context["presenca_interna"],
    }


def _strategy_id(action: ActionName | str) -> str:
    """Normalize a displayed action to its canonical preference strategy."""

    if action == "umidificacao":
        return "umidificacao"
    if action == "iluminacao":
        return "iluminacao"
    canonical_action = _normalise_action(action)
    if canonical_action == "umidificar":
        return "umidificacao"
    if canonical_action == "iluminar":
        return "iluminacao"
    if canonical_action == "fechar":
        return "manter"
    return canonical_action


def _default_preference_objective(action: ActionName | str) -> DecisionObjective:
    """Infer the legacy helper's objective when callers omit it."""

    strategy_id = _strategy_id(action)
    if strategy_id == "umidificacao":
        return "umidade"
    if strategy_id == "iluminacao":
        return "iluminacao"
    if action == "fechar":
        return "seguranca"
    return "termico"


def _preference_key_for_strategy(
    objective: DecisionObjective | str,
    strategy_id: str,
) -> PreferenceKey:
    """Serialize only the objective and canonical strategy as memory identity."""

    return json.dumps(
        (objective, _strategy_id(strategy_id)),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _preference_key(
    context: LearningContext,
    action: ActionName | str,
    objective: DecisionObjective | None = None,
) -> PreferenceKey:
    """Return the normative preference key, keeping context explanatory only."""

    selected_objective = objective or _default_preference_objective(action)
    _ = context
    return _preference_key_for_strategy(selected_objective, _strategy_id(action))


def _preference_for(
    state: RoomState,
    context: LearningContext,
    action: ActionName | str,
    objective: DecisionObjective | None = None,
) -> int:
    """Read the preference for an objective and strategy pair."""

    value = state["preferencias"].get(
        _preference_key(context, action, objective),
        0,
    )
    if type(value) is not int:
        raise ValueError("A preferência deve ser um inteiro.")
    return max(-3, min(3, value))


def _effective_thermal_preference(
    state: RoomState,
    context: LearningContext,
    action: ActionName,
    final_devices: Mapping[str, object],
) -> int:
    """Share feedback only between the two active air-conditioning strategies."""

    direct = _preference_for(state, context, action, "termico")
    if final_devices.get("ar") != 1:
        return direct
    if action == "resfriamento":
        related_action = "resfriamento_assistido"
    elif action == "resfriamento_assistido":
        related_action = "resfriamento"
    else:
        return direct
    family = min(
        0,
        _preference_for(state, context, related_action, "termico"),
    )
    return max(-3, min(3, direct + family))


def _allowed_corrections(action: ActionName) -> list[CorrectionCommand]:
    """Materializa a matriz inversa no formato do contrato da decisão."""

    corrections: list[CorrectionCommand] = []
    for route, device, command in _CORRECTION_MATRIX.get(
        _normalise_action(action), ()
    ):
        corrections.append(
            {
                "rota": route,
                "dispositivo": device,
                "comando": command,
            }
        )
    return corrections


def _normalise_feedback_type(feedback_type: str) -> tuple[FeedbackType, Literal[-1, 1]]:
    """Valida nomes de feedback e retorna seu delta canônico."""

    try:
        return _FEEDBACK_DELTAS[feedback_type]
    except (KeyError, TypeError):
        _fail(
            INVALID_TYPE,
            f"Tipo de feedback desconhecido: {feedback_type!r}.",
            ["tipo"],
        )


def _lighting_required(readings: SensorReadings) -> bool:
    """Indica se o contexto atual requer a lâmpada ligada."""

    return (
        readings["luminosidade"] == "escuro"
        and readings["presenca_interna"] == 1
        and readings["dormir"] == 0
    )


def _lighting_action_pending(
    readings: SensorReadings,
    devices: Mapping[str, object],
) -> bool:
    """Indica se a iluminação necessária ainda não está atendida."""

    return _lighting_required(readings) and devices.get("lampada") == 0


def _cold_action_pending(devices: Mapping[str, object]) -> bool:
    """Indica se o plano de fechamento térmico ainda precisa atuar."""

    return any(
        devices.get(device) == 1
        for device in ("janela", "ar", "ventilador")
    )


def _climate_shutdown_pending(devices: Mapping[str, object]) -> bool:
    """Indica se ainda há climatização ativa para desligar no conforto."""

    return any(
        devices.get(device) == 1
        for device in ("ar", "ventilador")
    )


def calculate_comfort(temperature: float) -> float:
    """Calculate normalized thermal comfort for one room temperature."""

    if 22 <= temperature <= 25:
        comfort = 1.0
    elif temperature < 22:
        comfort = _clamp((temperature - 10) / 12, 0.0, 1.0)
    else:
        comfort = _clamp((38 - temperature) / 13, 0.0, 1.0)
    return round(comfort, 2)


def calculate_cost(device_state: Mapping[str, object]) -> int:
    """Sum the hourly cost of devices that are on in a final state."""

    return sum(
        cost
        for device, cost in _DEVICE_COSTS.items()
        if device_state.get(device) == 1
    )


def calculate_economy(cost: int) -> float:
    """Calculate rounded economy from the final device cost."""

    return round(_clamp(1 - cost / 5, 0.0, 1.0), 2)


def calculate_preference_adjustment(preference: int) -> float:
    """Convert bounded learning preference into its normative score offset."""

    return round(_clamp(preference / 10, -0.3, 0.3), 2)


def _calculate_base_score(comfort: float, economy: float) -> float:
    """Calculate the normative weighted score before preference adjustment."""

    return 0.6 * comfort + 0.4 * economy


def calculate_utility(
    conforto: float,
    economia: float,
    preferencia: int,
) -> float:
    """Calculate total utility with the normalized preference offset."""

    adjustment = calculate_preference_adjustment(preferencia)
    return round(_calculate_base_score(conforto, economia) + adjustment, 2)


def _cognitive_actions(
    state: RoomState,
) -> tuple[tuple[ActionName, ...], DecisionObjective]:
    """Seleciona as alternativas do objetivo prioritário do ciclo."""

    readings = read_sensors(state)
    devices = state["dispositivos"]
    window_open = devices["janela"] == 1
    unsafe_window = window_open and (
        readings["chuva"] == 1 or readings["presenca_externa"] == 1
    )
    interlock_conflict = devices["janela"] == 1 and devices["ar"] == 1
    temperature = readings["temperatura_interna"]

    if unsafe_window or interlock_conflict or readings["presenca_interna"] == 0:
        return ("fechar",), "seguranca"
    if readings["umidade"] < 40:
        return ("umidificar", "manter"), "umidade"
    if temperature < TEMP_COLD_LIMIT_C and _cold_action_pending(devices):
        return ("fechar",), "termico"
    if temperature > COGNITIVE_COOL_ON_C or devices["ar"] == 1:
        return _thermal_actions(state), "termico"
    if temperature <= TEMP_CLIMATE_OFF_C and _climate_shutdown_pending(devices):
        return ("manter",), "termico"
    if _lighting_action_pending(readings, devices):
        return ("iluminar", "manter"), "iluminacao"
    return ("manter",), "manutencao"


def _thermal_vector(
    action: str,
    devices: Mapping[str, object],
) -> tuple[object, object, object]:
    """Return a candidate's canonical (window, AC, fan) vector."""

    canonical_action = _normalise_action(action)
    if canonical_action == "manter":
        return (
            devices.get("janela"),
            devices.get("ar"),
            devices.get("ventilador"),
        )
    return _THERMAL_VECTORS[cast(StrategyId, canonical_action)]


def _strategy_for_thermal_vector(
    vector: Mapping[str, object],
) -> StrategyId | None:
    """Match an exact canonical thermal vector to one preference strategy."""

    values = tuple(vector.get(device) for device in ("janela", "ar", "ventilador"))
    if any(type(value) is not int or value not in (0, 1) for value in values):
        return None
    observed = cast(tuple[Binary, Binary, Binary], values)
    for strategy_id, candidate in _THERMAL_MATCH_VECTORS.items():
        if observed == candidate:
            return strategy_id
    return None


def _thermal_actions(state: RoomState) -> tuple[ActionName, ...]:
    """List thermal strategies once each, in canonical order.

    ``manter`` e a estratégia nomeada do vetor atual são leituras distintas do
    mesmo estado e ambas permanecem na lista; somente estratégias nomeadas com
    o mesmo vetor seriam duplicatas.
    """

    actions: list[ActionName] = []
    seen_vectors: set[tuple[object, object, object]] = set()
    for strategy_id in _THERMAL_STRATEGIES:
        vector = _thermal_vector(strategy_id, state["dispositivos"])
        if strategy_id != "manter":
            if vector in seen_vectors:
                continue
            seen_vectors.add(vector)
        actions.append(cast(ActionName, strategy_id))
    return tuple(actions)


def _devices_after_action(
    action: ActionName,
    state: RoomState,
    objective: DecisionObjective,
) -> dict[str, object]:
    """Project the device vector after the same plan used by a decision."""

    final_devices = cast(
        dict[str, object],
        deepcopy(dict(state["dispositivos"])),
    )
    plan = _build_decision_plan(
        action,
        read_sensors(state),
        state["dispositivos"],
        objective=objective,
        mode="cognitivo",
    )
    for step in plan:
        final_devices[step["dispositivo"]] = step["comando"]
    return final_devices


def _thermal_forecast(
    state: RoomState,
    devices: Mapping[str, object],
) -> tuple[float, float, float]:
    """Forecast three hours with the candidate vector held constant."""

    temperature = state["temperatura_interna"]
    comfort_values: list[float] = []
    first_temperature = temperature
    for hour in range(THERMAL_HORIZON_HOURS):
        temperature = advance_physics(
            temperature,
            state["temperatura_externa"],
            devices.get("janela") == 1,
            devices.get("ventilador") == 1,
            devices.get("ar") == 1,
        )
        if hour == 0:
            first_temperature = temperature
        comfort_values.append(
            calculate_comfort(_perceived_temperature(temperature, devices))
        )
    mean_comfort = round(sum(comfort_values) / len(comfort_values), 2)
    return first_temperature, temperature, mean_comfort


def _thermal_switch_penalty(
    current: Mapping[str, object],
    final: Mapping[str, object],
) -> float:
    changes = sum(
        current.get(device) != final.get(device)
        for device in ("janela", "ar", "ventilador")
    )
    return round(changes * THERMAL_SWITCH_PENALTY, 2)


def _perceived_temperature(
    projected_temperature: float,
    devices: Mapping[str, object],
) -> float:
    """Apply the perceived relief of airflow without touching simulated physics."""

    cooling = 0.0
    if devices.get("ventilador") == 1:
        cooling += PERCEIVED_AIRFLOW_COOLING_C
        if devices.get("janela") == 1:
            cooling += PERCEIVED_EXCHANGE_COOLING_C
    return projected_temperature - cooling


def _alternative_comfort(
    action: ActionName,
    objective: DecisionObjective,
    state: RoomState,
) -> float:
    """Score the candidate against its objective and projected temperature."""

    canonical_action = _normalise_action(action)
    if objective == "umidade":
        return 1.0 if canonical_action == "umidificar" else 0.0
    if objective == "iluminacao":
        return 1.0 if canonical_action == "iluminar" else 0.0
    if objective == "seguranca":
        return 1.0 if canonical_action == "fechar" else 0.0
    if objective == "manutencao":
        return 1.0 if canonical_action == "manter" else 0.0

    devices = _devices_after_action(canonical_action, state, objective)
    predicted_temperature = advance_physics(
        state["temperatura_interna"],
        state["temperatura_externa"],
        devices.get("janela") == 1,
        devices.get("ventilador") == 1,
        devices.get("ar") == 1,
    )
    return calculate_comfort(
        _perceived_temperature(predicted_temperature, devices)
    )


def _alternative_block_reason(
    action: ActionName,
    state: RoomState,
    objective: DecisionObjective,
) -> str | None:
    """Explica por que uma alternativa não pode ser escolhida no ciclo."""

    canonical_action = _normalise_action(action)
    readings = read_sensors(state)
    devices: dict[str, object] = deepcopy(dict(state["dispositivos"]))
    invalid_open_window = devices["janela"] == 1 and (
        readings["chuva"] == 1
        or readings["presenca_externa"] == 1
        or devices["ar"] == 1
    )
    if invalid_open_window and canonical_action != "fechar":
        return "estado recebido inseguro: é necessário fechar a janela primeiro"
    if objective == "termico" and canonical_action in _THERMAL_STRATEGIES:
        temperature = readings["temperatura_interna"]
        thermal_floor = (
            COGNITIVE_CLIMATE_OFF_C
            if devices.get("ar") == 1
            else TEMP_HOT_LIMIT_C
        )
        if temperature > thermal_floor:
            final_devices = _devices_after_action(canonical_action, state, objective)
            projected_temperature, horizon_temperature, _ = _thermal_forecast(
                state, final_devices
            )
            if projected_temperature >= temperature:
                context = build_learning_context(state)
                cooling_aversion = any(
                    _preference_for(state, context, cooling, "termico") < 0
                    for cooling in ("resfriamento", "resfriamento_assistido")
                )
                chosen_preference = _preference_for(
                    state, context, canonical_action, "termico"
                )
                learned_tradeoff = (
                    final_devices["ar"] == 0
                    and (cooling_aversion or chosen_preference > 0)
                )
                if not learned_tradeoff:
                    if (
                        final_devices["janela"] == 1
                        and readings["temperatura_externa"] >= temperature
                    ):
                        return "o ar externo está tão quente quanto o quarto; abrir a janela aumentaria o calor"
                    return "a estratégia não reduz a temperatura do quarto neste ciclo"
                if horizon_temperature > LEARNED_HEAT_CEILING_C:
                    return (
                        "a temperatura prevista em três horas excede "
                        "o limite de tolerância térmica de 32 °C"
                    )
    if canonical_action in {"ventilacao_natural", "ventilacao_assistida"}:
        if readings["chuva"] == 1:
            return "chuva detectada: abertura da janela bloqueada"
        if readings["presenca_externa"] == 1:
            return "presença externa detectada: abertura da janela bloqueada"
    if canonical_action == "iluminar" and not _lighting_required(readings):
        return "iluminação não requerida pelo estado atual"
    if canonical_action == "manter":
        if devices["janela"] == 1 and readings["chuva"] == 1:
            return "segurança: manter a janela aberta sob chuva é bloqueado"
        if devices["janela"] == 1 and readings["presenca_externa"] == 1:
            return "segurança: manter a janela aberta com presença externa é bloqueado"
        if devices["janela"] == 1 and devices["ar"] == 1:
            return "intertravamento: janela aberta e ar ligado são incompatíveis"
    for device, command in _PLAN_STEPS[canonical_action]:
        reason: str | None = None
        if device == "janela" and command == 1:
            if readings["chuva"] == 1:
                reason = "chuva detectada: abertura da janela bloqueada"
            elif readings["presenca_externa"] == 1:
                reason = "presença externa detectada: abertura da janela bloqueada"
            elif devices.get("ar") == 1:
                reason = "intertravamento: ar ligado impede a abertura da janela"
        elif device == "ar" and command == 1 and devices.get("janela") == 1:
            reason = "intertravamento: ar ligado com janela aberta é bloqueado"
        elif (
            device == "umidificador"
            and command == 1
            and readings["umidade"] >= MAX_HUMIDITY_PCT
        ):
            reason = "saturação: umidificador bloqueado com umidade em 100%"
        if reason is not None:
            return reason
        devices[device] = command
    return None


def _select_cognitive_alternative(
    alternatives: Iterable[DecisionAlternative],
    state: RoomState,
    score_field: Literal["pontuacao_base", "pontuacao_total"],
) -> DecisionAlternative:
    """Seleciona a melhor alternativa por uma pontuação já calculada."""

    eligible = [
        alternative
        for alternative in alternatives
        if alternative["elegivel"]
    ]
    if not eligible:
        raise RuntimeError("Nenhuma alternativa cognitiva elegível")

    def order_key(alternative: DecisionAlternative) -> tuple[float, float, int, int]:
        score = alternative[score_field]
        comfort = alternative.get("conforto")
        cost = alternative.get("custo")
        if score is None or comfort is None or cost is None:
            raise RuntimeError("Alternativa elegível sem pontuação normativa")
        strategy_id = _alternative_strategy_id(alternative)
        return (-score, -comfort, cost, _ACTION_ORDER[strategy_id])

    _ = state
    return min(eligible, key=order_key)


def evaluate_alternatives(state: RoomState) -> list[DecisionAlternative]:
    """Avalia somente as alternativas do objetivo prioritário atual.

    A avaliação é pura: não executa planos, altera dispositivos ou consulta a
    temperatura externa. A preferência é lida pelo objetivo e strategy_id.
    """

    actions, objective = _cognitive_actions(state)
    return _evaluate_objective_alternatives(state, actions, objective)


def _evaluate_objective_alternatives(
    state: RoomState,
    actions: Iterable[ActionName],
    objective: DecisionObjective,
    *,
    compare_preferences: bool = True,
) -> list[DecisionAlternative]:
    """Aplica a mesma utilidade e aprendizagem a um objetivo independente."""

    action_list = tuple(actions)
    context = build_learning_context(state)
    alternatives: list[DecisionAlternative] = []
    for action in action_list:
        canonical_action = _normalise_action(action)
        blocked_reason = _alternative_block_reason(
            canonical_action, state, objective
        )
        eligible = blocked_reason is None
        corrections = (
            _allowed_corrections(canonical_action)
            if eligible and objective != "seguranca"
            else []
        )
        preference = 0
        comfort: float | None = None
        cost: int | None = None
        economy: float | None = None
        base_score: float | None = None
        total_score: float | None = None
        utility: float | None = None
        preference_adjustment = 0.0
        direct_preference = 0
        first_temperature: float | None = None
        horizon_temperature: float | None = None
        horizon_comfort: float | None = None
        switch_penalty = 0.0
        if eligible:
            final_devices = _devices_after_action(canonical_action, state, objective)
            direct_preference = _preference_for(
                state, context, canonical_action, objective
            )
            preference = (
                _effective_thermal_preference(
                    state, context, canonical_action, final_devices
                )
                if objective == "termico" and canonical_action in _THERMAL_STRATEGIES
                else direct_preference
            )
            comfort = _alternative_comfort(canonical_action, objective, state)
            cost = calculate_cost(final_devices)
            economy = calculate_economy(cost)
            if objective == "termico" and canonical_action in _THERMAL_STRATEGIES:
                first_temperature, horizon_temperature, horizon_comfort = (
                    _thermal_forecast(state, final_devices)
                )
                switch_penalty = _thermal_switch_penalty(
                    state["dispositivos"], final_devices
                )
                base_score = (
                    _calculate_base_score(horizon_comfort, economy) - switch_penalty
                )
            else:
                base_score = _calculate_base_score(comfort, economy)
            preference_adjustment = calculate_preference_adjustment(preference)
            total_score = round(base_score + preference_adjustment, 2)
            utility = total_score
        alternatives.append(
            {
                "acao": cast(ActionName, _legacy_action(canonical_action)),
                "strategy_id": canonical_action,
                "pontuacao_base": base_score,
                "preferencia_contextual": preference,
                "pontuacao_total": total_score,
                "elegivel": eligible,
                "influenciada": preference != 0,
                "motivo_bloqueio": blocked_reason,
                "correcoes_permitidas": corrections,
                "conforto": comfort,
                "economia": economy,
                "custo": cost,
                "preferencia": preference_adjustment,
                "utilidade": utility,
                "temperatura_projetada": first_temperature,
                "temperatura_em_tres_horas": horizon_temperature,
                "conforto_horizonte": horizon_comfort,
                "penalidade_troca": switch_penalty,
                "preferencia_estrategia": direct_preference,
                "ajuste_familia_ar": preference - direct_preference,
            }
        )

    if not any(alternative["elegivel"] for alternative in alternatives):
        return alternatives
    if not compare_preferences:
        return alternatives

    baseline_state = cast(RoomState, {**state, "preferencias": {}})
    baseline_alternatives = _evaluate_objective_alternatives(
        baseline_state,
        action_list,
        objective,
        compare_preferences=False,
    )
    winner = _select_cognitive_alternative(alternatives, state, "pontuacao_total")
    baseline_eligible = [
        item for item in baseline_alternatives if item["elegivel"]
    ]
    baseline_winner = (
        _select_cognitive_alternative(
            baseline_alternatives,
            baseline_state,
            "pontuacao_total",
        )
        if baseline_eligible
        else None
    )
    winner_changed_without_preferences = (
        baseline_winner is None
        or _alternative_strategy_id(winner) != _alternative_strategy_id(baseline_winner)
    )
    baseline_by_strategy = {
        _alternative_strategy_id(item): item for item in baseline_alternatives
    }
    for alternative in alternatives:
        baseline_alternative = baseline_by_strategy[
            _alternative_strategy_id(alternative)
        ]
        alternative["influenciada"] = (
            alternative["preferencia_contextual"] != 0
            or alternative["elegivel"] != baseline_alternative["elegivel"]
            or (
                winner_changed_without_preferences
                and _alternative_strategy_id(alternative)
                == _alternative_strategy_id(winner)
            )
        )
    return alternatives


def _alternative_strategy_id(alternative: DecisionAlternative) -> str:
    """Read a canonical strategy identifier with support for old alternatives."""

    value = alternative.get("strategy_id")
    if isinstance(value, str):
        return _normalise_action(value)
    return _normalise_action(alternative["acao"])


def _legacy_action(action: ActionName | str) -> str:
    """Translate canonical thermal identifiers for the legacy `acao` field."""

    canonical_action = _normalise_action(action)
    return _LEGACY_THERMAL_ACTIONS.get(canonical_action, canonical_action)


def _strategy_explanation_label(strategy: str, state: RoomState) -> str:
    if strategy == "manter":
        if state["dispositivos"]["ar"] == 1:
            return "manter o ar-condicionado ligado"
        return "manter os dispositivos como estão"
    return {
        "ventilacao_natural": "ventilação natural",
        "ventilacao_assistida": "ventilação com ventilador",
        "circulacao_interna": "circulação interna",
        "resfriamento": "resfriamento com ar-condicionado",
        "resfriamento_assistido": "resfriamento com ar e ventilador",
        "umidificacao": "umidificação",
        "iluminacao": "iluminação",
    }.get(strategy, strategy)


def _learning_influence_message(
    state: RoomState,
    winner: DecisionAlternative,
    baseline_winner: DecisionAlternative,
    alternatives: list[DecisionAlternative],
    baseline_alternatives: list[DecisionAlternative],
) -> tuple[bool, str]:
    """Explain the causal effect of learned preferences on the primary choice."""

    chosen = _alternative_strategy_id(winner)
    baseline = _alternative_strategy_id(baseline_winner)
    chosen_label = _strategy_explanation_label(chosen, state)
    baseline_label = _strategy_explanation_label(baseline, state)
    baseline_by_strategy = {
        _alternative_strategy_id(item): item for item in baseline_alternatives
    }
    actual_by_strategy = {
        _alternative_strategy_id(item): item for item in alternatives
    }
    eligibility_changed = any(
        item["elegivel"] != baseline_by_strategy[strategy]["elegivel"]
        for strategy, item in actual_by_strategy.items()
    )
    applicable_preference = any(
        item["elegivel"] and item["preferencia_contextual"] != 0
        for item in alternatives
    )
    if chosen != baseline:
        if not baseline_by_strategy[chosen]["elegivel"]:
            context = build_learning_context(state)
            cooling_rejected = any(
                _preference_for(state, context, cooling, "termico") < 0
                for cooling in ("resfriamento", "resfriamento_assistido")
            )
            source = (
                "a rejeição anterior ao ar-condicionado"
                if cooling_rejected and winner["preferencia_contextual"] == 0
                else "a preferência aprendida"
            )
            return (
                True,
                f"Sem preferências, a escolha seria {baseline_label}; {source} "
                f"liberou a opção de {chosen_label} e alterou a escolha.",
            )
        competitor = actual_by_strategy[baseline]
        if (
            winner["preferencia_contextual"] == 0
            and competitor["preferencia_contextual"] < 0
        ):
            return (
                True,
                f"Sem preferências, a escolha seria {baseline_label}; a penalização "
                f"aprendida de {baseline_label} alterou a escolha para {chosen_label}.",
            )
        return (
            True,
            f"Sem preferências, a escolha seria {baseline_label}; a preferência "
            f"aprendida alterou a escolha para {chosen_label}.",
        )
    if applicable_preference or eligibility_changed:
        return (
            True,
            f"Sem preferências, {chosen_label} também venceria; a preferência aprendida "
            "foi considerada, mas não alterou a vencedora.",
        )
    return False, "Nenhuma preferência aprendida influenciou esta escolha."


def _cognitive_decision_reason(
    objective: DecisionObjective,
    winner: DecisionAlternative,
) -> str:
    """Explica o efeito causal da preferência sobre a alternativa vencedora."""

    action = _legacy_action(_alternative_strategy_id(winner))
    preference = winner["preferencia_contextual"]
    score = winner["pontuacao_total"]
    base_score = winner["pontuacao_base"]
    causal_reason = winner.get(
        "motivo_influencia", "Nenhuma preferência aprendida influenciou esta escolha."
    )
    forecast = winner.get("temperatura_em_tres_horas")
    first = winner.get("temperatura_projetada")
    forecast_reason = (
        f" Temperatura física prevista: {first:.1f} °C no próximo ciclo e "
        f"{forecast:.1f} °C em três ciclos; penalidade por troca "
        f"{winner.get('penalidade_troca', 0.0):.2f}."
        if isinstance(first, (int, float)) and isinstance(forecast, (int, float))
        else ""
    )
    return (
        f"Objetivo {objective}: ação {action} escolhida com pontuação-base "
        f"{base_score:.2f}, preferência contextual {preference:+d} e "
        f"pontuação total {score:.2f}. {causal_reason}"
        f"{forecast_reason}"
    )


def choose_cognitive_action(state: RoomState) -> ActionName:
    """Escolhe a alternativa elegível de maior utilidade determinística."""

    evaluated = evaluate_alternatives(state)
    winner = _select_cognitive_alternative(
        evaluated,
        state,
        "pontuacao_total",
    )
    return cast(ActionName, _alternative_strategy_id(winner))


def _preventive_commands(
    readings: SensorReadings,
    devices: Mapping[str, object],
) -> list[tuple[DeviceName, Binary]]:
    """Lista comandos preventivos que devem preceder a ação escolhida."""

    if readings["presenca_interna"] == 0:
        return []
    commands: list[tuple[DeviceName, Binary]] = []
    if readings["umidade"] >= MAX_HUMIDITY_PCT and devices.get("umidificador") == 1:
        commands.append(("umidificador", 0))
    return commands


def _preventive_reason_suffix(
    readings: SensorReadings,
    devices: Mapping[str, object],
) -> str:
    """Explica comandos preventivos agregados ao plano da decisão."""

    if readings["presenca_interna"] == 0:
        return ""
    details: list[str] = []
    if readings["umidade"] >= MAX_HUMIDITY_PCT and devices.get("umidificador") == 1:
        details.append("umidade alta: desligando preventivamente o umidificador")
    return f" {'; '.join(details)}." if details else ""


def _reactive_rule(
    state: RoomState,
) -> tuple[ActionName, DecisionObjective, str]:
    """Aplica a precedência reativa e explica a primeira regra satisfeita."""

    readings = read_sensors(state)
    devices = state["dispositivos"]
    preventive_suffix = _preventive_reason_suffix(readings, devices)
    lighting_off_suffix = (
        " condição de iluminação inativa: desligando a lâmpada."
        if not _lighting_required(readings) and devices.get("lampada") == 1
        else ""
    )

    security_reasons: list[str] = []
    if readings["chuva"] == 1:
        security_reasons.append("chuva detectada")
    if readings["presenca_externa"] == 1:
        security_reasons.append("presença externa detectada")
    if devices["janela"] == 1 and devices["ar"] == 1:
        security_reasons.append("intertravamento entre janela aberta e ar ligado")
    if devices["janela"] == 1 and security_reasons:
        details = "; ".join(security_reasons)
        return (
            "fechar",
            "seguranca",
            f"Segurança da janela: {details}; fechando a janela."
            f"{preventive_suffix}",
        )

    if readings["presenca_interna"] == 0:
        return (
            "fechar",
            "seguranca",
            "Sem presença interna; desligando os dispositivos e fechando a janela.",
        )

    humidity = readings["umidade"]
    if humidity < 40:
        return (
            "umidificar",
            "umidade",
            f"Umidade abaixo de 40% ({humidity:.1f}%); ligando o umidificador."
            f"{preventive_suffix}",
        )

    temperature = readings["temperatura_interna"]
    if temperature > TEMP_HOT_LIMIT_C:
        return (
            "resfriar",
            "termico",
            f"Calor acima de {TEMP_HOT_LIMIT_C:g} °C ({temperature:.1f} °C); "
            f"resfriando o quarto.{preventive_suffix}",
        )
    if temperature < TEMP_COLD_LIMIT_C and _cold_action_pending(devices):
        return (
            "fechar",
            "termico",
            f"Frio abaixo de {TEMP_COLD_LIMIT_C:g} °C ({temperature:.1f} °C); "
            f"fechando a janela.{preventive_suffix}",
        )
    if temperature <= TEMP_CLIMATE_OFF_C and _climate_shutdown_pending(devices):
        return (
            "manter",
            "termico",
            f"Temperatura em {TEMP_CLIMATE_OFF_C:g} °C ou menos; "
            f"desligando a climatização.{preventive_suffix}",
        )

    if _lighting_action_pending(readings, devices):
        return (
            "iluminar",
            "iluminacao",
            f"Quarto escuro, ocupado e acordado; ligando a lâmpada."
            f"{preventive_suffix}",
        )

    return (
        "manter",
        "manutencao",
        f"Nenhuma condição prioritária ativa; mantendo o estado."
        f"{preventive_suffix}"
        f"{lighting_off_suffix}",
    )


def choose_reactive_action(state: RoomState) -> ActionName:
    """Escolhe uma ação pela ordem fixa da política reativa.

    A segurança da janela é avaliada antes das regras de umidade, temperatura,
    iluminação e manutenção. A função é deliberadamente pura: não executa
    comandos, não avança a física e não altera preferências.
    """

    action, _, _ = _reactive_rule(state)
    return action


def build_plan(
    action: ActionName | str,
    device_state: Mapping[str, object] | None = None,
) -> list[PlanStep]:
    """Converte uma ação em etapas binárias na ordem causal definida.

    Quando um dispositivo já está no valor solicitado, sua etapa continua no
    plano como confirmação neutra. Nenhuma entrada é mutada nesta conversão;
    uma etapa pendente só descreve o comando que o executor deverá confirmar.
    """

    normalised_action = _normalise_action(action)
    commands = _PLAN_STEPS[normalised_action]
    return _build_plan_steps(commands, device_state)


def _build_plan_steps(
    commands: Iterable[tuple[DeviceName, Binary]],
    device_state: Mapping[str, object] | None,
) -> list[PlanStep]:
    """Materializa comandos em etapas ordenadas com confirmações neutras."""

    plan: list[PlanStep] = []
    for order, (device, command) in enumerate(commands, 1):
        previous_value = (
            device_state.get(device)
            if device_state is not None
            else None
        )
        previous_state = (
            cast(Binary, previous_value)
            if previous_value in (0, 1)
            else None
        )
        already_confirmed = (
            device_state is not None and device_state.get(device) == command
        )
        status: PlanStatus = "confirmado" if already_confirmed else "pendente"
        transitions: list[PlanTransition] = (
            ["confirmado"] if already_confirmed else []
        )
        plan.append(
            {
                "ordem": order,
                "comando_id": None,
                "dispositivo": device,
                "comando": command,
                "status": status,
                "transicoes": transitions,
                "estado_anterior": previous_state,
                "estado_novo": command,
            }
        )
    return plan


def _build_maintenance_plan(
    readings: SensorReadings,
    device_state: Mapping[str, object],
    *,
    mode: Mode = "reativo",
) -> list[PlanStep]:
    """Monta desligamentos de segurança, iluminação e climatização."""

    commands: list[tuple[DeviceName, Binary]] = []
    if readings["presenca_interna"] == 0:
        commands.extend((("umidificador", 0), ("lampada", 0)))
    elif not _lighting_required(readings) and device_state.get("lampada") == 1:
        commands.append(("lampada", 0))

    if (
        readings["presenca_interna"] == 1
        and readings["temperatura_interna"] <= (
            COGNITIVE_CLIMATE_OFF_C if mode == "cognitivo" else TEMP_CLIMATE_OFF_C
        )
    ):
        commands.extend(
            (device, 0)
            for device in ("ar", "ventilador")
            if device_state.get(device) == 1
        )
    return _build_plan_steps(commands, device_state)


def _build_decision_plan(
    action: ActionName | Iterable[ActionName],
    readings: SensorReadings,
    device_state: Mapping[str, object],
    *,
    objective: DecisionObjective | None = None,
    mode: Mode = "reativo",
) -> list[PlanStep]:
    """Monta o plano da decisão com as salvaguardas preventivas da política."""

    if isinstance(action, str):
        actions = (_normalise_action(action),)
    else:
        actions = tuple(_normalise_action(item) for item in action)
    if not actions:
        actions = ("manter",)
    command_by_device = dict(_preventive_commands(readings, device_state))
    for selected_action in actions:
        action_commands = _PLAN_STEPS[selected_action]
        if any(
            device in command_by_device and command_by_device[device] != command
            for device, command in action_commands
        ):
            raise ValueError("O plano contém ações incompatíveis no mesmo atuador.")
        command_by_device.update(action_commands)
    preserves_thermal_auxiliaries = objective == "termico" or any(
        selected_action in _THERMAL_STRATEGIES
        and selected_action != "manter"
        for selected_action in actions
    )
    for step in _build_maintenance_plan(readings, device_state, mode=mode):
        if (
            preserves_thermal_auxiliaries
            and readings["presenca_interna"] == 1
            and readings["dormir"] == 0
            and step["dispositivo"] == "lampada"
        ):
            continue
        command_by_device[step["dispositivo"]] = step["comando"]
    ordered_commands = list(command_by_device.items())
    window_needs_closing = device_state.get("janela") == 1 and (
        readings["chuva"] == 1
        or readings["presenca_externa"] == 1
        or device_state.get("ar") == 1
    )
    if window_needs_closing and command_by_device.get("janela") == 0:
        ordered_commands.insert(
            0, ordered_commands.pop(ordered_commands.index(("janela", 0)))
        )
    return _build_plan_steps(ordered_commands, device_state)


def _compatible_cycle_actions(
    state: RoomState,
    primary_action: ActionName,
    objective: DecisionObjective,
    mode: Mode = "reativo",
) -> list[ActionName]:
    """Escolhe por objetivo; só conflitos físicos impedem a composição."""

    actions = [primary_action]
    readings = read_sensors(state)
    devices = state["dispositivos"]
    if readings["presenca_interna"] == 0:
        return [primary_action]

    commands = dict(_PLAN_STEPS[primary_action])
    groups: list[tuple[DecisionObjective, tuple[ActionName, ...]]] = []
    if readings["umidade"] < 40:
        groups.append(("umidade", ("umidificar", "manter")))
    if readings["temperatura_interna"] > (
        COGNITIVE_COOL_ON_C if mode == "cognitivo" else TEMP_HOT_LIMIT_C
    ):
        thermal_candidates: tuple[ActionName, ...] = (
            _thermal_actions(state)
            if mode == "cognitivo"
            else ("resfriamento", "ventilacao_assistida", "manter")
        )
        groups.append(("termico", thermal_candidates))
    elif (
        readings["temperatura_interna"] < TEMP_COLD_LIMIT_C
        and _cold_action_pending(devices)
    ):
        groups.append(("termico", ("fechar", "manter")))
    if _lighting_action_pending(readings, devices):
        groups.append(("iluminacao", ("iluminar", "manter")))

    for goal, candidates in groups:
        if goal == objective:
            continue
        compatible = tuple(
            candidate for candidate in candidates
            if all(
                device not in commands or commands[device] == command
                for device, command in _PLAN_STEPS[candidate]
            )
        )
        if mode == "cognitivo":
            # A trava já é atendida pelo plano de segurança. Avaliar 'manter'
            # neste grupo significa não mudar este objetivo, não a janela.
            evaluated_state = cast(
                RoomState, {**state, "dispositivos": {**devices, **commands}}
            )
            alternatives = _evaluate_objective_alternatives(
                evaluated_state, compatible, goal
            )
            if not any(alternative["elegivel"] for alternative in alternatives):
                continue
            action = _select_cognitive_alternative(
                alternatives, evaluated_state, "pontuacao_total"
            )
            action = cast(ActionName, _alternative_strategy_id(action))
        else:
            action = candidates[0] if candidates[0] in compatible else "manter"
        if action != "manter" and action not in actions:
            actions.append(action)
            commands.update(_PLAN_STEPS[action])
    return actions


def make_decision(state: RoomState, mode: Mode | str = "reativo") -> Decision:
    """Create a decision preview for the selected policy without physics."""

    selected_mode = _normalise_mode(mode)
    readings = read_sensors(state)
    context = (
        build_learning_context(state)
        if selected_mode == "cognitivo"
        else None
    )

    if selected_mode == "reativo":
        action, objective, reason = _reactive_rule(state)
        action = _normalise_action(action)
        alternatives: list[DecisionAlternative] = [
            {
                "acao": cast(ActionName, _legacy_action(action)),
                "strategy_id": action,
                "pontuacao_base": 0.0,
                "preferencia_contextual": 0,
                "pontuacao_total": 0.0,
                "elegivel": True,
                "influenciada": False,
                "motivo_bloqueio": None,
                "correcoes_permitidas": [],
                "conforto": 0.0,
                "economia": 0.0,
                "preferencia": 0,
                "utilidade": None,
            }
        ]
    else:
        alternatives = evaluate_alternatives(state)
        winner = _select_cognitive_alternative(
            alternatives,
            state,
            "pontuacao_total",
        )
        action = cast(ActionName, _alternative_strategy_id(winner))
        _, objective = _cognitive_actions(state)
        baseline_state = cast(RoomState, {**state, "preferencias": {}})
        baseline_alternatives = evaluate_alternatives(baseline_state)
        baseline_winner = _select_cognitive_alternative(
            baseline_alternatives,
            baseline_state,
            "pontuacao_total",
        )
        influenced, influence_message = _learning_influence_message(
            state, winner, baseline_winner, alternatives, baseline_alternatives
        )
        winner["influenciada"] = influenced
        winner["motivo_influencia"] = influence_message

    actions = _compatible_cycle_actions(state, action, objective, selected_mode)
    if selected_mode == "cognitivo":
        baseline_action = cast(ActionName, _alternative_strategy_id(baseline_winner))
        baseline_actions = _compatible_cycle_actions(
            baseline_state, baseline_action, objective, "cognitivo"
        )
        if actions[1:] != baseline_actions[1:]:
            if action == baseline_action:
                secondary_message = (
                    "A preferência aprendida alterou uma ação adicional do ciclo; "
                    "a estratégia principal permaneceu a mesma."
                )
                winner["motivo_influencia"] = (
                    f"{winner['motivo_influencia']} {secondary_message}"
                    if winner["influenciada"]
                    else secondary_message
                )
            else:
                winner["motivo_influencia"] += (
                    " A composição das ações adicionais do ciclo também mudou."
                )
            winner["influenciada"] = True
        reason = _cognitive_decision_reason(objective, winner)
        if (
            objective == "termico"
            and action == "manter"
            and state["dispositivos"]["ar"] == 1
            and readings["temperatura_interna"] <= COGNITIVE_CLIMATE_OFF_C
        ):
            reason += " O plano desliga o ar-condicionado ao entrar na faixa de conforto."
    legacy_action = cast(ActionName, _legacy_action(action))
    legacy_actions = [cast(ActionName, _legacy_action(item)) for item in actions]
    decision: Decision = {
        "decisao_id": uuid4().hex,
        "identidade": (
            _learning_identity(state, context, selected_mode)
            if context is not None
            else None
        ),
        "modo": selected_mode,
        "objetivo": objective,
        "acao": legacy_action,
        "strategy_id": action,
        "acoes": legacy_actions,
        "status": "prevista",
        "motivo": reason,
        "alternativas": alternatives,
        "plano": _build_decision_plan(
            actions,
            readings,
            state["dispositivos"],
            objective=objective,
            mode=selected_mode,
        ),
        "correcoes_permitidas": (
            _allowed_corrections(action)
            if selected_mode == "cognitivo" and objective != "seguranca"
            else []
        ),
    }
    if context is not None:
        decision["contexto"] = context
    state["decisao_pendente"] = cast(dict[str, object], deepcopy(decision))
    return decision


def _request_body(
    payload: object,
    fields: tuple[str, ...],
    *,
    required_fields: tuple[str, ...] | None = None,
) -> Mapping[str, object]:
    """Valida o formato fechado de um corpo JSON de entrada."""

    if not isinstance(payload, Mapping):
        _fail(
            JSON_INVALID,
            "O corpo da requisição deve ser um objeto JSON válido.",
        )
    if any(not isinstance(key, str) for key in payload):
        _fail(
            JSON_INVALID,
            "O corpo da requisição deve conter somente chaves JSON.",
        )
    body = cast(Mapping[str, object], payload)
    allowed_fields = set(fields)
    unknown = [key for key in body if key not in allowed_fields]
    if unknown:
        _fail(
            UNKNOWN_FIELD,
            f"Campos desconhecidos: {', '.join(unknown)}.",
            unknown,
        )
    expected_fields = fields if required_fields is None else required_fields
    missing = [field for field in expected_fields if field not in body]
    if missing:
        _fail(
            MISSING_FIELD,
            f"Campos ausentes: {', '.join(missing)}.",
            missing,
        )
    return dict(body)


def _number_field(
    value: object,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    """Converte e valida um número finito dentro do intervalo permitido."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(INVALID_TYPE, f"{field} deve ser numérico.", [field])
    number = float(value)
    if not isfinite(number) or not minimum <= number <= maximum:
        _fail(
            INVALID_VALUE,
            f"{field} está fora do intervalo permitido.",
            [field],
        )
    return number


def _integer_field(
    value: object,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    """Converte e valida um inteiro no intervalo permitido."""

    if type(value) is not int:
        _fail(INVALID_TYPE, f"{field} deve ser um inteiro.", [field])
    if not minimum <= value <= maximum:
        _fail(
            INVALID_VALUE,
            f"{field} está fora do intervalo permitido.",
            [field],
        )
    return value


def _binary_field(value: object, field: str) -> Binary:
    """Valida um campo binário representado por 0 ou 1."""

    if type(value) is not int:
        _fail(INVALID_TYPE, f"{field} deve ser um inteiro.", [field])
    if value not in (0, 1):
        _fail(INVALID_VALUE, f"{field} deve ser 0 ou 1.", [field])
    return cast(Binary, value)


def _string_field(value: object, field: str) -> str:
    """Valida um identificador textual não vazio."""

    if not isinstance(value, str):
        _fail(INVALID_TYPE, f"{field} deve ser uma string.", [field])
    if not value.strip():
        _fail(INVALID_VALUE, f"{field} não pode ser vazio.", [field])
    return value


def validate_environment_request(payload: object) -> EnvironmentRequest:
    """Valida os sete campos do ajuste ambiental sem tocar no estado."""

    body = _request_body(payload, _ENVIRONMENT_FIELDS)
    internal_presence = _binary_field(
        body["presenca_interna"],
        "presenca_interna",
    )
    sleep = _binary_field(body["dormir"], "dormir")
    return {
        "hora": _integer_field(body["hora"], "hora", 0, 23),
        "temperatura_externa": _number_field(
            body["temperatura_externa"],
            "temperatura_externa",
            MIN_EXTERNAL_TEMPERATURE_C,
            MAX_EXTERNAL_TEMPERATURE_C,
        ),
        "umidade": _number_field(
            body["umidade"],
            "umidade",
            MIN_HUMIDITY_PCT,
            MAX_HUMIDITY_PCT,
        ),
        "chuva": _binary_field(body["chuva"], "chuva"),
        "presenca_interna": cast(
            Binary,
            1 if internal_presence == 1 or sleep == 1 else 0,
        ),
        "presenca_externa": _binary_field(
            body["presenca_externa"],
            "presenca_externa",
        ),
        "dormir": sleep,
    }


def validate_cycle_request(payload: object) -> CycleRequest:
    """Valida o modo do corpo fechado de ciclo sem executar a operação."""

    body = _request_body(
        {} if payload is NO_BODY else payload,
        ("modo",),
    )
    mode = body["modo"]
    if not isinstance(mode, str):
        _fail(INVALID_TYPE, "modo deve ser uma string.", ["modo"])
    if mode not in {"reativo", "cognitivo"}:
        _fail(INVALID_MODE, "O modo deve ser reativo ou cognitivo.", ["modo"])
    return {"modo": cast(Mode, mode)}


def confirm_step(state: RoomState, step: PlanStep) -> DeviceConfirmation:
    """Apply one local device command and require its physical confirmation."""

    _ensure_device_command_is_safe(
        state,
        step["dispositivo"],
        step["comando"],
    )
    confirmation = apply_device_command(
        state,
        step["dispositivo"],
        step["comando"],
    )
    if (
        confirmation["status"] != "confirmado"
        or confirmation["dispositivo"] != step["dispositivo"]
        or confirmation["comando"] != step["comando"]
        or state["dispositivos"][step["dispositivo"]] != step["comando"]
    ):
        raise RuntimeError("A local device did not confirm the requested step.")
    return confirmation


def _restore_state(state: RoomState, snapshot: RoomState) -> None:
    """Restore a mutable room state in place after a failed operation."""

    state_dict = cast(dict[str, object], state)
    state_dict.clear()
    state_dict.update(cast(dict[str, object], deepcopy(snapshot)))


def execute_plan(
    state: RoomState,
    plan: Iterable[PlanStep],
    *,
    on_step: Callable[[PlanStep], None] | None = None,
) -> list[PlanStep]:
    """Execute an ordered plan, confirming each step before the next one."""

    snapshot = deepcopy(state)
    executed_steps: list[PlanStep] = []
    current_step: PlanStep | None = None
    try:
        for order, original_step in enumerate(plan, start=1):
            source = cast(PlanStep, deepcopy(original_step))
            command_id = source["comando_id"]
            already_confirmed = source["status"] == "confirmado"
            executing: PlanStep = {
                "ordem": order,
                "comando_id": command_id,
                "dispositivo": source["dispositivo"],
                "comando": source["comando"],
                "status": "confirmado" if already_confirmed else "pendente",
                "transicoes": ["confirmado"] if already_confirmed else ["executando"],
                "estado_anterior": source.get("estado_anterior"),
                "estado_novo": source.get("estado_novo", source["comando"]),
            }
            current_step = executing
            if on_step is not None and not already_confirmed:
                on_step(deepcopy(executing))

            confirmation = confirm_step(state, executing)
            if (
                confirmation["status"] != "confirmado"
                or confirmation["dispositivo"] != executing["dispositivo"]
                or confirmation["comando"] != executing["comando"]
            ):
                raise RuntimeError(
                    "A local device confirmation did not match the step."
                )

            confirmed_command_id = command_id or f"comando-{uuid4().hex}"
            confirmed: PlanStep = {
                **executing,
                "comando_id": confirmed_command_id,
                "status": "confirmado",
                "transicoes": (
                    ["confirmado"]
                    if already_confirmed
                    else ["executando", "confirmado"]
                ),
            }
            executed_steps.append(confirmed)
            if on_step is not None:
                on_step(deepcopy(confirmed))
    except ContractValidationError:
        _restore_state(state, snapshot)
        raise
    except Exception:
        _restore_state(state, snapshot)
        if current_step is None:
            raise
        failed_step: PlanStep = {
            **current_step,
            "status": "falhou",
            "transicoes": [*current_step["transicoes"], "falhou"],
        }
        raise PlanExecutionError(
            "A execução do plano falhou antes da confirmação completa.",
            [*executed_steps, failed_step],
        ) from None

    state["etapas"] = cast(
        list[dict[str, object]],
        deepcopy(executed_steps),
    )
    return executed_steps


def _manual_plan(
    state: RoomState,
    device: DeviceName,
    command: Binary,
) -> list[PlanStep]:
    """Build the ordered binary plan for one manual actuator command."""

    commands: tuple[tuple[DeviceName, Binary], ...]
    if device == "ar" and command == 1:
        ordered_commands: list[tuple[DeviceName, Binary]] = []
        if state["dispositivos"]["janela"] == 1:
            ordered_commands.append(("janela", 0))
        if state["dispositivos"]["ventilador"] == 1:
            ordered_commands.append(("ventilador", 0))
        ordered_commands.append(("ar", 1))
        commands = tuple(ordered_commands)
    else:
        commands = ((device, command),)
    return _build_plan_steps(commands, state["dispositivos"])


def _validate_manual_correction(
    state: RoomState,
    device: DeviceName,
    command: Binary,
    decision_id: str,
) -> Mapping[str, object]:
    """Validate a correlated manual intent before reaching an actuator."""

    _ensure_preset_selected(state)
    decision = _resolve_decision(state, decision_id)
    requested_correction: Mapping[str, object] = {
        "dispositivo": device,
        "comando": command,
    }
    if not correction_is_eligible(
        state,
        decision,
        requested_correction,
    ):
        _fail(
            CORRECTION_INCOMPATIBLE,
            "O comando não é compatível com a decisão informada.",
            ["dispositivo", "comando"],
        )
    return decision


def execute_manual(
    state: RoomState,
    device: DeviceName,
    command: Binary,
    *,
    decision_id: str | None = None,
) -> list[PlanStep]:
    """Execute one manual command through the local confirmation executor."""

    if decision_id is not None:
        _validate_manual_correction(state, device, command, decision_id)
    _ensure_window_opening_is_safe(state, device, command)

    previous_devices = cast(Mapping[str, object], deepcopy(state["dispositivos"]))
    executed_steps = execute_plan(
        state,
        _manual_plan(state, device, command),
    )
    _refresh_luminosity(state)
    _replace_confirmed_command_registry(
        state,
        executed_steps,
        decision_id,
        previous_devices=previous_devices,
    )
    if decision_id is not None:
        command_id = next(
            (
                step["comando_id"]
                for step in executed_steps
                if step["comando_id"] is not None
            ),
            None,
        )
        append_trace_event(
            state,
            "correcao",
            decisao_id=decision_id,
            comando_id=command_id,
            dados={
                "dispositivo": device,
                "comando": command,
                "etapas": executed_steps,
            },
        )
    return executed_steps


def _empty_run_summary(run_id: str) -> RunSummary:
    return {
        "run_id": run_id,
        "ciclos": 0,
        "custo_energetico_total": 0.0,
        "custo_energetico_medio": None,
        "conforto_acumulado": 0.0,
        "conforto_medio": None,
        "ciclos_seguros": 0,
        "prevencoes": 0,
        "incidentes": 0,
        "aceitacoes": 0,
        "correcoes": 0,
        "feedbacks_observados": 0,
        "satisfacao_acumulada": 0.0,
        "satisfacao_observada": None,
    }


def _update_run_summary_for_cycle(state: RoomState, metric: CycleMetrics) -> None:
    summary = deepcopy(state["resumo"])
    if summary["run_id"] != metric["run_id"]:
        summary = _empty_run_summary(metric["run_id"])
    cycle_count = summary["ciclos"] + 1
    energy_total = summary["custo_energetico_total"] + metric["custo_energetico"]
    comfort_total = summary["conforto_acumulado"] + metric["conforto"]
    feedback = metric["feedback"]
    if feedback is not None:
        summary["feedbacks_observados"] += 1
        summary["satisfacao_acumulada"] += 1.0 if feedback == "aceitar" else 0.0
        summary["aceitacoes"] += feedback == "aceitar"
        summary["correcoes"] += feedback == "corrigir"
    feedback_count = summary["feedbacks_observados"]
    state["resumo"] = {
        **summary,
        "ciclos": cycle_count,
        "custo_energetico_total": energy_total,
        "custo_energetico_medio": round(energy_total / cycle_count, 2),
        "conforto_acumulado": comfort_total,
        "conforto_medio": round(comfort_total / cycle_count, 2),
        "ciclos_seguros": summary["ciclos_seguros"] + (metric["seguranca"] == "seguro"),
        "prevencoes": summary["prevencoes"] + (metric["seguranca"] == "prevencao"),
        "incidentes": summary["incidentes"] + len(metric["incidentes"]),
        "satisfacao_observada": (
            round(summary["satisfacao_acumulada"] / feedback_count, 2)
            if feedback_count
            else None
        ),
    }


def _update_run_summary_for_feedback(
    state: RoomState,
    feedback_type: FeedbackType,
) -> None:
    summary = deepcopy(state["resumo"])
    feedback_count = summary["feedbacks_observados"] + 1
    satisfaction_total = summary["satisfacao_acumulada"] + (
        1.0 if feedback_type == "aceitar" else 0.0
    )
    state["resumo"] = {
        **summary,
        "aceitacoes": summary["aceitacoes"] + (feedback_type == "aceitar"),
        "correcoes": summary["correcoes"] + (feedback_type == "corrigir"),
        "feedbacks_observados": feedback_count,
        "satisfacao_acumulada": satisfaction_total,
        "satisfacao_observada": round(satisfaction_total / feedback_count, 2),
    }


def _refresh_run_summary(state: RoomState) -> None:
    metrics = [
        metric for metric in state["metricas"]
        if metric["run_id"] == state["run_id"]
    ]
    feedback_scores = [
        1.0 if metric["feedback"] == "aceitar" else 0.0
        for metric in metrics
        if metric["feedback"] is not None
    ]
    cycle_count = len(metrics)
    energy_total = float(sum(metric["custo_energetico"] for metric in metrics))
    comfort_total = sum(metric["conforto"] for metric in metrics)
    satisfaction_total = sum(feedback_scores)
    state["resumo"] = {
        "run_id": state["run_id"],
        "ciclos": cycle_count,
        "custo_energetico_total": energy_total,
        "custo_energetico_medio": (
            round(energy_total / cycle_count, 2) if cycle_count else None
        ),
        "conforto_acumulado": comfort_total,
        "conforto_medio": (
            round(comfort_total / cycle_count, 2) if cycle_count else None
        ),
        "ciclos_seguros": sum(
            metric["seguranca"] == "seguro" for metric in metrics
        ),
        "prevencoes": sum(
            metric["seguranca"] == "prevencao" for metric in metrics
        ),
        "incidentes": sum(len(metric["incidentes"]) for metric in metrics),
        "aceitacoes": sum(metric["feedback"] == "aceitar" for metric in metrics),
        "correcoes": sum(metric["feedback"] == "corrigir" for metric in metrics),
        "feedbacks_observados": len(feedback_scores),
        "satisfacao_acumulada": satisfaction_total,
        "satisfacao_observada": (
            round(satisfaction_total / len(feedback_scores), 2)
            if feedback_scores
            else None
        ),
    }


def _cycle_incidents(state: RoomState) -> list[str]:
    devices = state["dispositivos"]
    incidents: list[str] = []
    if devices["janela"] == 1 and state["chuva"] == 1:
        incidents.append("janela_aberta_com_chuva")
    if devices["janela"] == 1 and state["presenca_externa"] == 1:
        incidents.append("janela_aberta_com_presenca_externa")
    if devices["janela"] == 1 and devices["ar"] == 1:
        incidents.append("intertravamento_janela_ar")
    return incidents


def _materialize_cycle_metrics(
    state: RoomState,
    decision: Mapping[str, object],
    previous_state: RoomState,
) -> CycleMetrics:
    strategy_value = decision.get("strategy_id")
    if not isinstance(strategy_value, str):
        raise RuntimeError("Confirmed decision has no strategy identifier.")
    action_strategy_id = _normalise_action(strategy_value)
    strategy_id = cast(StrategyId, _strategy_id(strategy_value))
    alternatives_value = decision.get("alternativas")
    alternatives = (
        cast(list[Mapping[str, object]], alternatives_value)
        if isinstance(alternatives_value, list)
        else []
    )
    selected_alternative = next(
        (
            alternative
            for alternative in alternatives
            if (
                isinstance(alternative.get("strategy_id"), str)
                and _normalise_action(cast(str, alternative["strategy_id"]))
                == action_strategy_id
            )
        ),
        None,
    )
    adjustment_value = (
        selected_alternative.get("preferencia")
        if selected_alternative is not None
        else 0.0
    )
    preference_adjustment = (
        float(adjustment_value)
        if isinstance(adjustment_value, (int, float))
        and not isinstance(adjustment_value, bool)
        else 0.0
    )
    blocked_reasons: list[str] = []
    for alternative in alternatives:
        reason = alternative.get("motivo_bloqueio")
        if isinstance(reason, str) and reason not in blocked_reasons:
            blocked_reasons.append(reason)

    incidents = _cycle_incidents(state)
    previous_devices = previous_state["dispositivos"]
    was_unsafe = (
        previous_devices["janela"] == 1
        and (
            previous_state["chuva"] == 1
            or previous_state["presenca_externa"] == 1
            or previous_devices["ar"] == 1
        )
    )
    decision_prevented = decision.get("objetivo") == "seguranca"
    prevented = bool(blocked_reasons) or decision_prevented or (
        was_unsafe and not incidents
    )
    security: Literal["seguro", "prevencao", "incidente"]
    if incidents:
        security = "incidente"
    elif prevented:
        security = "prevencao"
    else:
        security = "seguro"

    cost = calculate_cost(state["dispositivos"])
    temperature = state["temperatura_interna"]
    cycle_number = state["resumo"]["ciclos"] + 1
    metric: CycleMetrics = {
        "cycle_id": uuid5(
            NAMESPACE_URL,
            f"peas-cycle:{state['run_id']}:{cycle_number}",
        ).hex,
        "run_id": state["run_id"],
        "numero_ciclo": cycle_number,
        "temperatura_projetada": temperature,
        "conforto": calculate_comfort(temperature),
        "custo_energetico": float(cost),
        "economia": calculate_economy(cost),
        "ajuste_preferencia": preference_adjustment,
        "strategy_id": strategy_id,
        "seguranca": security,
        "bloqueios": blocked_reasons,
        "incidentes": incidents,
        "feedback": None,
    }
    return metric


def record_observed_feedback(
    state: RoomState,
    decision_id: str,
    feedback_type: FeedbackType,
) -> None:
    if not state["metricas"]:
        return
    metric = state["metricas"][-1]
    current_decision = state["decisao"]
    if (
        metric["run_id"] != state["run_id"]
        or not isinstance(current_decision, Mapping)
        or _decision_id(current_decision) != decision_id
        or metric["feedback"] is not None
    ):
        return
    metric["feedback"] = feedback_type
    _update_run_summary_for_feedback(state, feedback_type)


def run_cycle(
    request: CycleRequest | Mapping[str, object] | str | None = None,
    *,
    mode: Mode | None = None,
    state: RoomState | None = None,
) -> dict[str, object]:
    """Run one serial cycle from observation through one hour of physics."""

    selected_state = estado_quarto if state is None else state
    if mode is not None:
        cycle_request = validate_cycle_request({"modo": mode})
    elif request is None:
        cycle_request = validate_cycle_request({})
    elif isinstance(request, str):
        cycle_request = validate_cycle_request({"modo": request})
    else:
        cycle_request = validate_cycle_request(request)

    snapshot = deepcopy(selected_state)
    try:
        _ensure_preset_selected(selected_state)
        decision = make_decision(selected_state, cycle_request["modo"])
        executed_steps = execute_plan(selected_state, decision["plano"])
        devices = selected_state["dispositivos"]
        selected_state["temperatura_interna"] = advance_physics(
            selected_state["temperatura_interna"],
            selected_state["temperatura_externa"],
            devices["janela"] == 1,
            devices["ventilador"] == 1,
            devices["ar"] == 1,
        )
        selected_state["umidade"] = advance_humidity(
            selected_state["umidade"],
            devices["janela"] == 1,
            devices["umidificador"] == 1,
        )
        selected_state["hora"] = (selected_state["hora"] + 1) % 24
        _refresh_luminosity(selected_state)
        _ = read_sensors(selected_state)

        decision["plano"] = deepcopy(executed_steps)
        decision["status"] = "confirmada"
        selected_state["modo"] = cycle_request["modo"]
        selected_state["ultima_acao_confirmada"] = next(
            (
                action for action in decision["acoes"]
                if action in {"ventilar", "resfriar", "fechar"}
            ),
            decision["acao"],
        )
        selected_state["decisao"] = cast(
            dict[str, object],
            deepcopy(decision),
        )
        selected_state["etapas"] = cast(
            list[dict[str, object]],
            deepcopy(executed_steps),
        )
        selected_state["decisao_pendente"] = None
        _clear_confirmed_command_registry(selected_state)
        metric = _materialize_cycle_metrics(selected_state, decision, snapshot)
        selected_state["metricas"].append(metric)
        _update_run_summary_for_cycle(selected_state, metric)
        append_trace_event(
            selected_state,
            "ciclo",
            decisao_id=decision["decisao_id"],
            dados={
                "modo": cycle_request["modo"],
                "acao": decision["acao"],
                "acoes": decision["acoes"],
                "status": decision["status"],
            },
        )
    except Exception:
        _restore_state(selected_state, snapshot)
        raise

    return {
        "status": "sucesso",
        "mensagem": "Ciclo concluído com todas as etapas confirmadas.",
        "estado": public_state(selected_state),
        "decisao": deepcopy(decision),
        "etapas": deepcopy(executed_steps),
    }


def validate_preset_request(payload: object) -> PresetRequest:
    """Valida o nome de preset antes de qualquer substituição de ambiente."""

    body = _request_body(payload, ("preset",))
    preset = body["preset"]
    if not isinstance(preset, str):
        _fail(INVALID_TYPE, "preset deve ser uma string.", ["preset"])
    if preset not in _PRESET_NAMES:
        _fail(
            INVALID_PRESET,
            "O preset deve ser calor, frio ou conforto.",
            ["preset"],
        )
    return {"preset": cast(PresetName, preset)}


def validate_reset_request(payload: object = NO_BODY) -> ResetRequest:
    """Valida que o reset receba somente um objeto JSON vazio."""

    _request_body(payload, ())
    return {}


def validate_trace_query_request(payload: object) -> TraceQueryRequest:
    body = _request_body(payload, ("run_id", "cursor", "limit"))
    run_id = _string_field(body["run_id"], "run_id")
    if len(run_id) > 128:
        _fail(INVALID_VALUE, "run_id excede o limite permitido.", ["run_id"])
    cursor_value = body["cursor"]
    cursor = (
        None
        if cursor_value is None
        else _integer_field(cursor_value, "cursor", 0, 2**53 - 1)
    )
    limit = _integer_field(body["limit"], "limit", 1, MAX_TRACE_PAGE_LIMIT)
    return {"run_id": run_id, "cursor": cursor, "limit": limit}


def prune_trace(state: RoomState, through_order: int) -> int:
    if type(through_order) is not int or through_order < 0:
        _fail(INVALID_VALUE, "through_order deve ser um inteiro não negativo.", ["through_order"])
    validate_trace(state)
    old_watermark = state["pruned_before"]
    removed = [
        event for event in state["rastro"]
        if event["ordem"] <= through_order
    ]
    if not removed:
        return old_watermark
    state["rastro"] = [
        event for event in state["rastro"]
        if event["ordem"] > through_order
    ]
    state["pruned_before"] = max(old_watermark, removed[-1]["ordem"])
    validate_trace(state)
    return state["pruned_before"]


def query_trace(
    payload: object,
    *,
    state: RoomState = estado_quarto,
) -> dict[str, object]:
    query = validate_trace_query_request(payload)
    validate_trace(state)
    if query["run_id"] != state["run_id"]:
        _fail(RUN_NOT_FOUND, "A execução solicitada não existe.", ["run_id"])

    watermark = state["pruned_before"]
    cursor = query["cursor"]
    if cursor is not None and cursor <= watermark:
        _fail(
            TRACE_CURSOR_PRUNED,
            "O cursor solicitado já foi removido pela retenção do rastro.",
            ["cursor"],
        )
    first_order = watermark + 1 if cursor is None else cursor
    remaining = [
        event for event in state["rastro"]
        if event["ordem"] >= first_order
    ]
    limit = query["limit"]
    page = remaining[:limit]
    next_cursor = remaining[limit]["ordem"] if len(remaining) > limit else None
    return {
        "status": "sucesso",
        "run_id": state["run_id"],
        "events": deepcopy(page),
        "next_cursor": next_cursor,
        "pruned_before": watermark,
    }


def validate_manual_request(payload: object) -> ManualRequest:
    """Valida o corpo opcional de correlação de um comando manual."""

    body = _request_body(
        payload,
        ("decisao_id",),
        required_fields=(),
    )
    if "decisao_id" not in body:
        return {}
    return {"decisao_id": _string_field(body["decisao_id"], "decisao_id")}


def cancel_manual_correction(payload: object) -> dict[str, object]:
    """Cancel a manual correction before dispatching any actuator command."""

    _request_body({} if payload is NO_BODY else payload, ())
    response = pegar_status()
    response["mensagem"] = "Correção cancelada."
    return response


def validate_feedback_request(payload: object) -> FeedbackRequest:
    """Valida as variantes discriminadas de feedback em snake_case."""

    body = _request_body(
        payload,
        ("decisao_id", "tipo", "comando_id"),
        required_fields=("decisao_id", "tipo"),
    )
    decision_id = _string_field(body["decisao_id"], "decisao_id")
    feedback_type = body["tipo"]
    if not isinstance(feedback_type, str):
        _fail(INVALID_TYPE, "tipo deve ser uma string.", ["tipo"])
    if feedback_type not in {"aceitar", "rejeitar", "corrigir"}:
        _fail(INVALID_TYPE, "tipo de feedback inválido.", ["tipo"])

    if feedback_type == "corrigir":
        if "comando_id" not in body:
            _fail(
                MISSING_FIELD,
                "Campos ausentes: comando_id.",
                ["comando_id"],
            )
        command_id = _string_field(body["comando_id"], "comando_id")
        return {
            "decisao_id": decision_id,
            "tipo": "corrigir",
            "comando_id": command_id,
        }

    if "comando_id" in body:
        _fail(
            UNKNOWN_FIELD,
            "comando_id só é aceito para o feedback corrigir.",
            ["comando_id"],
        )
    if feedback_type == "aceitar":
        return {"decisao_id": decision_id, "tipo": "aceitar"}
    return {"decisao_id": decision_id, "tipo": "rejeitar"}


def public_state(state: RoomState = estado_quarto) -> PublicRoomState:
    """Serializa somente o estado autoritativo permitido pela API."""

    devices = cast(PresetDevices, deepcopy(state["dispositivos"]))
    return {
        "preset_atual": state["preset_atual"],
        "hora": state["hora"],
        "temperatura_externa": state["temperatura_externa"],
        "temperatura_interna": state["temperatura_interna"],
        "umidade": state["umidade"],
        "luminosidade": state["luminosidade"],
        "chuva": state["chuva"],
        "presenca_interna": state["presenca_interna"],
        "presenca_externa": state["presenca_externa"],
        "dormir": state["dormir"],
        "modo": state["modo"],
        "dispositivos": devices,
    }


def serialize_decision(decision: Mapping[str, object]) -> Decision:
    """Cria uma cópia JSON-safe da decisão sem expor referências mutáveis."""

    return cast(Decision, deepcopy(dict(decision)))


def serialize_learning_result(
    result: Mapping[str, object],
) -> FeedbackResult | LearningResult:
    """Cria uma cópia JSON-safe do resultado de aprendizagem."""

    serialized = deepcopy(dict(result))
    if "decisao_id" in serialized:
        return cast(FeedbackResult, serialized)
    return cast(LearningResult, serialized)


def error_response(
    code: ErrorCode,
    message: str,
    fields: Iterable[str] | None = None,
) -> ErrorResponse:
    """Cria o envelope de erro com o último estado confirmado."""

    if code not in ERROR_CODES:
        raise ValueError("Código de erro não pertence ao contrato público.")
    public_message = (
        "Falha interna ao processar a requisição. Tente novamente."
        if code == INTERNAL_ERROR
        else message
    )
    return {
        "status": "erro",
        "codigo": code,
        "mensagem": public_message,
        "campos": [] if code == INTERNAL_ERROR else list(fields or []),
        "estado": public_state(),
    }


def pegar_status() -> dict[str, object]:
    """Retorna o envelope base com uma cópia do estado autoritativo."""

    return {
        "status": "sucesso",
        "mensagem": "Estado autoritativo do quarto.",
        "estado": public_state(),
    }


def status_geral() -> dict[str, object]:
    """Retorna os parâmetros gerais compatíveis com a interface histórica."""

    return {
        "modo_dormir": estado_quarto["dormir"],
        "temp_limite": TEMP_LIMIT_C,
    }


def _refresh_luminosity(state: RoomState) -> None:
    """Mantém a luminosidade derivada dos parâmetros ambientais atuais."""

    state["luminosidade"] = calculate_luminosity(
        state["hora"],
        state["dispositivos"]["janela"] == 1,
        state["chuva"] == 1,
    )


def _apply_environment_values(
    state: RoomState,
    environment: EnvironmentRequest,
) -> None:
    """Aplica os valores ambientais validados e atualiza a luminosidade."""

    state["hora"] = environment["hora"]
    state["temperatura_externa"] = environment["temperatura_externa"]
    state["umidade"] = environment["umidade"]
    state["chuva"] = environment["chuva"]
    state["presenca_interna"] = environment["presenca_interna"]
    state["presenca_externa"] = environment["presenca_externa"]
    state["dormir"] = environment["dormir"]
    _refresh_luminosity(state)


def _environment_changes_decision_identity(
    decision: Mapping[str, object] | None,
    state: RoomState,
) -> bool:
    """Indica se o ambiente candidato diverge da identidade congelada."""

    if decision is None or not _decision_status_is_confirmed(decision):
        return False
    identity = decision.get("identidade")
    if not isinstance(identity, Mapping):
        return False

    context = build_learning_context(state)
    return (
        identity.get("faixa_horario") != context["faixa_horario"]
        or identity.get("dormir") != context["dormir"]
        or identity.get("faixa_temperatura")
        != context["faixa_temperatura"]
        or identity.get("luminosidade") != context["luminosidade"]
        or identity.get("presenca_interna") != context["presenca_interna"]
    )


def _clear_invalidated_decision_controls(state: RoomState) -> None:
    """Remove comandos e feedback visíveis associados à decisão obsoleta."""

    state["etapas"] = []
    state["feedbacks"] = []
    _clear_confirmed_command_registry(state)


def _preview_decision(state: RoomState = estado_quarto) -> Decision:
    """Calcula uma prévia sem publicar decisão ou alterar o estado recebido."""

    preview_state = deepcopy(state)
    return make_decision(preview_state)


def apply_environment_request(payload: object) -> dict[str, object]:
    """Aplica um ajuste ambiental e retorna sua decisão prevista."""

    environment = validate_environment_request(payload)
    candidate_state = deepcopy(estado_quarto)
    _apply_environment_values(candidate_state, environment)
    confirmed_decision = estado_quarto["decisao"]
    decision_identity_changed = _environment_changes_decision_identity(
        cast(Mapping[str, object] | None, confirmed_decision),
        candidate_state,
    )
    changed = (
        estado_quarto["hora"] != environment["hora"]
        or estado_quarto["temperatura_externa"]
        != environment["temperatura_externa"]
        or estado_quarto["umidade"] != environment["umidade"]
        or estado_quarto["chuva"] != environment["chuva"]
        or estado_quarto["presenca_interna"] != environment["presenca_interna"]
        or estado_quarto["presenca_externa"] != environment["presenca_externa"]
        or estado_quarto["dormir"] != environment["dormir"]
    )
    if changed:
        _apply_environment_values(estado_quarto, environment)
        if decision_identity_changed:
            invalidate_decision(
                estado_quarto,
                motivo="ajuste ambiental alterou a identidade da decisão",
            )
            _clear_invalidated_decision_controls(estado_quarto)

    response = pegar_status()
    if (
        isinstance(confirmed_decision, Mapping)
        and _decision_status_is_confirmed(confirmed_decision)
        and not decision_identity_changed
    ):
        response["decisao"] = deepcopy(dict(confirmed_decision))
    else:
        response["decisao"] = _preview_decision()
    return response


def _query_number(
    value: str | None,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    """Converte um número recebido pela rota histórica de ajuste."""

    if value is None:
        _fail(MISSING_FIELD, f"O parâmetro {field} é obrigatório.", [field])
    try:
        number = float(value)
    except ValueError as error:
        _fail(INVALID_TYPE, f"{field} deve ser numérico.", [field])
    if not isfinite(number) or not minimum <= number <= maximum:
        _fail(
            INVALID_VALUE,
            f"{field} está fora do intervalo permitido.",
            [field],
        )
    return number


def _query_binary(value: str | None, field: str) -> Binary:
    """Converte um parâmetro histórico binário sem aceitar outros valores."""

    if value is None:
        _fail(MISSING_FIELD, f"O parâmetro {field} é obrigatório.", [field])
    if value not in {"0", "1"}:
        _fail(INVALID_VALUE, f"{field} deve ser 0 ou 1.", [field])
    return cast(Binary, int(value))


_LEGACY_IDENTITY_ID: Final[str] = "legacy-room"
_PROTOCOL_STRATEGIES: Final[frozenset[str]] = frozenset(
    {
        "manter",
        "ventilacao_natural",
        "ventilacao_assistida",
        "circulacao_interna",
        "resfriamento",
        "resfriamento_assistido",
        "umidificacao",
        "iluminacao",
    }
)


def _legacy_protocol_id(value: object) -> str:
    if isinstance(value, str):
        try:
            return protocol.validate_payload_hash(value)
        except protocol.ProtocolValidationError:
            return sha256(value.encode("utf-8")).hexdigest()
    return sha256(protocol.canonical_json_bytes(value)).hexdigest()


def _legacy_protocol_decision(
    value: Mapping[str, object] | None,
) -> protocol.DecisionSnapshot | None:
    if value is None:
        return None
    raw_strategy = value.get("strategy_id")
    if isinstance(raw_strategy, str) and raw_strategy in _PROTOCOL_STRATEGIES:
        strategy = raw_strategy
    else:
        action = value.get("acao", "manter")
        if not isinstance(action, str):
            raise ValueError("Legacy decision action must be a string.")
        strategy = _strategy_id(action)
    if strategy not in _PROTOCOL_STRATEGIES:
        raise ValueError("Legacy decision has an unsupported strategy.")
    objective = value.get("objetivo", "manutencao")
    mode = value.get("modo", "reativo")
    status = value.get("status", "confirmada")
    if objective not in {"seguranca", "umidade", "termico", "iluminacao", "manutencao"}:
        raise ValueError("Legacy decision has an unsupported objective.")
    if mode not in {"reativo", "cognitivo"}:
        raise ValueError("Legacy decision has an unsupported mode.")
    if status not in {"prevista", "confirmada", "invalidada"}:
        raise ValueError("Legacy decision has an unsupported status.")
    alternatives = value.get("alternativas", [])
    plan = value.get("plano", [])
    if not isinstance(alternatives, list) or not isinstance(plan, list):
        raise ValueError("Legacy decision alternatives and plan must be lists.")
    decision: dict[str, object] = {
        "decisao_id": _legacy_protocol_id(value.get("decisao_id")),
        "objetivo": cast(protocol.Objective, objective),
        "strategy_id": cast(protocol.StrategyId, strategy),
        "modo": cast(protocol.Mode, mode),
        "status": cast(Literal["prevista", "confirmada", "invalidada"], status),
        "influenciada": value.get("influenciada") is True,
        "alternativas": cast(list[dict[str, object]], deepcopy(alternatives)),
        "plano": cast(list[dict[str, object]], deepcopy(plan)),
    }
    context = value.get("contexto")
    if isinstance(context, Mapping):
        decision["contexto"] = deepcopy(dict(context))
    corrections = value.get("correcoes_permitidas")
    if not isinstance(corrections, list):
        selected = next(
            (
                alternative
                for alternative in alternatives
                if isinstance(alternative, Mapping)
                and alternative.get("strategy_id") == strategy
            ),
            None,
        )
        corrections = (
            selected.get("correcoes_permitidas")
            if isinstance(selected, Mapping)
            else None
        )
    if isinstance(corrections, list):
        decision["correcoes_permitidas"] = deepcopy(corrections)
    return cast(protocol.DecisionSnapshot, decision)


def _legacy_protocol_preferences(
    state: RoomState,
) -> list[protocol.PreferenceRecord]:
    revision = state["revisao_estado"]
    context = cast(
        dict[str, str | int | float | bool],
        dict(build_learning_context(state)),
    )
    records: list[protocol.PreferenceRecord] = []
    for key, value in state["preferencias"].items():
        if isinstance(key, str):
            preference_key = json.loads(key)
        else:
            preference_key = key
        if (
            not isinstance(preference_key, (tuple, list))
            or len(preference_key) != 2
            or not isinstance(preference_key[0], str)
            or not isinstance(preference_key[1], str)
        ):
            raise ValueError("Legacy preference key is invalid.")
        objective, raw_strategy = preference_key
        strategy = _strategy_id(raw_strategy)
        if objective not in {
            "seguranca",
            "umidade",
            "termico",
            "iluminacao",
            "manutencao",
        }:
            raise ValueError("Legacy preference objective is unsupported.")
        if strategy not in _PROTOCOL_STRATEGIES:
            raise ValueError("Legacy preference strategy is unsupported.")
        if type(value) is not int or not -3 <= value <= 3:
            raise ValueError("Legacy preference value must be between -3 and 3.")
        records.append(
            {
                "objetivo": cast(protocol.Objective, objective),
                "strategy_id": cast(protocol.StrategyId, strategy),
                "valor": cast(protocol.PreferenceValue, value),
                "updated_revision": revision,
                "contexto_explicativo": context,
            }
        )
    return records


def _legacy_protocol_computation(
    state: RoomState,
) -> protocol.ComputationState:
    physical_fields = (
        "preset_atual",
        "hora",
        "temperatura_externa",
        "temperatura_interna",
        "umidade",
        "luminosidade",
        "chuva",
        "presenca_interna",
        "presenca_externa",
        "dormir",
    )
    decision = _legacy_protocol_decision(
        cast(Mapping[str, object] | None, state["decisao"])
    )
    episode = deepcopy(state["episodio_aberto"])
    if episode is not None:
        episode["episode_id"] = _legacy_protocol_id(episode["episode_id"])
        episode["decisao_id"] = _legacy_protocol_id(episode["decisao_id"])
    computation: dict[str, object] = {
        "revision": state["revisao_estado"],
        "fisico": {field: deepcopy(state[field]) for field in physical_fields},
        "dispositivos": deepcopy(state["dispositivos"]),
        "preferencias": _legacy_protocol_preferences(state),
        "decisao": decision,
        "episodio_aberto": episode,
        "execucao": deepcopy(state["execucao_automatica"]),
        "metricas": deepcopy(state["metricas"]),
        "resumo": deepcopy(state["resumo"]),
    }
    return cast(protocol.ComputationState, computation)


def _legacy_operation_id(
    route: str,
    operation: str,
    payload: Mapping[str, object],
    raw_input: object,
    computation: protocol.ComputationState,
) -> str:
    value = {
        "route": route,
        "operation": operation,
        "payload": payload,
        "raw_input": raw_input,
        "computation": computation,
    }
    return sha256(protocol.canonical_json_bytes(value)).hexdigest()


def run_legacy_transition(
    route: str,
    operation: protocol.MutationOperationKind,
    payload: Mapping[str, object],
    *,
    raw_input: object,
    state: RoomState | None = None,
) -> dict[str, object]:
    selected_state = estado_quarto if state is None else state
    computation = _legacy_protocol_computation(selected_state)
    operation_payload = cast(dict[str, object], deepcopy(dict(payload)))
    if operation == "manual_command":
        decision_id = operation_payload.get("decisao_id")
        existing_decision = selected_state["decisao"]
        if (
            isinstance(decision_id, str)
            and isinstance(existing_decision, Mapping)
            and decision_id == existing_decision.get("decisao_id")
        ):
            operation_payload["decisao_id"] = _legacy_protocol_id(decision_id)
    operation_id = _legacy_operation_id(
        route,
        operation,
        operation_payload,
        raw_input,
        computation,
    )
    request_body: protocol.TransitionRequest = {
        "schema_version": 1,
        "identity_id": _LEGACY_IDENTITY_ID,
        "identity_generation": 0,
        "base_revision": computation["revision"],
        "operation_id": operation_id,
        "payload_hash": "0" * 64,
        "operation": operation,
        "computation": computation,
        "payload": cast(
            protocol.CompactPayload,
            {"kind": operation, **operation_payload},
        ),
    }
    request_body["payload_hash"] = protocol.compute_payload_hash(request_body)
    import transition

    envelope = transition.run_transition(
        request_body,
        expected_identity={
            "identity_id": _LEGACY_IDENTITY_ID,
            "identity_generation": 0,
        },
    )
    return {
        "envelope": cast(dict[str, object], envelope),
        "operation_id": operation_id,
        "payload_hash": request_body["payload_hash"],
        "base_revision": computation["revision"],
        "source_state": deepcopy(selected_state),
    }


def _legacy_public_state(
    computation: protocol.ComputationState,
    source_state: RoomState,
) -> PublicRoomState:
    physical = cast(dict[str, object], deepcopy(computation["fisico"]))
    decision = computation["decisao"]
    mode = source_state["modo"] if decision is None else decision["modo"]
    return cast(
        PublicRoomState,
        {
            **physical,
            "modo": mode,
            "dispositivos": deepcopy(computation["dispositivos"]),
        },
    )


def _legacy_public_decision(
    computation: protocol.ComputationState,
    source_state: RoomState,
) -> dict[str, object] | None:
    decision = computation["decisao"]
    if decision is None:
        return None
    original = source_state["decisao"]
    base = deepcopy(original) if isinstance(original, Mapping) else {}
    action = _legacy_action(decision["strategy_id"])
    base.update(
        {
            "decisao_id": decision["decisao_id"],
            "objetivo": decision["objetivo"],
            "strategy_id": decision["strategy_id"],
            "modo": decision["modo"],
            "status": decision["status"],
            "acao": action,
            "acoes": [action],
            "influenciada": decision["influenciada"],
            "alternativas": deepcopy(decision["alternativas"]),
            "plano": deepcopy(decision["plano"]),
        }
    )
    return base


def legacy_response(
    result: Mapping[str, object],
    *,
    message: str,
    decision: Mapping[str, object] | None = None,
) -> dict[str, object]:
    envelope = cast(Mapping[str, object], result["envelope"])
    source_state = cast(RoomState, result["source_state"])
    successful = envelope.get("status") == "success"
    computation = (
        cast(protocol.ComputationState, envelope["computation"])
        if successful
        else _legacy_protocol_computation(source_state)
    )
    events = envelope.get("events", [])
    steps: list[object] = []
    if isinstance(events, list) and events and isinstance(events[-1], Mapping):
        event_data = events[-1].get("dados")
        if isinstance(event_data, Mapping) and isinstance(
            event_data.get("steps"), list
        ):
            steps = deepcopy(cast(list[object], event_data["steps"]))
    status = "sucesso" if successful else "erro"
    response: dict[str, object] = {
        "status": status,
        "mensagem": message if successful else str(envelope.get("message", message)),
        "estado": _legacy_public_state(computation, source_state),
        "decisao": (
            deepcopy(dict(decision))
            if decision is not None
            else _legacy_public_decision(computation, source_state)
        ),
        "etapas": steps,
        "operation_id": result["operation_id"],
        "payload_hash": result["payload_hash"],
        "revision": (
            envelope.get("new_revision")
            if successful
            else envelope.get("current_revision", result["base_revision"])
        ),
        "envelope": deepcopy(dict(envelope)),
    }
    if not successful:
        response["codigo"] = envelope.get("code")
        response["campos"] = deepcopy(envelope.get("fields", []))
    return response


def legacy_validation_response(
    error: ContractValidationError,
    route: str,
    raw_input: object,
) -> dict[str, object]:
    state = estado_quarto
    computation = _legacy_protocol_computation(state)
    operation_id = _legacy_operation_id(
        route,
        "legacy_validation",
        {"code": error.code, "fields": list(error.fields)},
        raw_input,
        computation,
    )
    payload_hash = sha256(
        protocol.canonical_json_bytes(
            {"route": route, "input": raw_input, "revision": computation["revision"]}
        )
    ).hexdigest()
    error_code: protocol.ErrorCode
    if error.code == JSON_INVALID:
        error_code = "invalid_json"
    elif error.code == UNSAFE_ACTION:
        error_code = "unsafe_action"
    elif error.code == INTERNAL_ERROR:
        error_code = "internal_error"
    elif error.code in {
        DECISION_NOT_FOUND,
        DECISION_NOT_CONFIRMED,
        DECISION_OBSOLETE,
        COMMAND_NOT_CONFIRMED,
    }:
        error_code = "not_found"
    else:
        error_code = "invalid_payload"
    envelope = protocol.validate_transition_error({
        "status": "error",
        "schema_version": 1,
        "code": error_code,
        "http_status": protocol.ERROR_HTTP_STATUS[error_code],
        "message": (
            "The request could not be completed."
            if error_code == "internal_error"
            else error.message
        ),
        "fields": list(error.fields),
        "operation_id": operation_id,
        "received_revision": computation["revision"],
        "current_revision": computation["revision"],
        "snapshot": None,
    })
    result = {
        "envelope": cast(dict[str, object], envelope),
        "operation_id": operation_id,
        "payload_hash": payload_hash,
        "base_revision": computation["revision"],
        "source_state": deepcopy(state),
    }
    return legacy_response(result, message=error.message)


def legacy_internal_error_response(route: str, raw_input: object) -> dict[str, object]:
    error = ContractValidationError(
        INTERNAL_ERROR,
        "Falha interna ao processar a requisição.",
    )
    return legacy_validation_response(error, route, raw_input)


def ajustar(
    temp_str: str | None,
    umid_str: str | None,
    dormir: str | None,
    aberta: str | None,
) -> dict[str, object]:
    """Atualiza leituras legadas sem permitir controlar a temperatura interna.

    A temperatura recebida preserva a forma histórica da rota, mas a decisão
    sempre usa a temperatura interna medida no estado autoritativo.
    """

    raw_input = {
        "temperatura": temp_str,
        "umidade": umid_str,
        "dormir": dormir,
        "aberta": aberta,
    }
    try:
        _query_number(
            temp_str,
            "temperatura",
            MIN_TEMPERATURE_C,
            MAX_TEMPERATURE_C,
        )
        humidity = _query_number(
            umid_str,
            "umidade",
            MIN_HUMIDITY_PCT,
            MAX_HUMIDITY_PCT,
        )
        sleep = _query_binary(dormir, "dormir")
        window_open = _query_binary(aberta, "aberta")
    except ContractValidationError as error:
        return legacy_validation_response(error, "/ajustar", raw_input)

    preview_state = deepcopy(estado_quarto)
    preview_state["umidade"] = humidity
    preview_state["dormir"] = sleep
    if sleep == 1:
        preview_state["presenca_interna"] = 1
    preview_state["dispositivos"]["janela"] = window_open
    _refresh_luminosity(preview_state)
    environment = {
        "hora": preview_state["hora"],
        "temperatura_externa": preview_state["temperatura_externa"],
        "umidade": preview_state["umidade"],
        "chuva": preview_state["chuva"],
        "presenca_interna": preview_state["presenca_interna"],
        "presenca_externa": preview_state["presenca_externa"],
        "dormir": preview_state["dormir"],
    }
    result = run_legacy_transition(
        "/ajustar",
        "environment",
        environment,
        raw_input=raw_input,
    )
    return legacy_response(
        result,
        message="Prévia do ambiente ajustado.",
        decision=_preview_decision(preview_state),
    )


def apply_preset_request(payload: object) -> dict[str, object]:
    """Aplica calor, frio ou conforto preservando a aprendizagem atual."""

    preset_request = validate_preset_request(payload)
    try:
        apply_config_preset(preset_request["preset"])
    except PresetError:
        _fail(INVALID_PRESET, "O preset solicitado não existe.", ["preset"])
    _clear_confirmed_command_registry(estado_quarto)
    response = pegar_status()
    response["decisao"] = None
    response["etapas"] = []
    return response


def _start_new_run(state: RoomState, *, paused: bool) -> None:
    run_id = uuid4().hex
    state["run_id"] = run_id
    state["pruned_before"] = 0
    state["metricas"] = []
    state["resumo"] = _empty_run_summary(run_id)
    state["rastro"] = []
    state["decisao"] = None
    state["decisao_pendente"] = None
    state["etapas"] = []
    state["episodio_aberto"] = None
    state["feedbacks"] = []
    state["ultima_acao_confirmada"] = None
    state["execucao_automatica"] = {"pausada": paused}
    state["revisao_estado"] += 1
    _clear_confirmed_command_registry(state)


def new_run() -> dict[str, object]:
    _start_new_run(estado_quarto, paused=False)
    response = pegar_status()
    response["mensagem"] = "Nova execução iniciada."
    response["decisao"] = None
    response["etapas"] = []
    return response


def reset_environment(payload: object) -> dict[str, object]:
    """Limpa a jornada, preferências, métricas e rastro em uma nova execução."""

    validate_reset_request(payload)
    reset_config_state()
    estado_quarto["preferencias"].clear()
    _start_new_run(estado_quarto, paused=True)
    estado_quarto["modo"] = "reativo"
    response = pegar_status()
    response["decisao"] = None
    response["etapas"] = []
    return response


def _looks_like_state(value: object) -> bool:
    """Identifica a chamada opcional que fornece o estado antes da decisão."""

    return isinstance(value, Mapping) and {
        "dispositivos",
        "preferencias",
    }.issubset(value)


def _looks_like_decision(value: object) -> bool:
    """Identifica uma decisão nos formatos novo e compatível."""

    return isinstance(value, Mapping) and (
        "acao" in value or "action" in value
    )


def _decision_status_is_confirmed(decision: Mapping[str, object]) -> bool:
    """Indica se a decisão já terminou com confirmação física."""

    return decision.get("status") in {"confirmada", "confirmed"}


def _decision_action(decision: Mapping[str, object]) -> ActionName:
    """Obtém e valida a ação vencedora de uma decisão."""

    action = decision.get("strategy_id")
    if not isinstance(action, str):
        action = decision.get("acao", decision.get("action"))
    if action == "umidificacao":
        action = "umidificar"
    elif action == "iluminacao":
        action = "iluminar"
    if not isinstance(action, str):
        _fail(
            CORRECTION_INCOMPATIBLE,
            "A decisão não contém uma ação compatível.",
            ["decisao_id"],
        )
    try:
        return _normalise_action(action)
    except ValueError:
        _fail(
            CORRECTION_INCOMPATIBLE,
            "A decisão não contém uma ação compatível.",
            ["decisao_id"],
        )


def _decision_strategy_id(decision: Mapping[str, object]) -> str:
    """Resolve the canonical strategy independently of explanatory context."""

    value = decision.get("strategy_id")
    if isinstance(value, str):
        try:
            return _strategy_id(value)
        except ValueError:
            pass
    action = decision.get("acao", decision.get("action"))
    if not isinstance(action, str):
        _fail(
            CORRECTION_INCOMPATIBLE,
            "A decisão não contém uma estratégia compatível.",
            ["decisao_id"],
        )
    try:
        return _strategy_id(action)
    except ValueError:
        _fail(
            CORRECTION_INCOMPATIBLE,
            "A decisão não contém uma estratégia compatível.",
            ["decisao_id"],
        )


def _decision_objective(decision: Mapping[str, object]) -> DecisionObjective:
    """Read the objective that scopes a preference record."""

    value = decision.get("objetivo", decision.get("objective"))
    if isinstance(value, str) and value in {
        "seguranca",
        "umidade",
        "termico",
        "iluminacao",
        "manutencao",
    }:
        return cast(DecisionObjective, value)
    action = decision.get("strategy_id", decision.get("acao", decision.get("action")))
    if isinstance(action, str):
        return _default_preference_objective(action)
    _fail(
        CORRECTION_INCOMPATIBLE,
        "A decisão não contém um objetivo compatível.",
        ["decisao_id"],
    )


def _ensure_cognitive_feedback(decision: Mapping[str, object]) -> None:
    """Impede aprendizagem silenciosa a partir de uma decisão reativa."""

    if decision.get("modo", decision.get("mode")) not in {
        "cognitivo",
        "cognitive",
    }:
        _fail(
            CORRECTION_INCOMPATIBLE,
            "Feedback só está disponível para decisões cognitivas.",
            ["decisao_id"],
        )


def _decision_id(decision: Mapping[str, object]) -> str | None:
    """Obtém o identificador efêmero de uma decisão, quando disponível."""

    value = decision.get("decisao_id", decision.get("decisionId"))
    return value if isinstance(value, str) and value.strip() else None


def _resolve_decision(
    state: RoomState,
    decision: Decision | Mapping[str, object] | str | None,
) -> Mapping[str, object]:
    """Resolve uma decisão explícita ou a última decisão confirmada em memória."""

    if isinstance(decision, Mapping):
        resolved = cast(Mapping[str, object], decision)
        if resolved.get("status") == "invalidada":
            _fail(
                DECISION_OBSOLETE,
                "A decisão foi invalidada e não pode mais ser utilizada.",
                ["decisao_id"],
            )
        if not _decision_status_is_confirmed(resolved):
            _fail(
                DECISION_NOT_CONFIRMED,
                "A decisão precisa estar confirmada.",
                ["decisao_id"],
            )
        return resolved

    candidates: list[Mapping[str, object]] = []
    for value in (state["decisao"], state["decisao_pendente"]):
        if isinstance(value, Mapping):
            candidates.append(cast(Mapping[str, object], value))

    if isinstance(decision, str):
        candidates = [
            candidate
            for candidate in candidates
            if _decision_id(candidate) == decision
        ]
        if not candidates:
            _fail(
                DECISION_NOT_FOUND,
                "A decisão informada não existe.",
                ["decisao_id"],
            )
    elif decision is not None:
        _fail(
            DECISION_NOT_FOUND,
            "A decisão informada não existe.",
            ["decisao_id"],
        )

    for candidate in candidates:
        if _decision_status_is_confirmed(candidate):
            return candidate
    if candidates:
        if any(candidate.get("status") == "invalidada" for candidate in candidates):
            _fail(
                DECISION_OBSOLETE,
                "A decisão foi invalidada e não pode mais ser utilizada.",
                ["decisao_id"],
            )
        _fail(
            DECISION_NOT_CONFIRMED,
            "A decisão precisa estar confirmada.",
            ["decisao_id"],
        )
    _fail(
        DECISION_NOT_FOUND,
        "Nenhuma decisão confirmada está disponível.",
        ["decisao_id"],
    )


def confirmed_decision(state: RoomState, decision_id: str) -> Decision:
    """Retorna a decisão confirmada correlacionada em formato público."""

    return serialize_decision(_resolve_decision(state, decision_id))


def _validated_context(value: Mapping[str, object]) -> LearningContext:
    """Valida e copia um contexto persistido na decisão."""

    hour = value.get("hora")
    preset = value.get("preset")
    mode = value.get("modo")
    time_band = value.get("faixa_horario")
    sleep = value.get("dormir")
    temperature_band = value.get("faixa_temperatura")
    luminosity = value.get("luminosidade")
    inside = value.get("presenca_interna")
    if (
        (hour is not None and (type(hour) is not int or not 0 <= hour <= 23))
        or preset not in {"calor", "frio", "conforto"}
        or mode != "cognitivo"
        or time_band not in {"madrugada", "amanhecer", "dia", "noite"}
        or type(sleep) is not int
        or sleep not in (0, 1)
        or temperature_band not in {"frio", "conforto", "calor"}
        or luminosity not in {"escuro", "adequado", "claro"}
        or type(inside) is not int
        or inside not in (0, 1)
    ):
        _fail(
            CORRECTION_INCOMPATIBLE,
            "A decisão não contém um contexto compatível.",
            ["decisao_id"],
        )
    context: LearningContext = {
        "preset": cast(PresetName, preset),
        "modo": "cognitivo",
        "faixa_horario": cast(TimeBand, time_band),
        "dormir": cast(Binary, sleep),
        "faixa_temperatura": cast(TemperatureBand, temperature_band),
        "luminosidade": cast(Luminosity, luminosity),
        "presenca_interna": cast(Binary, inside),
    }
    if type(hour) is int:
        context["hora"] = hour
    return context


def _decision_context(
    state: RoomState,
    decision: Mapping[str, object],
) -> LearningContext:
    """Read explanatory context from the decision without making it normative."""

    value = decision.get("contexto", decision.get("context"))
    if not isinstance(value, Mapping):
        value = decision.get("identidade")
    if isinstance(value, Mapping):
        return _validated_context(cast(Mapping[str, object], value))
    _fail(
        CORRECTION_INCOMPATIBLE,
        "A decisão não contém um snapshot contextual.",
        ["decisao_id"],
    )


def _command_id(command: Mapping[str, object]) -> str | None:
    """Obtém o identificador de confirmação de um comando."""

    value = command.get("comando_id", command.get("commandId"))
    return value if isinstance(value, str) and value.strip() else None


def _confirmed_command_registry(
    state: RoomState,
) -> Mapping[str, Mapping[str, object]] | None:
    """Lê o conjunto efêmero de comandos manuais da última operação."""

    raw_registry = cast(Mapping[str, object], state).get(_CONFIRMED_COMMANDS_KEY)
    if raw_registry is None:
        return None
    if not isinstance(raw_registry, Mapping):
        return {}
    registry: dict[str, Mapping[str, object]] = {}
    for key, value in raw_registry.items():
        if isinstance(key, str) and isinstance(value, Mapping):
            registry[key] = cast(Mapping[str, object], value)
    return registry


def _replace_confirmed_command_registry(
    state: RoomState,
    steps: Iterable[PlanStep],
    decision_id: str | None,
    *,
    previous_devices: Mapping[str, object] | None = None,
) -> None:
    """Guarda somente confirmações manuais da operação corrente em memória."""

    registry: dict[str, dict[str, object]] = {}
    for step in steps:
        command_id = _command_id(step)
        if command_id is None:
            continue
        command = cast(dict[str, object], deepcopy(step))
        command["decisao_id"] = decision_id
        if previous_devices is not None:
            command_device = command.get("dispositivo")
            command["alterado"] = (
                isinstance(command_device, str)
                and previous_devices.get(command_device) != command.get("comando")
            )
        registry[command_id] = command
    cast(dict[str, object], state)[_CONFIRMED_COMMANDS_KEY] = registry


def _clear_confirmed_command_registry(state: RoomState) -> None:
    """Invalida confirmações manuais quando outra operação substitui o contexto."""

    cast(dict[str, object], state)[_CONFIRMED_COMMANDS_KEY] = {}


def _command_status_is_confirmed(command: Mapping[str, object]) -> bool:
    """Diferencia confirmação física de intenção ou etapa pendente."""

    status = command.get("status")
    if status in {"confirmado", "confirmed"}:
        return True
    return command.get("confirmado") is True or command.get("confirmed") is True


def _command_is_neutral(command: Mapping[str, object]) -> bool:
    """Identifica uma repetição que não alterou o estado do dispositivo."""

    if command.get("neutro") is True or command.get("neutral") is True:
        return True
    if command.get("alterado") is False or command.get("changed") is False:
        return True
    transitions = command.get("transicoes", command.get("transitions"))
    return isinstance(transitions, (list, tuple)) and list(transitions) == [
        "confirmado"
    ]


def _is_automatic_safety_signal(value: Mapping[str, object]) -> bool:
    """Identifica fechamento automático que não deve ensinar o agente."""

    if (
        value.get("automatico") is True
        or value.get("automatic") is True
        or value.get("seguranca_automatica") is True
    ):
        return True
    origin = value.get("origem", value.get("origin"))
    return origin in {
        "seguranca",
        "segurança",
        "security",
        "seguranca_automatica",
        "segurança_automática",
        "automatico",
        "automatic",
    }


def _command_device_and_value(
    command: Mapping[str, object],
) -> tuple[DeviceName, Binary] | None:
    """Obtém o dispositivo e o valor binário de um comando confirmado."""

    device = command.get("dispositivo", command.get("device"))
    value = command.get("comando", command.get("command", command.get("value")))
    if device not in _DEVICE_NAMES or type(value) is not int or value not in (0, 1):
        return None
    return cast(DeviceName, device), cast(Binary, value)


def _state_command_by_id(
    state: RoomState,
    command_id: str,
    decision: Mapping[str, object] | None = None,
) -> Mapping[str, object] | None:
    """Localiza uma confirmação manual efêmera já guardada no estado."""

    registry = _confirmed_command_registry(state)
    if registry is not None:
        return registry.get(command_id)

    values: list[object] = [state["etapas"]]
    if decision is not None:
        values.append(decision.get("plano"))
    for stored_decision in (state["decisao"], state["decisao_pendente"]):
        if isinstance(stored_decision, Mapping):
            values.append(stored_decision.get("plano"))
    for name in ("comandos_confirmados", "confirmed_commands"):
        values.append(cast(Mapping[str, object], state).get(name))
    for collection in values:
        if isinstance(collection, Mapping):
            collection_values: Iterable[object] = collection.values()
        elif isinstance(collection, (list, tuple)):
            collection_values = collection
        else:
            continue
        for value in collection_values:
            if not isinstance(value, Mapping):
                continue
            candidate = cast(Mapping[str, object], value)
            if _command_id(candidate) == command_id:
                return candidate
    return None


def _resolve_command(
    state: RoomState,
    command: PlanStep | Mapping[str, object] | str | None,
    command_id: str | None,
    decision: Mapping[str, object] | None = None,
) -> Mapping[str, object] | None:
    """Resolve uma confirmação por objeto ou por identificador efêmero."""

    if isinstance(command, Mapping):
        resolved = dict(cast(Mapping[str, object], command))
        resolved_id = _command_id(resolved) or command_id
        if resolved_id is not None:
            resolved["comando_id"] = resolved_id
            stored = _state_command_by_id(state, resolved_id, decision)
            if stored is None and _looks_like_state(state):
                return None
            if stored is not None:
                for key, value in stored.items():
                    resolved.setdefault(key, value)
        return cast(Mapping[str, object], resolved)

    resolved_id = command if isinstance(command, str) else command_id
    if resolved_id is None:
        return None
    return _state_command_by_id(state, resolved_id, decision)


def correction_is_eligible(
    decision: Decision | Mapping[str, object] | RoomState,
    command: PlanStep | Mapping[str, object] | Decision | None = None,
    confirmed_command: PlanStep | Mapping[str, object] | str | None = None,
    *,
    state: RoomState | None = None,
) -> bool:
    """Verifica se um comando confirmado é correção da ação da decisão.

    A forma principal é ``correction_is_eligible(decision, command)``. A forma
    ``correction_is_eligible(state, decision, command)`` também é aceita para
    permitir que a confirmação seja resolvida da memória do simulador.
    """

    if confirmed_command is not None:
        if not _looks_like_state(decision) or not _looks_like_decision(command):
            return False
        state = cast(RoomState, decision)
        decision_value = cast(Mapping[str, object], command)
        command_value_candidate: PlanStep | Mapping[str, object] | str = (
            confirmed_command
        )
    else:
        if _looks_like_state(decision):
            if not _looks_like_decision(command):
                return False
            return False
        if not isinstance(decision, Mapping):
            return False
        decision_value = cast(Mapping[str, object], decision)
        if not isinstance(command, (Mapping, str)):
            return False
        command_value_candidate = command

    command_value: Mapping[str, object]
    if state is not None:
        resolved_command = _resolve_command(
            state,
            command_value_candidate,
            None,
            decision_value,
        )
        if resolved_command is None:
            return False
        command_value = resolved_command
    elif isinstance(command_value_candidate, Mapping):
        command_value = cast(Mapping[str, object], command_value_candidate)
    else:
        return False

    if not _decision_status_is_confirmed(decision_value):
        return False
    if decision_value.get("modo", decision_value.get("mode")) not in {
        "cognitivo",
        "cognitive",
    }:
        return False
    objective = decision_value.get("objetivo", decision_value.get("objective"))
    if objective not in {"umidade", "termico", "iluminacao", "manutencao"}:
        return False
    objective_name = cast(DecisionObjective, objective)
    action_value = decision_value.get("strategy_id")
    if not isinstance(action_value, str):
        action_value = decision_value.get("acao", decision_value.get("action"))
    if action_value == "umidificacao":
        action_value = "umidificar"
    elif action_value == "iluminacao":
        action_value = "iluminar"
    if not isinstance(action_value, str):
        return False
    try:
        action = _normalise_action(action_value)
    except ValueError:
        return False
    if action not in _CORRECTION_MATRIX:
        return False
    if objective_name not in _CORRECTION_OBJECTIVES[action]:
        return False
    if objective in {
        "seguranca",
        "security",
    }:
        return False
    if _is_automatic_safety_signal(decision_value) or _is_automatic_safety_signal(
        command_value
    ):
        return False
    decision_identifier = _decision_id(decision_value)
    if state is not None:
        stored_decision = state.get("decisao")
        if isinstance(stored_decision, Mapping):
            stored_decision_value = cast(Mapping[str, object], stored_decision)
            stored_identifier = _decision_id(stored_decision_value)
            if (
                decision_identifier is not None
                and stored_identifier is not None
                and stored_identifier != decision_identifier
            ):
                return False
            if (
                decision_identifier is not None
                and stored_identifier == decision_identifier
                and not _decision_status_is_confirmed(stored_decision_value)
            ):
                return False
    command_decision_identifier = command_value.get(
        "decisao_id", command_value.get("decisionId")
    )
    if decision_identifier is not None:
        if (
            command_decision_identifier is not None
            and command_decision_identifier != decision_identifier
        ):
            return False
        if (
            state is not None
            and command_decision_identifier != decision_identifier
            and any(
                field in command_value
                for field in (
                    "comando_id",
                    "commandId",
                    "status",
                    "confirmado",
                    "confirmed",
                    "transicoes",
                    "transitions",
                )
            )
        ):
            return False

    has_physical_confirmation = any(
        field in command_value
        for field in (
            "comando_id",
            "commandId",
            "status",
            "confirmado",
            "confirmed",
            "transicoes",
            "transitions",
        )
    )
    if has_physical_confirmation:
        if _command_id(command_value) is None:
            return False
        if not _command_status_is_confirmed(command_value) or _command_is_neutral(
            command_value
        ):
            return False
    command_parts = _command_device_and_value(command_value)
    if command_parts is None:
        return False
    device, value = command_parts
    route = command_value.get("rota", command_value.get("route"))
    if route is not None and not isinstance(route, str):
        return False
    decision_corrections = decision_value.get("correcoes_permitidas")
    if decision_corrections is not None:
        if not isinstance(decision_corrections, (list, tuple)):
            return False
        decision_allowed = next(
            (
                correction
                for correction in decision_corrections
                if isinstance(correction, Mapping)
                and _command_device_and_value(correction) == (device, value)
                and (
                    route is None
                    or correction.get("rota", correction.get("route")) == route
                )
            ),
            None,
        )
        if decision_allowed is None:
            return False
    allowed = next(
        (
            entry
            for entry in _CORRECTION_MATRIX[action]
            if entry[1] == device and entry[2] == value
        ),
        None,
    )
    if allowed is None or (route is not None and route != allowed[0]):
        return False

    if state is not None and has_physical_confirmation:
        devices = state.get("dispositivos")
        if not isinstance(devices, Mapping) or devices.get(device) != value:
            return False
    if state is not None and not has_physical_confirmation:
        devices = state.get("dispositivos")
        if not isinstance(devices, Mapping) or devices.get(device) == value:
            return False
    return True


def _feedback_record_for_decision(
    state: RoomState,
    decision_id: str,
) -> tuple[Mapping[str, object], str | None] | None:
    """Find the first feedback result and command recorded for a decision."""

    for event in reversed(state["rastro"]):
        if event["tipo"] != "feedback" or event["decisao_id"] != decision_id:
            continue
        result = event["dados"].get("resultado")
        if isinstance(result, Mapping):
            return (
                cast(Mapping[str, object], result),
                event["comando_id"],
            )

    for value in reversed(state["feedbacks"]):
        if not isinstance(value, Mapping):
            continue
        result = cast(Mapping[str, object], value)
        if result.get("decisao_id") != decision_id:
            continue
        command_value = result.get("comando_id")
        command_id = command_value if isinstance(command_value, str) else None
        return result, command_id
    return None


def _feedback_identity(
    decision: Mapping[str, object],
    context: LearningContext,
) -> LearningIdentity:
    """Materialize explanatory context frozen with the decision snapshot."""

    value = decision.get("identidade")
    identity_context = context
    if isinstance(value, Mapping):
        identity_context = _validated_context(cast(Mapping[str, object], value))
    return {
        "preset": identity_context["preset"],
        "modo": "cognitivo",
        "faixa_horario": identity_context["faixa_horario"],
        "dormir": identity_context["dormir"],
        "faixa_temperatura": identity_context["faixa_temperatura"],
        "luminosidade": identity_context["luminosidade"],
        "presenca_interna": identity_context["presenca_interna"],
    }


def _idempotent_feedback_result(
    result: Mapping[str, object],
) -> FeedbackResult:
    """Return a stored result marked as the response to an identical retry."""

    replay = cast(dict[str, object], deepcopy(dict(result)))
    replay["idempotente"] = True
    return cast(FeedbackResult, replay)


def record_feedback(
    state: RoomState | LearningContext,
    decision: Decision | Mapping[str, object] | str | None = None,
    feedback_type: str | Mapping[str, object] | None = None,
    command: PlanStep | Mapping[str, object] | str | None = None,
    *,
    command_id: str | None = None,
    confirmed_command: PlanStep | Mapping[str, object] | str | None = None,
    tipo: str | None = None,
    decision_id: str | None = None,
    decisao_id: str | None = None,
    comando_id: str | None = None,
) -> FeedbackResult | LearningResult:
    """Registra feedback e atualiza a preferência somente em memória.

    A forma pública ``record_feedback(contexto, acao, tipo)`` usa o estado
    global do simulador. O contexto explica a observação, mas não compõe a chave.
    Feedback comum usa a decisão confirmada e ``aceitar``/``rejeitar``.
    ``corrigir`` exige uma confirmação manual relacionada e não neutra.
    """

    if not _looks_like_state(state):
        if not isinstance(state, Mapping):
            raise ValueError("O primeiro argumento deve ser um estado ou contexto.")
        public_feedback_type = feedback_type if feedback_type is not None else tipo
        if not isinstance(decision, str) or not isinstance(public_feedback_type, str):
            raise ValueError("A forma pública exige contexto, ação e tipo.")
        if (
            command is not None
            or confirmed_command is not None
            or command_id is not None
            or decisao_id is not None
            or decision_id is not None
            or comando_id is not None
        ):
            raise ValueError("A forma pública não aceita correlação adicional.")
        context = _validated_context(cast(Mapping[str, object], state))
        action = _normalise_action(decision)
        objective = _default_preference_objective(action)
        _, delta = _normalise_feedback_type(public_feedback_type)
        preference_key = _preference_key(context, action, objective)
        previous = _preference_for(estado_quarto, context, action, objective)
        if (delta == 1 and previous >= 3) or (delta == -1 and previous <= -3):
            _fail(
                PREFERENCE_AT_LIMIT,
                "A preferência já está no limite para este objetivo e estratégia.",
                ["preferencia"],
            )
        current = previous + delta
        estado_quarto["preferencias"][preference_key] = current
        public_result: LearningResult = {
            "contexto": deepcopy(context),
            "acao": action,
            "delta": delta,
            "preferencia_anterior": previous,
            "preferencia_atual": current,
        }
        estado_quarto["feedbacks"].append(deepcopy(public_result))
        append_trace_event(
            estado_quarto,
            "feedback",
            dados={
                "tipo": public_feedback_type,
                "acao": action,
                "delta": delta,
            },
        )
        return public_result

    state = cast(RoomState, state)
    _ensure_preset_selected(state)

    if decision_id is not None and decisao_id is not None and decision_id != decisao_id:
        _fail(
            FEEDBACK_CONFLICTING,
            "Os identificadores da decisão não coincidem.",
            ["decisao_id"],
        )
    resolved_decision_id = decision_id if decision_id is not None else decisao_id
    if resolved_decision_id is not None:
        if isinstance(decision, Mapping):
            if _decision_id(cast(Mapping[str, object], decision)) != resolved_decision_id:
                _fail(
                    FEEDBACK_CONFLICTING,
                    "Os identificadores da decisão não coincidem.",
                    ["decisao_id"],
                )
        elif decision is not None and decision != resolved_decision_id:
            _fail(
                FEEDBACK_CONFLICTING,
                "Os identificadores da decisão não coincidem.",
                ["decisao_id"],
            )
        decision = resolved_decision_id

    if command_id is not None and comando_id is not None and command_id != comando_id:
        _fail(
            FEEDBACK_CONFLICTING,
            "Os identificadores do comando não coincidem.",
            ["comando_id"],
        )
    resolved_command_id = command_id if command_id is not None else comando_id

    if tipo is not None:
        if feedback_type is not None and feedback_type != tipo:
            _fail(
                FEEDBACK_CONFLICTING,
                "Os tipos de feedback não coincidem.",
                ["tipo"],
            )
        feedback_type = tipo

    if isinstance(decision, str) and decision in _FEEDBACK_DELTAS:
        if feedback_type is None:
            feedback_type = decision
            decision = None
        else:
            decision, feedback_type = feedback_type, decision

    if not isinstance(feedback_type, str):
        _fail(MISSING_FIELD, "O tipo de feedback é obrigatório.", ["tipo"])
    canonical_type, delta = _normalise_feedback_type(feedback_type)
    resolved_decision = _resolve_decision(state, decision)
    _ensure_cognitive_feedback(resolved_decision)
    action = _decision_action(resolved_decision)
    objective = _decision_objective(resolved_decision)
    strategy_id = _decision_strategy_id(resolved_decision)
    context = _decision_context(state, resolved_decision)
    identity = _feedback_identity(resolved_decision, context)
    active_decision_id = _decision_id(resolved_decision) or resolved_decision_id
    if active_decision_id is None:
        _fail(
            DECISION_NOT_FOUND,
            "A decisão informada não existe.",
            ["decisao_id"],
        )

    supplied_command: PlanStep | Mapping[str, object] | str | None = (
        confirmed_command if confirmed_command is not None else command
    )
    requested_command_id = resolved_command_id
    if requested_command_id is None:
        if isinstance(supplied_command, Mapping):
            requested_command_id = _command_id(supplied_command)
        elif isinstance(supplied_command, str):
            requested_command_id = supplied_command

    stored_feedback = _feedback_record_for_decision(state, active_decision_id)
    if stored_feedback is not None:
        stored_result, stored_command_id = stored_feedback
        stored_type = stored_result.get("tipo")
        if stored_type != canonical_type or stored_command_id != requested_command_id:
            _fail(
                FEEDBACK_CONFLICTING,
                "A decisão já possui um feedback diferente registrado.",
                ["decisao_id"],
            )
        return _idempotent_feedback_result(stored_result)

    resolved_command: Mapping[str, object] | None = None
    if canonical_type == "corrigir":
        resolved_command = _resolve_command(
            state,
            supplied_command,
            resolved_command_id,
            resolved_decision,
        )
        if resolved_command is None or not correction_is_eligible(
            resolved_decision,
            resolved_command,
            state=state,
        ):
            if resolved_command is None:
                _fail(
                    COMMAND_NOT_CONFIRMED,
                    "O comando informado não está confirmado.",
                    ["comando_id"],
                )
            _fail(
                CORRECTION_INCOMPATIBLE,
                "O comando não é compatível com a decisão informada.",
                ["comando_id"],
            )
    elif supplied_command is not None or resolved_command_id is not None:
        _fail(
            CORRECTION_INCOMPATIBLE,
            "Feedback comum não aceita comando de correção.",
            ["comando_id"],
        )

    preference_key = _preference_key(context, strategy_id, objective)
    previous = _preference_for(state, context, strategy_id, objective)
    if (delta == 1 and previous >= 3) or (delta == -1 and previous <= -3):
        _fail(
            PREFERENCE_AT_LIMIT,
            "A preferência já está no limite para este objetivo e estratégia.",
            ["preferencia"],
        )
    current = previous + delta
    state["preferencias"][preference_key] = current
    if canonical_type == "corrigir" and action in {
        "ventilacao_natural",
        "ventilacao_assistida",
        "circulacao_interna",
    }:
        state["ultima_acao_confirmada"] = None
    result: FeedbackResult = {
        "decisao_id": active_decision_id,
        "tipo": canonical_type,
        "acao": cast(ActionName, _legacy_action(action)),
        "identidade": deepcopy(identity),
        "preferencia_anterior": previous,
        "delta": delta,
        "preferencia_atual": current,
        "condicao_reaplicacao": _FEEDBACK_REAPPLICATION_CONDITION,
        "idempotente": False,
    }
    state["feedbacks"] = [deepcopy(result)]
    trace_command_id = (
        _command_id(resolved_command)
        if canonical_type == "corrigir" and resolved_command is not None
        else None
    )
    append_trace_event(
        state,
        "feedback",
        decisao_id=active_decision_id,
        comando_id=trace_command_id,
        dados={
            "tipo": canonical_type,
            "acao": action,
            "delta": delta,
            "preferencia_anterior": previous,
            "preferencia_atual": current,
            "resultado": deepcopy(result),
        },
    )
    record_observed_feedback(state, active_decision_id, canonical_type)
    return result

