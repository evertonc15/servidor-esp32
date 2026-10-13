from collections.abc import Mapping
from hashlib import sha256
import json
from math import isfinite
from typing import Final, Literal, NotRequired, TypeAlias, TypedDict, TypeGuard, cast


Binary: TypeAlias = Literal[0, 1]
SchemaVersion: TypeAlias = Literal[1]
Mode: TypeAlias = Literal["reativo", "cognitivo"]
Luminosity: TypeAlias = Literal["escuro", "adequado", "claro"]
PresetName: TypeAlias = Literal["calor", "frio", "conforto"]
DeviceName: TypeAlias = Literal[
    "janela",
    "ar",
    "ventilador",
    "umidificador",
    "lampada",
]
Objective: TypeAlias = Literal[
    "seguranca",
    "umidade",
    "termico",
    "iluminacao",
    "manutencao",
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
OperationKind: TypeAlias = Literal[
    "cycle",
    "environment",
    "manual_command",
    "feedback",
    "preset",
    "pause",
    "resume",
    "new_run",
    "reset",
    "checkpoint",
]
MutationOperationKind: TypeAlias = Literal[
    "cycle",
    "environment",
    "manual_command",
    "feedback",
    "preset",
    "pause",
    "resume",
    "new_run",
    "reset",
]
FeedbackType: TypeAlias = Literal["aceitar", "rejeitar", "corrigir"]
OperationStatus: TypeAlias = Literal[
    "pending",
    "sent",
    "accepted",
    "persisted",
    "retryable",
    "failed",
    "timeout",
    "unknown",
]
ErrorCode: TypeAlias = Literal[
    "invalid_json",
    "schema_unsupported",
    "invalid_payload",
    "identity_mismatch",
    "stale_revision",
    "operation_conflict",
    "operation_in_flight",
    "unsafe_action",
    "invalid_state",
    "not_found",
    "internal_error",
]
ErrorHttpStatus: TypeAlias = Literal[400, 409, 422, 500]
PreferenceValue: TypeAlias = Literal[-3, -2, -1, 0, 1, 2, 3]
PreferenceKey: TypeAlias = tuple[Objective, StrategyId]

ERROR_HTTP_STATUS: Final[dict[ErrorCode, ErrorHttpStatus]] = {
    "invalid_json": 400,
    "schema_unsupported": 400,
    "invalid_payload": 422,
    "identity_mismatch": 409,
    "stale_revision": 409,
    "operation_conflict": 409,
    "operation_in_flight": 409,
    "unsafe_action": 422,
    "invalid_state": 422,
    "not_found": 422,
    "internal_error": 500,
}

MAX_IDENTITY_ID_LENGTH: Final[int] = 128
MAX_OPERATION_ID_LENGTH: Final[int] = 128
MAX_TRACE_PAGE_LIMIT: Final[int] = 200
MAX_CYCLE_HISTORY: Final[int] = 10000


class IdentityRef(TypedDict):
    identity_id: str
    identity_generation: int


class PhysicalState(TypedDict):
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


class DeviceVector(TypedDict):
    janela: Binary
    ar: Binary
    ventilador: Binary
    umidificador: Binary
    lampada: Binary


class PreferenceRecord(TypedDict):
    objetivo: Objective
    strategy_id: StrategyId
    valor: PreferenceValue
    updated_revision: int
    contexto_explicativo: dict[str, str | int | float | bool]


class DecisionContext(TypedDict):
    hora: NotRequired[int]
    preset: PresetName
    modo: Literal["cognitivo"]
    faixa_horario: Literal["madrugada", "amanhecer", "dia", "noite"]
    dormir: Binary
    faixa_temperatura: Literal["frio", "conforto", "calor"]
    luminosidade: Luminosity
    presenca_interna: Binary


class CorrectionCommand(TypedDict):
    rota: str
    dispositivo: DeviceName
    comando: Binary


class DecisionSnapshot(TypedDict):
    decisao_id: str
    objetivo: Objective
    strategy_id: StrategyId
    modo: Mode
    status: Literal["prevista", "confirmada", "invalidada"]
    influenciada: bool
    alternativas: list[dict[str, object]]
    plano: list[dict[str, object]]
    contexto: NotRequired[DecisionContext]
    correcoes_permitidas: NotRequired[list[CorrectionCommand]]


class ThermalDeviceVector(TypedDict):
    janela: Binary
    ar: Binary
    ventilador: Binary


class EpisodeState(TypedDict):
    episode_id: str
    run_id: str
    decisao_id: str
    objetivo: Objective
    estrategia_sugerida: StrategyId
    vetor_inicial: ThermalDeviceVector
    comandos: list[dict[str, object]]
    vetor_final: ThermalDeviceVector | None
    estrategia_corrigida: StrategyId | None
    status: Literal["aberto", "fechado", "cancelado"]


class CycleMetrics(TypedDict):
    cycle_id: str
    run_id: str
    numero_ciclo: int
    temperatura_projetada: float
    conforto: float
    custo_energetico: float
    economia: float
    ajuste_preferencia: float
    strategy_id: StrategyId
    seguranca: Literal["seguro", "prevencao", "incidente"]
    bloqueios: list[str]
    incidentes: list[str]
    feedback: FeedbackType | None


class RunSummary(TypedDict):
    run_id: str
    ciclos: int
    custo_energetico_total: float
    custo_energetico_medio: float | None
    conforto_acumulado: float
    conforto_medio: float | None
    ciclos_seguros: int
    prevencoes: int
    incidentes: int
    aceitacoes: int
    correcoes: int
    feedbacks_observados: int
    satisfacao_acumulada: float
    satisfacao_observada: float | None


class ExecutionState(TypedDict):
    pausada: bool


class ComputationState(TypedDict):
    revision: int
    fisico: PhysicalState
    dispositivos: DeviceVector
    preferencias: list[PreferenceRecord]
    decisao: DecisionSnapshot | None
    episodio_aberto: EpisodeState | None
    execucao: ExecutionState
    metricas: list[CycleMetrics]
    resumo: RunSummary


class TraceEvent(TypedDict):
    event_id: str
    run_id: str
    ordem: int
    tipo: Literal[
        "cycle",
        "environment",
        "manual_command",
        "feedback",
        "episode",
        "reset",
        "run",
    ]
    operation_id: str
    decisao_id: str | None
    comando_id: str | None
    dados: dict[str, object]


class FullSnapshot(IdentityRef):
    schema_version: SchemaVersion
    revision: int
    next_trace_order: int
    pruned_before: int
    run_id: str
    computation: ComputationState
    cycle_metrics: list[CycleMetrics]
    trace: list[TraceEvent]


class CyclePayload(TypedDict):
    kind: Literal["cycle"]
    mode: Mode


class EnvironmentPayload(TypedDict):
    kind: Literal["environment"]
    hora: int
    temperatura_externa: float
    umidade: float
    chuva: Binary
    presenca_interna: Binary
    presenca_externa: Binary
    dormir: Binary


class ManualCommandPayload(TypedDict):
    kind: Literal["manual_command"]
    device: DeviceName
    command: Binary
    decisao_id: str | None


class FeedbackPayload(TypedDict):
    kind: Literal["feedback"]
    decisao_id: str
    tipo: FeedbackType
    comando_id: str | None


class PresetPayload(TypedDict):
    kind: Literal["preset"]
    preset: PresetName


class PausePayload(TypedDict):
    kind: Literal["pause"]


class ResumePayload(TypedDict):
    kind: Literal["resume"]


class NewRunPayload(TypedDict):
    kind: Literal["new_run"]


class ResetPayload(TypedDict):
    kind: Literal["reset"]


CompactPayload: TypeAlias = (
    CyclePayload
    | EnvironmentPayload
    | ManualCommandPayload
    | FeedbackPayload
    | PresetPayload
    | PausePayload
    | ResumePayload
    | NewRunPayload
    | ResetPayload
)


class TransitionRequest(TypedDict):
    schema_version: SchemaVersion
    identity_id: str
    identity_generation: int
    base_revision: int
    operation_id: str
    payload_hash: str
    operation: MutationOperationKind
    computation: ComputationState
    payload: CompactPayload


class SnapshotRequest(TypedDict):
    schema_version: SchemaVersion
    identity_id: str
    identity_generation: int
    operation_id: str
    payload_hash: str
    purpose: Literal[
        "bootstrap",
        "recovery",
        "emergency_sync",
        "reset",
        "new_run",
    ]
    snapshot: FullSnapshot


class SnapshotSuccess(TypedDict):
    status: Literal["success"]
    schema_version: SchemaVersion
    identity_id: str
    identity_generation: int
    operation_id: str
    payload_hash: str
    revision: int
    snapshot: FullSnapshot


class TransitionSuccess(TypedDict):
    status: Literal["success"]
    schema_version: SchemaVersion
    identity_id: str
    identity_generation: int
    operation_id: str
    payload_hash: str
    base_revision: int
    new_revision: int
    operation: MutationOperationKind
    computation: ComputationState
    events: list[TraceEvent]
    snapshot: FullSnapshot | None


class TransitionError(TypedDict):
    status: Literal["error"]
    schema_version: SchemaVersion
    code: ErrorCode
    http_status: ErrorHttpStatus
    message: str
    fields: list[str]
    operation_id: str | None
    received_revision: int | None
    current_revision: int | None
    snapshot: FullSnapshot | None


ProtocolResponse: TypeAlias = TransitionSuccess | SnapshotSuccess | TransitionError


class OperationRecord(TypedDict):
    operation_key: str
    identity_id: str
    identity_generation: int
    operation_id: str
    payload_hash: str
    base_revision: int
    operation: OperationKind
    status: OperationStatus
    attempts: int
    response: ProtocolResponse | None


_IDENTITY_FIELDS: Final[frozenset[str]] = frozenset(
    {"identity_id", "identity_generation"}
)
_PHYSICAL_STATE_FIELDS: Final[frozenset[str]] = frozenset(
    {
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
    }
)
_DEVICE_VECTOR_FIELDS: Final[frozenset[str]] = frozenset(
    {"janela", "ar", "ventilador", "umidificador", "lampada"}
)
_PRESET_NAMES: Final[tuple[PresetName, ...]] = ("calor", "frio", "conforto")
_LUMINOSITIES: Final[tuple[Luminosity, ...]] = ("escuro", "adequado", "claro")
_OPERATION_KINDS: Final[tuple[OperationKind, ...]] = (
    "cycle",
    "environment",
    "manual_command",
    "feedback",
    "preset",
    "pause",
    "resume",
    "new_run",
    "reset",
    "checkpoint",
)
_OPERATION_STATUSES: Final[tuple[OperationStatus, ...]] = (
    "pending",
    "sent",
    "accepted",
    "persisted",
    "retryable",
    "failed",
    "timeout",
    "unknown",
)
_ERROR_CODES: Final[tuple[ErrorCode, ...]] = (
    "invalid_json",
    "schema_unsupported",
    "invalid_payload",
    "identity_mismatch",
    "stale_revision",
    "operation_conflict",
    "operation_in_flight",
    "unsafe_action",
    "invalid_state",
    "not_found",
    "internal_error",
)


class ProtocolValidationError(ValueError):
    pass


def _object_with_fields(
    value: object,
    fields: frozenset[str],
    contract_name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProtocolValidationError(f"{contract_name} must be an object.")
    if set(value) != fields:
        raise ProtocolValidationError(f"{contract_name} has incompatible fields.")
    return cast(Mapping[str, object], value)


def _object_with_optional_fields(
    value: object,
    required_fields: frozenset[str],
    optional_fields: frozenset[str],
    contract_name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProtocolValidationError(f"{contract_name} must be an object.")
    actual_fields = set(value)
    if not required_fields.issubset(actual_fields) or not actual_fields.issubset(
        required_fields | optional_fields
    ):
        raise ProtocolValidationError(f"{contract_name} has incompatible fields.")
    return cast(Mapping[str, object], value)


def _binary(value: object, field_name: str) -> Binary:
    if type(value) is not int or value not in (0, 1):
        raise ProtocolValidationError(f"{field_name} must be 0 or 1.")
    return cast(Binary, value)


def _bounded_number(
    value: object,
    field_name: str,
    minimum: float,
    maximum: float,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not isfinite(value))
        or value < minimum
        or value > maximum
    ):
        raise ProtocolValidationError(
            f"{field_name} must be between {minimum:g} and {maximum:g}."
        )
    return cast(float, value)


def validate_identity_ref(value: object) -> IdentityRef:
    fields = _object_with_fields(value, _IDENTITY_FIELDS, "IdentityRef")
    identity_id = _validate_identifier(
        fields["identity_id"], "identity_id", MAX_IDENTITY_ID_LENGTH
    )
    identity_generation = fields["identity_generation"]
    if type(identity_generation) is not int or identity_generation < 0:
        raise ProtocolValidationError(
            "identity_generation must be a non-negative integer."
        )
    return {
        "identity_id": identity_id,
        "identity_generation": identity_generation,
    }


def validate_device_vector(value: object) -> DeviceVector:
    fields = _object_with_fields(value, _DEVICE_VECTOR_FIELDS, "DeviceVector")
    devices: DeviceVector = {
        "janela": _binary(fields["janela"], "janela"),
        "ar": _binary(fields["ar"], "ar"),
        "ventilador": _binary(fields["ventilador"], "ventilador"),
        "umidificador": _binary(fields["umidificador"], "umidificador"),
        "lampada": _binary(fields["lampada"], "lampada"),
    }
    if devices["janela"] == 1 and devices["ar"] == 1:
        raise ProtocolValidationError("janela and ar cannot both be active.")
    return devices


def validate_physical_state(value: object) -> PhysicalState:
    fields = _object_with_fields(value, _PHYSICAL_STATE_FIELDS, "PhysicalState")
    preset = fields["preset_atual"]
    if preset is not None and preset not in _PRESET_NAMES:
        raise ProtocolValidationError("preset_atual is not a supported preset.")

    hour = fields["hora"]
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ProtocolValidationError("hora must be an integer between 0 and 23.")

    luminosity = fields["luminosidade"]
    if not isinstance(luminosity, str) or luminosity not in _LUMINOSITIES:
        raise ProtocolValidationError("luminosidade is not a supported value.")

    return {
        "preset_atual": cast(PresetName | None, preset),
        "hora": hour,
        "temperatura_externa": _bounded_number(
            fields["temperatura_externa"], "temperatura_externa", 10, 38
        ),
        "temperatura_interna": _bounded_number(
            fields["temperatura_interna"], "temperatura_interna", 10, 38
        ),
        "umidade": _bounded_number(fields["umidade"], "umidade", 0, 100),
        "luminosidade": cast(Luminosity, luminosity),
        "chuva": _binary(fields["chuva"], "chuva"),
        "presenca_interna": _binary(fields["presenca_interna"], "presenca_interna"),
        "presenca_externa": _binary(fields["presenca_externa"], "presenca_externa"),
        "dormir": _binary(fields["dormir"], "dormir"),
    }


def _validate_string_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ProtocolValidationError(f"{field_name} must be an object with string keys.")
    return cast(Mapping[str, object], value)


def _validate_record_list(
    value: object,
    field_name: str,
) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise ProtocolValidationError(f"{field_name} must be a list.")
    return [
        _validate_string_mapping(item, f"{field_name} item")
        for item in value
    ]


def _validate_preference_record(value: object, revision: int) -> None:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "objetivo",
                "strategy_id",
                "valor",
                "updated_revision",
                "contexto_explicativo",
            }
        ),
        "PreferenceRecord",
    )
    if fields["objetivo"] not in (
        "seguranca",
        "umidade",
        "termico",
        "iluminacao",
        "manutencao",
    ):
        raise ProtocolValidationError("preference objective is not supported.")
    if fields["strategy_id"] not in (
        "manter",
        "ventilacao_natural",
        "ventilacao_assistida",
        "circulacao_interna",
        "resfriamento",
        "resfriamento_assistido",
        "umidificacao",
        "iluminacao",
    ):
        raise ProtocolValidationError("preference strategy is not supported.")
    preference_value = fields["valor"]
    if type(preference_value) is not int or preference_value not in (-3, -2, -1, 0, 1, 2, 3):
        raise ProtocolValidationError("preference value must be between -3 and 3.")
    updated_revision = validate_revision(fields["updated_revision"], "updated_revision")
    if updated_revision > revision:
        raise ProtocolValidationError("updated_revision cannot exceed computation revision.")
    context = _validate_string_mapping(
        fields["contexto_explicativo"], "contexto_explicativo"
    )
    for context_value in context.values():
        if isinstance(context_value, bool) or isinstance(context_value, str):
            continue
        if type(context_value) is int:
            continue
        if isinstance(context_value, float) and isfinite(context_value):
            continue
        raise ProtocolValidationError("contexto_explicativo values must be finite scalars.")


def _validate_decision_snapshot(value: object) -> None:
    required_fields = frozenset(
        {
            "decisao_id",
            "objetivo",
            "strategy_id",
            "modo",
            "status",
            "influenciada",
            "alternativas",
            "plano",
        }
    )
    optional_fields = frozenset({"contexto", "correcoes_permitidas"})
    fields = _object_with_optional_fields(
        value,
        required_fields,
        optional_fields,
        "DecisionSnapshot",
    )
    validate_payload_hash(fields["decisao_id"])
    if fields["objetivo"] not in (
        "seguranca",
        "umidade",
        "termico",
        "iluminacao",
        "manutencao",
    ):
        raise ProtocolValidationError("decision objective is not supported.")
    if fields["strategy_id"] not in (
        "manter",
        "ventilacao_natural",
        "ventilacao_assistida",
        "circulacao_interna",
        "resfriamento",
        "resfriamento_assistido",
        "umidificacao",
        "iluminacao",
    ):
        raise ProtocolValidationError("decision strategy is not supported.")
    if fields["modo"] not in ("reativo", "cognitivo"):
        raise ProtocolValidationError("decision mode is not supported.")
    if fields["status"] not in ("prevista", "confirmada", "invalidada"):
        raise ProtocolValidationError("decision status is not supported.")
    if type(fields["influenciada"]) is not bool:
        raise ProtocolValidationError("influenciada must be a boolean.")
    for field_name in ("alternativas", "plano"):
        _validate_record_list(fields[field_name], field_name)
    if "contexto" in fields:
        if fields["modo"] != "cognitivo":
            raise ProtocolValidationError("only cognitive decisions carry context.")
        _validate_decision_context(fields["contexto"])
    if "correcoes_permitidas" in fields:
        corrections = fields["correcoes_permitidas"]
        if not isinstance(corrections, list):
            raise ProtocolValidationError("correcoes_permitidas must be a list.")
        for correction in corrections:
            command = _object_with_fields(
                correction,
                frozenset({"rota", "dispositivo", "comando"}),
                "CorrectionCommand",
            )
            if not isinstance(command["rota"], str) or not command["rota"]:
                raise ProtocolValidationError("correction route must be a string.")
            if command["dispositivo"] not in (
                "janela",
                "ar",
                "ventilador",
                "umidificador",
                "lampada",
            ):
                raise ProtocolValidationError("correction device is not supported.")
            _binary(command["comando"], "correction command")


def _validate_decision_context(value: object) -> None:
    fields = _object_with_optional_fields(
        value,
        frozenset(
            {
                "preset",
                "modo",
                "faixa_horario",
                "dormir",
                "faixa_temperatura",
                "luminosidade",
                "presenca_interna",
            }
        ),
        frozenset({"hora"}),
        "DecisionContext",
    )
    if fields["preset"] not in ("calor", "frio", "conforto"):
        raise ProtocolValidationError("decision context preset is not supported.")
    if fields["modo"] != "cognitivo":
        raise ProtocolValidationError("decision context mode is not supported.")
    if fields["faixa_horario"] not in ("madrugada", "amanhecer", "dia", "noite"):
        raise ProtocolValidationError("decision context time band is not supported.")
    _binary(fields["dormir"], "contexto.dormir")
    if fields["faixa_temperatura"] not in ("frio", "conforto", "calor"):
        raise ProtocolValidationError("decision context temperature band is not supported.")
    if fields["luminosidade"] not in ("escuro", "adequado", "claro"):
        raise ProtocolValidationError("decision context luminosity is not supported.")
    _binary(fields["presenca_interna"], "contexto.presenca_interna")
    if "hora" in fields:
        hour = fields["hora"]
        if type(hour) is not int or not 0 <= hour <= 23:
            raise ProtocolValidationError("decision context hour is invalid.")


def _validate_thermal_device_vector(value: object) -> None:
    fields = _object_with_fields(
        value,
        frozenset({"janela", "ar", "ventilador"}),
        "ThermalDeviceVector",
    )
    for field_name in ("janela", "ar", "ventilador"):
        _binary(fields[field_name], field_name)


def _validate_episode_state(
    value: object,
    expected_run_id: str | None,
) -> None:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "episode_id",
                "run_id",
                "decisao_id",
                "objetivo",
                "estrategia_sugerida",
                "vetor_inicial",
                "comandos",
                "vetor_final",
                "estrategia_corrigida",
                "status",
            }
        ),
        "EpisodeState",
    )
    validate_payload_hash(fields["episode_id"])
    run_id = _validate_identifier(fields["run_id"], "run_id", MAX_OPERATION_ID_LENGTH)
    if expected_run_id is not None and run_id != expected_run_id:
        raise ProtocolValidationError("episode run_id does not match computation.")
    validate_payload_hash(fields["decisao_id"])
    if fields["objetivo"] not in (
        "seguranca",
        "umidade",
        "termico",
        "iluminacao",
        "manutencao",
    ):
        raise ProtocolValidationError("episode objective is not supported.")
    strategies = (
        "manter",
        "ventilacao_natural",
        "ventilacao_assistida",
        "circulacao_interna",
        "resfriamento",
        "resfriamento_assistido",
        "umidificacao",
        "iluminacao",
    )
    if fields["estrategia_sugerida"] not in strategies:
        raise ProtocolValidationError("suggested episode strategy is not supported.")
    _validate_thermal_device_vector(fields["vetor_inicial"])
    _validate_record_list(fields["comandos"], "comandos")
    final_vector = fields["vetor_final"]
    if final_vector is not None:
        _validate_thermal_device_vector(final_vector)
    corrected_strategy = fields["estrategia_corrigida"]
    if corrected_strategy is not None and corrected_strategy not in strategies:
        raise ProtocolValidationError("corrected episode strategy is not supported.")
    if fields["status"] not in ("aberto", "fechado", "cancelado"):
        raise ProtocolValidationError("episode status is not supported.")


def _validate_cycle_metrics(value: object, expected_run_id: str | None) -> None:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "cycle_id",
                "run_id",
                "numero_ciclo",
                "temperatura_projetada",
                "conforto",
                "custo_energetico",
                "economia",
                "ajuste_preferencia",
                "strategy_id",
                "seguranca",
                "bloqueios",
                "incidentes",
                "feedback",
            }
        ),
        "CycleMetrics",
    )
    _validate_identifier(fields["cycle_id"], "cycle_id", MAX_OPERATION_ID_LENGTH)
    run_id = _validate_identifier(fields["run_id"], "run_id", MAX_OPERATION_ID_LENGTH)
    if expected_run_id is not None and run_id != expected_run_id:
        raise ProtocolValidationError("cycle metric run_id does not match computation.")
    validate_revision(fields["numero_ciclo"], "numero_ciclo")
    for field_name in (
        "temperatura_projetada",
        "conforto",
        "custo_energetico",
        "economia",
        "ajuste_preferencia",
    ):
        _bounded_number(fields[field_name], field_name, float("-inf"), float("inf"))
    if fields["strategy_id"] not in (
        "manter",
        "ventilacao_natural",
        "ventilacao_assistida",
        "circulacao_interna",
        "resfriamento",
        "resfriamento_assistido",
        "umidificacao",
        "iluminacao",
    ):
        raise ProtocolValidationError("cycle metric strategy is not supported.")
    if fields["seguranca"] not in ("seguro", "prevencao", "incidente"):
        raise ProtocolValidationError("cycle metric safety status is not supported.")
    for field_name in ("bloqueios", "incidentes"):
        values = fields[field_name]
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ProtocolValidationError(f"{field_name} must be a list of strings.")
    feedback = fields["feedback"]
    if feedback is not None and feedback not in ("aceitar", "rejeitar", "corrigir"):
        raise ProtocolValidationError("cycle metric feedback is not supported.")


def _validate_computation_state(
    value: object,
    expected_revision: int,
    expected_run_id: str | None = None,
) -> None:
    computation = _object_with_fields(
        value,
        frozenset(
            {
                "revision",
                "fisico",
                "dispositivos",
                "preferencias",
                "decisao",
                "episodio_aberto",
                "execucao",
                "metricas",
                "resumo",
            }
        ),
        "ComputationState",
    )
    if validate_revision(computation["revision"]) != expected_revision:
        raise ProtocolValidationError("computation revision does not match response.")
    validate_physical_state(computation["fisico"])
    validate_device_vector(computation["dispositivos"])
    preferences = computation["preferencias"]
    if not isinstance(preferences, list):
        raise ProtocolValidationError("preferencias must be a list.")
    for preference in preferences:
        _validate_preference_record(preference, expected_revision)
    decision = computation["decisao"]
    if decision is not None:
        _validate_decision_snapshot(decision)
    episode = computation["episodio_aberto"]
    if episode is not None:
        _validate_episode_state(episode, expected_run_id)
    execution = _object_with_fields(
        computation["execucao"], frozenset({"pausada"}), "ExecutionState"
    )
    if type(execution["pausada"]) is not bool:
        raise ProtocolValidationError("pausada must be a boolean.")
    metrics = computation["metricas"]
    if not isinstance(metrics, list):
        raise ProtocolValidationError("metricas must be a list.")
    if len(metrics) > 1:
        raise ProtocolValidationError("computation.metricas may contain only the latest cycle metric.")
    for metric in metrics:
        _validate_cycle_metrics(metric, expected_run_id)
    summary = _object_with_fields(
        computation["resumo"],
        frozenset(
            {
                "run_id",
                "ciclos",
                "custo_energetico_total",
                "custo_energetico_medio",
                "conforto_acumulado",
                "conforto_medio",
                "ciclos_seguros",
                "prevencoes",
                "incidentes",
                "aceitacoes",
                "correcoes",
                "feedbacks_observados",
                "satisfacao_acumulada",
                "satisfacao_observada",
            }
        ),
        "RunSummary",
    )
    summary_run_id = _validate_identifier(
        summary["run_id"], "run_id", MAX_OPERATION_ID_LENGTH
    )
    if expected_run_id is not None and summary_run_id != expected_run_id:
        raise ProtocolValidationError("snapshot and summary run IDs differ.")
    for counter_name in (
        "ciclos",
        "ciclos_seguros",
        "prevencoes",
        "incidentes",
        "aceitacoes",
        "correcoes",
        "feedbacks_observados",
    ):
        validate_revision(summary[counter_name], counter_name)
    for metric_name in (
        "custo_energetico_total",
        "custo_energetico_medio",
        "conforto_acumulado",
        "conforto_medio",
        "satisfacao_acumulada",
        "satisfacao_observada",
    ):
        metric = summary[metric_name]
        if metric is not None:
            _bounded_number(metric, metric_name, 0, float("inf"))


def validate_computation_state(
    value: object,
    expected_revision: int,
    expected_run_id: str | None = None,
) -> ComputationState:
    _validate_computation_state(value, expected_revision, expected_run_id)
    return cast(ComputationState, dict(cast(Mapping[str, object], value)))


def _validate_trace_event(
    value: object,
    previous_order: int,
    expected_run_id: str | None = None,
) -> int:
    event = _object_with_fields(
        value,
        frozenset(
            {
                "event_id",
                "run_id",
                "ordem",
                "tipo",
                "operation_id",
                "decisao_id",
                "comando_id",
                "dados",
            }
        ),
        "TraceEvent",
    )
    validate_payload_hash(event["event_id"])
    run_id = _validate_identifier(event["run_id"], "run_id", MAX_OPERATION_ID_LENGTH)
    if expected_run_id is not None and run_id != expected_run_id:
        raise ProtocolValidationError("trace event run_id does not match snapshot.")
    order = validate_revision(event["ordem"], "ordem")
    if order <= previous_order:
        raise ProtocolValidationError("trace events must be in increasing order.")
    validate_operation_id(event["operation_id"])
    if event["tipo"] not in (
        "cycle",
        "environment",
        "manual_command",
        "feedback",
        "episode",
        "reset",
        "run",
    ):
        raise ProtocolValidationError("trace event type is not supported.")
    for related_id in ("decisao_id", "comando_id"):
        related_value = event[related_id]
        if related_value is not None:
            validate_payload_hash(related_value)
    _validate_string_mapping(event["dados"], "trace event data")
    return order


def validate_full_snapshot(value: object) -> FullSnapshot:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "schema_version",
                "identity_id",
                "identity_generation",
                "revision",
                "next_trace_order",
                "pruned_before",
                "run_id",
                "computation",
                "cycle_metrics",
                "trace",
            }
        ),
        "FullSnapshot",
    )
    identity = validate_identity_ref(
        {
            "identity_id": fields["identity_id"],
            "identity_generation": fields["identity_generation"],
        }
    )
    validate_schema_version(fields["schema_version"])
    revision = validate_revision(fields["revision"])
    next_trace_order = validate_revision(fields["next_trace_order"], "next_trace_order")
    pruned_before = validate_revision(fields["pruned_before"], "pruned_before")
    run_id = _validate_identifier(fields["run_id"], "run_id", MAX_OPERATION_ID_LENGTH)

    _validate_computation_state(fields["computation"], revision, run_id)

    trace = fields["trace"]
    if not isinstance(trace, list):
        raise ProtocolValidationError("trace must be a list.")
    cycle_metrics = fields["cycle_metrics"]
    if not isinstance(cycle_metrics, list) or len(cycle_metrics) > MAX_CYCLE_HISTORY:
        raise ProtocolValidationError("cycle_metrics exceeds the supported history limit.")
    for expected_cycle, metric in enumerate(cycle_metrics, start=1):
        _validate_cycle_metrics(metric, run_id)
        if metric["numero_ciclo"] != expected_cycle:
            raise ProtocolValidationError("cycle_metrics must retain every cycle in order.")
    computation = cast(Mapping[str, object], fields["computation"])
    summary = cast(Mapping[str, object], computation["resumo"])
    if len(cycle_metrics) != summary["ciclos"]:
        raise ProtocolValidationError("cycle_metrics must contain the complete run history.")
    if cycle_metrics:
        latest_metric = computation["metricas"]
        if latest_metric != [cycle_metrics[-1]]:
            raise ProtocolValidationError("computation.metricas must match the latest cycle metric.")
    elif computation["metricas"]:
        raise ProtocolValidationError("computation.metricas cannot exist without cycle history.")
    previous_order = pruned_before
    for event_value in trace:
        previous_order = _validate_trace_event(event_value, previous_order, run_id)
    if next_trace_order <= previous_order:
        raise ProtocolValidationError("next_trace_order must follow retained events.")

    return cast(FullSnapshot, dict(fields))


def _validate_identifier(value: object, field_name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
    ):
        raise ProtocolValidationError(
            f"{field_name} must contain between 1 and {maximum} characters."
        )
    return value


def validate_schema_version(value: object) -> SchemaVersion:
    if type(value) is not int or value != 1:
        raise ProtocolValidationError("schema_version is not supported.")
    return cast(SchemaVersion, value)


def validate_revision(value: object, field_name: str = "revision") -> int:
    if type(value) is not int or value < 0:
        raise ProtocolValidationError(f"{field_name} must be a non-negative integer.")
    return value


def validate_operation_id(value: object) -> str:
    return _validate_identifier(value, "operation_id", MAX_OPERATION_ID_LENGTH)


def validate_payload_hash(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ProtocolValidationError("payload_hash must be 64 hexadecimal characters.")
    return value


def validate_transition_error(value: object) -> TransitionError:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "status",
                "schema_version",
                "code",
                "http_status",
                "message",
                "fields",
                "operation_id",
                "received_revision",
                "current_revision",
                "snapshot",
            }
        ),
        "TransitionError",
    )
    code = fields["code"]
    if not isinstance(code, str) or code not in _ERROR_CODES:
        raise ProtocolValidationError("code is not a supported error code.")
    typed_code = cast(ErrorCode, code)
    status = fields["http_status"]
    if type(status) is not int or status != ERROR_HTTP_STATUS[typed_code]:
        raise ProtocolValidationError("http_status does not match code.")
    message = fields["message"]
    rejected_fields = fields["fields"]
    if not isinstance(message, str) or not message.strip():
        raise ProtocolValidationError("message must be a non-empty string.")
    if not isinstance(rejected_fields, list) or not all(
        isinstance(field, str) for field in rejected_fields
    ):
        raise ProtocolValidationError("fields must be a list of strings.")
    operation_id = fields["operation_id"]
    if operation_id is not None:
        validate_operation_id(operation_id)
    received_revision = fields["received_revision"]
    if received_revision is not None:
        validate_revision(received_revision, "received_revision")
    current_revision = fields["current_revision"]
    if current_revision is not None:
        validate_revision(current_revision, "current_revision")
    if fields["status"] != "error":
        raise ProtocolValidationError("status must be error.")
    validate_schema_version(fields["schema_version"])
    snapshot = fields["snapshot"]
    if snapshot is not None:
        validate_full_snapshot(snapshot)
    return cast(TransitionError, dict(fields))


def validate_snapshot_success(value: object) -> SnapshotSuccess:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "status",
                "schema_version",
                "identity_id",
                "identity_generation",
                "operation_id",
                "payload_hash",
                "revision",
                "snapshot",
            }
        ),
        "SnapshotSuccess",
    )
    if fields["status"] != "success":
        raise ProtocolValidationError("status must be success.")
    validate_schema_version(fields["schema_version"])
    identity = validate_identity_ref(
        {
            "identity_id": fields["identity_id"],
            "identity_generation": fields["identity_generation"],
        }
    )
    validate_operation_id(fields["operation_id"])
    validate_payload_hash(fields["payload_hash"])
    revision = validate_revision(fields["revision"])
    snapshot = validate_full_snapshot(fields["snapshot"])
    if (
        identity["identity_id"] != snapshot["identity_id"]
        or identity["identity_generation"] != snapshot["identity_generation"]
        or revision != snapshot["revision"]
    ):
        raise ProtocolValidationError("snapshot success does not match its snapshot.")
    return cast(SnapshotSuccess, dict(fields))


def validate_transition_success(value: object) -> TransitionSuccess:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "status",
                "schema_version",
                "identity_id",
                "identity_generation",
                "operation_id",
                "payload_hash",
                "base_revision",
                "new_revision",
                "operation",
                "computation",
                "events",
                "snapshot",
            }
        ),
        "TransitionSuccess",
    )
    if fields["status"] != "success":
        raise ProtocolValidationError("status must be success.")
    validate_schema_version(fields["schema_version"])
    validate_identity_ref(
        {
            "identity_id": fields["identity_id"],
            "identity_generation": fields["identity_generation"],
        }
    )
    validate_operation_id(fields["operation_id"])
    validate_payload_hash(fields["payload_hash"])
    base_revision = validate_revision(fields["base_revision"], "base_revision")
    new_revision = validate_revision(fields["new_revision"], "new_revision")
    if new_revision != base_revision + 1:
        raise ProtocolValidationError("new_revision must equal base_revision + 1.")
    if fields["operation"] not in _OPERATION_KINDS[:-1]:
        raise ProtocolValidationError("operation is not a mutation operation.")
    _validate_computation_state(fields["computation"], new_revision)
    events = fields["events"]
    if not isinstance(events, list):
        raise ProtocolValidationError("events must be a list.")
    previous_order = 0
    for event_value in events:
        previous_order = _validate_trace_event(event_value, previous_order)
    snapshot = fields["snapshot"]
    if snapshot is not None:
        validated_snapshot = validate_full_snapshot(snapshot)
        if validated_snapshot["revision"] != new_revision:
            raise ProtocolValidationError("response snapshot revision is incorrect.")
    return cast(TransitionSuccess, dict(fields))


def validate_operation_record(value: object) -> OperationRecord:
    fields = _object_with_fields(
        value,
        frozenset(
            {
                "operation_key",
                "identity_id",
                "identity_generation",
                "operation_id",
                "payload_hash",
                "base_revision",
                "operation",
                "status",
                "attempts",
                "response",
            }
        ),
        "OperationRecord",
    )
    identity = validate_identity_ref(
        {
            "identity_id": fields["identity_id"],
            "identity_generation": fields["identity_generation"],
        }
    )
    operation_id = validate_operation_id(fields["operation_id"])
    if fields["operation_key"] != f"{identity['identity_id']}:{operation_id}":
        raise ProtocolValidationError("operation_key does not match its identity.")
    validate_payload_hash(fields["payload_hash"])
    validate_revision(fields["base_revision"], "base_revision")
    if fields["operation"] not in _OPERATION_KINDS:
        raise ProtocolValidationError("operation is not supported.")
    if fields["status"] not in _OPERATION_STATUSES:
        raise ProtocolValidationError("status is not a supported operation status.")
    attempts = fields["attempts"]
    if type(attempts) is not int or attempts < 0:
        raise ProtocolValidationError("attempts must be a non-negative integer.")
    response = fields["response"]
    if response is not None:
        if not isinstance(response, Mapping):
            raise ProtocolValidationError("response must be an object or null.")
        response_status = response.get("status")
        if response_status == "error":
            validate_transition_error(response)
        elif response_status == "success":
            if "new_revision" in response:
                validate_transition_success(response)
            else:
                validate_snapshot_success(response)
        else:
            raise ProtocolValidationError("response has an unsupported status.")
    return cast(OperationRecord, dict(fields))


def _canonical_json_value(value: object) -> object:
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ProtocolValidationError("JSON numbers must be finite.")
        return value
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ProtocolValidationError("JSON strings must be valid UTF-8.") from error
        return value
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ProtocolValidationError("JSON object keys must be strings.")
        sorted_keys = sorted(cast(list[str], list(value.keys())), key=str.encode)
        return {
            key: _canonical_json_value(value[key])
            for key in sorted_keys
        }
    raise ProtocolValidationError("Value is not representable as JSON.")


def canonical_json_bytes(value: object) -> bytes:
    canonical_value = _canonical_json_value(value)
    try:
        serialized = json.dumps(
            canonical_value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        return serialized.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ProtocolValidationError("Value is not representable as canonical JSON.") from error


def canonicalize_payload(envelope: Mapping[str, object]) -> bytes:
    payload = {key: value for key, value in envelope.items() if key != "payload_hash"}
    return canonical_json_bytes(payload)


def compute_payload_hash(envelope: Mapping[str, object]) -> str:
    return sha256(canonicalize_payload(envelope)).hexdigest()


def derive_deterministic_id(
    identity_generation: int,
    base_revision: int,
    operation_id: str,
    ordinal: int,
) -> str:
    validate_revision(identity_generation, "identity_generation")
    validate_revision(base_revision, "base_revision")
    validate_operation_id(operation_id)
    validate_revision(ordinal, "ordinal")
    return sha256(
        canonical_json_bytes(
            {
                "identity_generation": identity_generation,
                "base_revision": base_revision,
                "operation_id": operation_id,
                "ordinal": ordinal,
            }
        )
    ).hexdigest()
