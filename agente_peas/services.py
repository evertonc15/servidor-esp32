"""Serviços determinísticos para o ambiente simulado do quarto."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
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
from uuid import uuid4

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
)


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
    "umidificar",
    "iluminar",
]
TemperatureBand: TypeAlias = Literal["frio", "conforto", "calor"]
TimeBand: TypeAlias = Literal["madrugada", "amanhecer", "dia", "noite"]
CognitiveMode: TypeAlias = Literal["cognitivo"]
FeedbackType: TypeAlias = Literal["aceitar", "rejeitar", "corrigir"]
LearningContextKey: TypeAlias = tuple[
    PresetName,
    CognitiveMode,
    TimeBand,
    Binary,
    TemperatureBand,
    Luminosity,
    Binary,
]
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
    """Snapshot contextual capturado para a aprendizagem cognitiva."""

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
    """Resultado de uma alteração de preferência contextual."""

    contexto: LearningContext
    acao: ActionName
    delta: Literal[-1, 1]
    preferencia_anterior: int
    preferencia_atual: int


class DecisionAlternative(TypedDict):
    """Alternativa cognitiva avaliada pelo agente."""

    acao: ActionName
    pontuacao_base: float
    preferencia_contextual: int
    pontuacao_total: float
    elegivel: bool
    influenciada: bool
    motivo_bloqueio: str | None
    correcoes_permitidas: list[CorrectionCommand]
    conforto: NotRequired[float]
    economia: NotRequired[float]
    preferencia: NotRequired[int]
    utilidade: NotRequired[float | None]


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
TEMP_LIMIT_C: Final[float] = TEMP_HOT_LIMIT_C
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
_PLAN_STEPS: Final[
    dict[ActionName, tuple[tuple[DeviceName, Binary], ...]]
] = {
    "manter": (),
    "ventilar": (("ar", 0), ("janela", 1), ("ventilador", 1)),
    "resfriar": (("janela", 0), ("ar", 1), ("ventilador", 0)),
    "fechar": (("janela", 0), ("ar", 0), ("ventilador", 0)),
    "umidificar": (("umidificador", 1),),
    "iluminar": (("lampada", 1),),
}
_ACTION_ECONOMY: Final[dict[ActionName, float]] = {
    "manter": 1.0,
    "fechar": 1.0,
    "ventilar": 0.75,
    "iluminar": 0.75,
    "umidificar": 0.5,
    "resfriar": 0.0,
}
_ACTION_COST: Final[dict[ActionName, int]] = {
    "manter": 0,
    "fechar": 3,
    "ventilar": 3,
    "resfriar": 3,
    "umidificar": 1,
    "iluminar": 1,
}
_ACTION_ORDER: Final[dict[ActionName, int]] = {
    "manter": 0,
    "fechar": 1,
    "ventilar": 2,
    "resfriar": 3,
    "umidificar": 4,
    "iluminar": 5,
}
_UTILITY_EPSILON: Final[float] = 0.01
_FEEDBACK_DELTAS: Final[dict[str, tuple[FeedbackType, Literal[-1, 1]]]] = {
    "aceitar": ("aceitar", 1),
    "rejeitar": ("rejeitar", -1),
    "corrigir": ("corrigir", -1),
    "accept": ("aceitar", 1),
    "reject": ("rejeitar", -1),
    "manual_correction": ("corrigir", -1),
}
_FEEDBACK_REAPPLICATION_CONDITION: Final[str] = (
    "Reaplicável para a mesma identidade congelada e a mesma ação."
)
_CORRECTION_MATRIX: Final[
    dict[ActionName, tuple[tuple[str, DeviceName, Binary], ...]]
] = {
    "manter": (),
    "ventilar": (
        ("/interf/ligarar", "ar", 1),
        ("/interf/fechar", "janela", 0),
        ("/interf/desligarventilador", "ventilador", 0),
    ),
    "resfriar": (
        ("/interf/abrir", "janela", 1),
        ("/interf/desligarar", "ar", 0),
        ("/interf/ligarventilador", "ventilador", 1),
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
_CORRECTION_OBJECTIVES: Final[dict[ActionName, tuple[DecisionObjective, ...]]] = {
    "manter": ("umidade", "termico", "iluminacao", "manutencao"),
    "fechar": ("termico",),
    "ventilar": ("termico",),
    "resfriar": ("termico",),
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

    if humidifier_on:
        humidity_delta = 4.0
    elif window_open:
        humidity_delta = -2.0
    else:
        humidity_delta = 0.0

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

    if action not in _PLAN_STEPS:
        raise ValueError(f"Ação desconhecida: {action!r}")
    return cast(ActionName, action)


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


def _learning_context_key(context: LearningContext) -> LearningContextKey:
    """Converte o contexto normativo em sua chave imutável."""

    return (
        context["preset"],
        context["modo"],
        context["faixa_horario"],
        context["dormir"],
        context["faixa_temperatura"],
        context["luminosidade"],
        context["presenca_interna"],
    )


def _preference_key(
    context: LearningContext,
    action: ActionName,
) -> PreferenceKey:
    """Combina e serializa a identidade contextual e a ação."""

    return json.dumps(
        (*_learning_context_key(context), action),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _preference_for(
    state: RoomState,
    context: LearningContext,
    action: ActionName,
) -> int:
    """Lê uma preferência contextual limitada sem persistência externa."""

    value = state["preferencias"].get(_preference_key(context, action), 0)
    if type(value) is not int:
        raise ValueError("A preferência contextual deve ser um inteiro.")
    return max(-3, min(3, value))


def _allowed_corrections(action: ActionName) -> list[CorrectionCommand]:
    """Materializa a matriz inversa no formato do contrato da decisão."""

    corrections: list[CorrectionCommand] = []
    for route, device, command in _CORRECTION_MATRIX.get(action, ()):
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


def calculate_utility(
    conforto: float,
    economia: float,
    preferencia: int,
) -> float:
    """Calcula a utilidade normativa de uma alternativa elegível."""

    return round(
        0.6 * conforto + 0.4 * economia + preferencia,
        2,
    )


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
    if temperature > TEMP_HOT_LIMIT_C:
        return ("ventilar", "resfriar", "manter"), "termico"
    if temperature < TEMP_COLD_LIMIT_C and _cold_action_pending(devices):
        return ("fechar", "manter"), "termico"
    if temperature <= TEMP_CLIMATE_OFF_C and _climate_shutdown_pending(devices):
        return ("manter",), "termico"
    if _lighting_action_pending(readings, devices):
        return ("iluminar", "manter"), "iluminacao"
    return ("manter",), "manutencao"


def _alternative_comfort(
    action: ActionName,
    objective: DecisionObjective,
    state: RoomState,
) -> float:
    """Retorna o conforto binário da ação para o objetivo selecionado."""

    if objective == "seguranca":
        if action == "fechar":
            return 1.0
        if state["temperatura_interna"] > TEMP_HOT_LIMIT_C:
            return 1.0 if action in {"ventilar", "resfriar"} else 0.0
        return 0.0
    if objective == "umidade":
        return 1.0 if action == "umidificar" else 0.0
    if objective == "termico":
        if state["temperatura_interna"] < TEMP_COLD_LIMIT_C:
            return 1.0 if action == "fechar" else 0.0
        return 1.0 if action in {"ventilar", "resfriar"} else 0.0
    if objective == "iluminacao":
        return 1.0 if action == "iluminar" else 0.0
    return 1.0 if action == "manter" else 0.0


def _alternative_block_reason(
    action: ActionName,
    state: RoomState,
) -> str | None:
    """Explica por que uma alternativa não pode ser escolhida no ciclo."""

    readings = read_sensors(state)
    devices = state["dispositivos"]
    reasons: list[str] = []

    if action == "ventilar":
        if readings["chuva"] == 1:
            reasons.append("chuva detectada: abertura da janela bloqueada")
        if readings["presenca_externa"] == 1:
            reasons.append(
                "presença externa detectada: abertura da janela bloqueada"
            )
        if devices["ar"] == 1:
            reasons.append(
                "intertravamento: ar ligado impede a abertura da janela"
            )
        if (
            readings["temperatura_interna"] > TEMP_HOT_LIMIT_C
            and state["ultima_acao_confirmada"] == "ventilar"
        ):
            reasons.append(
                "escalada térmica: ventilação anterior confirmada sem reduzir o calor"
            )
    elif action == "manter":
        if (
            devices["janela"] == 1
            and (readings["chuva"] == 1 or readings["presenca_externa"] == 1)
        ):
            reasons.append(
                "segurança: manter a janela aberta viola a proteção do quarto"
            )
        if devices["janela"] == 1 and devices["ar"] == 1:
            reasons.append(
                "intertravamento: janela aberta e ar ligado são incompatíveis"
            )

    return "; ".join(reasons) if reasons else None


def _alternative_change_count(action: ActionName, state: RoomState) -> int:
    """Conta as mudanças físicas necessárias para o plano da alternativa."""

    if action == "manter":
        plan = _build_maintenance_plan(
            read_sensors(state),
            state["dispositivos"],
        )
        return sum(step["status"] == "pendente" for step in plan)
    return sum(
        step["status"] == "pendente"
        for step in build_plan(action, state["dispositivos"])
    )


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

    winner = eligible[0]
    winner_score = winner[score_field]
    for current in eligible[1:]:
        current_score = current[score_field]
        if current_score > winner_score + _UTILITY_EPSILON:
            winner = current
            winner_score = current_score
        elif (
            abs(current_score - winner_score)
            <= _UTILITY_EPSILON + 1e-12
            and _cognitive_tie_key(
                current["acao"], state
            )
            < _cognitive_tie_key(winner["acao"], state)
        ):
            winner = current
            winner_score = current_score
    return winner


def evaluate_alternatives(state: RoomState) -> list[DecisionAlternative]:
    """Avalia somente as alternativas do objetivo prioritário atual.

    A avaliação é pura: não executa planos, altera dispositivos ou consulta a
    temperatura externa. A preferência é lida da memória contextual do estado.
    """

    actions, objective = _cognitive_actions(state)
    return _evaluate_objective_alternatives(state, actions, objective)


def _evaluate_objective_alternatives(
    state: RoomState,
    actions: Iterable[ActionName],
    objective: DecisionObjective,
) -> list[DecisionAlternative]:
    """Aplica a mesma utilidade e aprendizagem a um objetivo independente."""

    context = build_learning_context(state)
    alternatives: list[DecisionAlternative] = []
    for action in actions:
        blocked_reason = _alternative_block_reason(action, state)
        eligible = blocked_reason is None
        corrections = (
            _allowed_corrections(action)
            if eligible and objective != "seguranca"
            else []
        )
        comfort = _alternative_comfort(action, objective, state)
        economy = _ACTION_ECONOMY[action]
        preference = _preference_for(state, context, action)
        base_score = calculate_utility(comfort, economy, 0)
        total_score = round(base_score + preference, 2)
        utility = (
            total_score
            if eligible
            else None
        )
        alternatives.append(
            {
                "acao": action,
                "pontuacao_base": base_score,
                "preferencia_contextual": preference,
                "pontuacao_total": total_score,
                "elegivel": eligible,
                "influenciada": preference != 0,
                "motivo_bloqueio": blocked_reason,
                "correcoes_permitidas": corrections,
                "conforto": comfort,
                "economia": economy,
                "preferencia": preference,
                "utilidade": utility,
            }
        )

    winner = _select_cognitive_alternative(alternatives, state, "pontuacao_total")
    baseline_winner = _select_cognitive_alternative(
        alternatives,
        state,
        "pontuacao_base",
    )
    winner_changed_without_preferences = (
        winner["acao"] != baseline_winner["acao"]
    )
    for alternative in alternatives:
        alternative["influenciada"] = (
            alternative["preferencia_contextual"] != 0
            or (
                winner_changed_without_preferences
                and alternative["acao"] == winner["acao"]
            )
        )
    return alternatives


def _cognitive_tie_key(
    action: ActionName,
    state: RoomState,
) -> tuple[int, int, int, int]:
    """Produz a chave lexicográfica do desempate cognitivo."""

    return (
        0 if action == "manter" else 1,
        _ACTION_COST[action],
        _alternative_change_count(action, state),
        _ACTION_ORDER[action],
    )


def _cognitive_decision_reason(
    objective: DecisionObjective,
    winner: DecisionAlternative,
    baseline_winner: DecisionAlternative,
) -> str:
    """Explica o efeito causal da preferência sobre a alternativa vencedora."""

    action = winner["acao"]
    baseline_action = baseline_winner["acao"]
    preference = winner["preferencia_contextual"]
    score = winner["pontuacao_total"]
    base_score = winner["pontuacao_base"]

    if action != baseline_action:
        causal_reason = (
            f"Sem preferências contextuais, a vencedora seria "
            f"{baseline_action}; a preferência contextual alterou a escolha "
            f"para {action}."
        )
    elif preference != 0:
        causal_reason = (
            f"Sem preferências contextuais, {action} também venceria; a "
            "preferência contextual foi considerada, mas não alterou a "
            "vencedora."
        )
    else:
        causal_reason = (
            f"Sem preferências contextuais, {action} também venceria; não "
            "houve influência contextual na escolha."
        )
    return (
        f"Objetivo {objective}: ação {action} escolhida com pontuação-base "
        f"{base_score:.2f}, preferência contextual {preference:+d} e "
        f"pontuação total {score:.2f}. {causal_reason}"
    )


def choose_cognitive_action(state: RoomState) -> ActionName:
    """Escolhe a alternativa elegível de maior utilidade determinística."""

    evaluated = evaluate_alternatives(state)
    winner = _select_cognitive_alternative(
        evaluated,
        state,
        "pontuacao_total",
    )
    return winner["acao"]


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
) -> list[PlanStep]:
    """Monta desligamentos de segurança, iluminação e climatização."""

    commands: list[tuple[DeviceName, Binary]] = []
    if readings["presenca_interna"] == 0:
        commands.extend((("umidificador", 0), ("lampada", 0)))
    elif not _lighting_required(readings) and device_state.get("lampada") == 1:
        commands.append(("lampada", 0))

    if (
        readings["presenca_interna"] == 1
        and readings["temperatura_interna"] <= TEMP_CLIMATE_OFF_C
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
    for step in _build_maintenance_plan(readings, device_state):
        command_by_device[step["dispositivo"]] = step["comando"]
    return _build_plan_steps(command_by_device.items(), device_state)


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
    if readings["temperatura_interna"] > TEMP_HOT_LIMIT_C:
        groups.append(("termico", ("resfriar", "ventilar", "manter")))
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
            action = _select_cognitive_alternative(
                alternatives, evaluated_state, "pontuacao_total"
            )["acao"]
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
        alternatives: list[DecisionAlternative] = [
            {
                "acao": action,
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
        action = _select_cognitive_alternative(
            alternatives,
            state,
            "pontuacao_total",
        )["acao"]
        _, objective = _cognitive_actions(state)
        winner = next(
            alternative
            for alternative in alternatives
            if alternative["acao"] == action
        )
        baseline_winner = _select_cognitive_alternative(
            alternatives,
            state,
            "pontuacao_base",
        )
        reason = _cognitive_decision_reason(objective, winner, baseline_winner)

    actions = _compatible_cycle_actions(state, action, objective, selected_mode)
    decision: Decision = {
        "decisao_id": uuid4().hex,
        "identidade": (
            _learning_identity(state, context, selected_mode)
            if context is not None
            else None
        ),
        "modo": selected_mode,
        "objetivo": objective,
        "acao": action,
        "acoes": actions,
        "status": "prevista",
        "motivo": reason,
        "alternativas": alternatives,
        "plano": _build_decision_plan(actions, readings, state["dispositivos"]),
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

    _ensure_window_opening_is_safe(
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

    preview_state = deepcopy(estado_quarto)
    preview_state["umidade"] = humidity
    preview_state["dormir"] = sleep
    if sleep == 1:
        preview_state["presenca_interna"] = 1
    preview_state["dispositivos"]["janela"] = window_open
    _refresh_luminosity(preview_state)

    response = pegar_status()
    response["decisao"] = _preview_decision(preview_state)
    return response


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


def reset_environment(payload: object) -> dict[str, object]:
    """Limpa a jornada visível, preservando aprendizagem e rastro."""

    validate_reset_request(payload)
    reset_config_state()
    _clear_confirmed_command_registry(estado_quarto)
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

    action = decision.get("acao", decision.get("action"))
    if action not in _PLAN_STEPS:
        _fail(
            CORRECTION_INCOMPATIBLE,
            "A decisão não contém uma ação compatível.",
            ["decisao_id"],
        )
    return cast(ActionName, action)


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
    """Obtém o snapshot contextual da decisão, sem usar sinais posteriores."""

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
    action_value = decision_value.get("acao", decision_value.get("action"))
    if not isinstance(action_value, str) or action_value not in _CORRECTION_MATRIX:
        return False
    action = cast(ActionName, action_value)
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
    """Materialize the frozen identity captured by the decision snapshot."""

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
    global do simulador para preservar a memória contextual.
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
        _, delta = _normalise_feedback_type(public_feedback_type)
        preference_key = _preference_key(context, action)
        previous = _preference_for(estado_quarto, context, action)
        if (delta == 1 and previous >= 3) or (delta == -1 and previous <= -3):
            _fail(
                PREFERENCE_AT_LIMIT,
                "A preferência já está no limite para esta identidade e ação.",
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

    preference_key = _preference_key(context, action)
    previous = _preference_for(state, context, action)
    if (delta == 1 and previous >= 3) or (delta == -1 and previous <= -3):
        _fail(
            PREFERENCE_AT_LIMIT,
            "A preferência já está no limite para esta identidade e ação.",
            ["preferencia"],
        )
    current = previous + delta
    state["preferencias"][preference_key] = current
    if canonical_type == "corrigir" and action == "ventilar":
        state["ultima_acao_confirmada"] = None
    result: FeedbackResult = {
        "decisao_id": active_decision_id,
        "tipo": canonical_type,
        "acao": action,
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
    return result

