"""Estado autoritativo e cenários determinísticos do simulador do quarto."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from copy import deepcopy
from typing import Final, Literal, TypeAlias, TypedDict, cast


Binary: TypeAlias = Literal[0, 1]
Luminosity: TypeAlias = Literal["escuro", "adequado", "claro"]
Mode: TypeAlias = Literal["reativo", "cognitivo"]
PresetName: TypeAlias = Literal["calor", "frio", "conforto"]
TraceEventType: TypeAlias = Literal[
    "preset",
    "ciclo",
    "feedback",
    "correcao",
    "reset",
    "invalidacao",
]

_TRACE_EVENT_TYPES: Final[tuple[TraceEventType, ...]] = (
    "preset",
    "ciclo",
    "feedback",
    "correcao",
    "reset",
    "invalidacao",
)


class PresetDevices(TypedDict):
    """Estados binários dos dispositivos fornecidos por um preset."""

    janela: Binary
    ar: Binary
    ventilador: Binary
    umidificador: Binary
    lampada: Binary


class PresetState(TypedDict):
    """Parte ambiental e de dispositivos de um cenário determinístico."""

    hora: int
    temperatura_externa: float
    temperatura_interna: float
    umidade: float
    chuva: Binary
    presenca_interna: Binary
    presenca_externa: Binary
    dormir: Binary
    dispositivos: PresetDevices


class AutomaticExecutionState(TypedDict):
    """Estado efêmero da execução automática do simulador."""

    pausada: bool


class TraceEvent(TypedDict):
    """Evento ordenado do rastro autoritativo da sessão."""

    ordem: int
    tipo: TraceEventType
    decisao_id: str | None
    comando_id: str | None
    dados: dict[str, object]


class RoomState(TypedDict):
    """Estado em memória do ambiente, da decisão e da execução."""

    preset_atual: PresetName | None
    revisao_estado: int
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
    ultima_acao_confirmada: str | None
    decisao: dict[str, object] | None
    etapas: list[dict[str, object]]
    preferencias: dict[Hashable, int]
    feedbacks: list[object]
    rastro: list[TraceEvent]
    decisao_pendente: dict[str, object] | None
    execucao_automatica: AutomaticExecutionState


class PresetError(ValueError):
    """Erro levantado quando um preset solicitado não é conhecido."""


class TraceError(ValueError):
    """Erro levantado quando o rastro viola seu contrato autoritativo."""


PRESETS: Final[dict[PresetName, PresetState]] = {
    "calor": {
        "hora": 14,
        "temperatura_externa": 35,
        "temperatura_interna": 30,
        "umidade": 50,
        "chuva": 0,
        "presenca_interna": 1,
        "presenca_externa": 0,
        "dormir": 0,
        "dispositivos": {
            "janela": 1,
            "ar": 0,
            "ventilador": 0,
            "umidificador": 0,
            "lampada": 0,
        },
    },
    "frio": {
        "hora": 3,
        "temperatura_externa": 15,
        "temperatura_interna": 18,
        "umidade": 50,
        "chuva": 0,
        "presenca_interna": 1,
        "presenca_externa": 0,
        "dormir": 1,
        "dispositivos": {
            "janela": 1,
            "ar": 0,
            "ventilador": 0,
            "umidificador": 0,
            "lampada": 0,
        },
    },
    "conforto": {
        "hora": 10,
        "temperatura_externa": 24,
        "temperatura_interna": 24,
        "umidade": 50,
        "chuva": 0,
        "presenca_interna": 1,
        "presenca_externa": 0,
        "dormir": 0,
        "dispositivos": {
            "janela": 0,
            "ar": 0,
            "ventilador": 0,
            "umidificador": 0,
            "lampada": 0,
        },
    },
}

_PRESET_LUMINOSITY: Final[dict[PresetName, Luminosity]] = {
    "calor": "claro",
    "frio": "escuro",
    "conforto": "adequado",
}


def _preset_name(value: PresetName | str) -> PresetName:
    """Valida e estreita o nome de preset recebido na fronteira do módulo."""

    if value not in PRESETS:
        raise PresetError(f"Preset desconhecido: {value!r}")
    return value


def _state_from_preset(name: PresetName) -> RoomState:
    """Cria um estado completo sem compartilhar estruturas mutáveis."""

    preset = deepcopy(PRESETS[name])
    return {
        "preset_atual": None,
        "revisao_estado": 0,
        "hora": preset["hora"],
        "temperatura_externa": preset["temperatura_externa"],
        "temperatura_interna": preset["temperatura_interna"],
        "umidade": preset["umidade"],
        "luminosidade": _PRESET_LUMINOSITY[name],
        "chuva": preset["chuva"],
        "presenca_interna": preset["presenca_interna"],
        "presenca_externa": preset["presenca_externa"],
        "dormir": preset["dormir"],
        "modo": "reativo",
        "dispositivos": preset["dispositivos"],
        "ultima_acao_confirmada": None,
        "decisao": None,
        "etapas": [],
        "preferencias": {},
        "feedbacks": [],
        "rastro": [],
        "decisao_pendente": None,
        "execucao_automatica": {"pausada": True},
    }


estado_quarto: RoomState = _state_from_preset("conforto")


def validate_trace(state: RoomState) -> None:
    """Valida tipos permitidos e ordem estritamente crescente do rastro."""

    previous_order = 0
    expected_fields = {"ordem", "tipo", "decisao_id", "comando_id", "dados"}
    for event in state["rastro"]:
        if set(event) != expected_fields:
            raise TraceError("Evento do rastro possui campos incompatíveis.")
        order = event["ordem"]
        if type(order) is not int or order <= previous_order:
            raise TraceError("A ordem do rastro deve ser estritamente crescente.")
        if event["tipo"] not in _TRACE_EVENT_TYPES:
            raise TraceError("Tipo de evento não pertence ao contrato do rastro.")
        for field in ("decisao_id", "comando_id"):
            value = event[field]
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise TraceError(f"{field} deve ser uma string não vazia ou nulo.")
        if not isinstance(event["dados"], dict):
            raise TraceError("Os dados do evento devem ser um objeto mutável.")
        previous_order = order


def append_trace_event(
    state: RoomState,
    tipo: TraceEventType,
    *,
    decisao_id: str | None = None,
    comando_id: str | None = None,
    dados: Mapping[str, object] | None = None,
) -> TraceEvent:
    """Registra um evento permitido com ordem derivada do último evento."""

    validate_trace(state)
    if tipo not in _TRACE_EVENT_TYPES:
        raise TraceError("Tipo de evento não pertence ao contrato do rastro.")
    for field, value in (("decisao_id", decisao_id), ("comando_id", comando_id)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise TraceError(f"{field} deve ser uma string não vazia ou nulo.")
    event: TraceEvent = {
        "ordem": state["rastro"][-1]["ordem"] + 1 if state["rastro"] else 1,
        "tipo": tipo,
        "decisao_id": decisao_id,
        "comando_id": comando_id,
        "dados": deepcopy(dict(dados or {})),
    }
    state["rastro"].append(event)
    validate_trace(state)
    return deepcopy(event)


def invalidate_decision(
    state: RoomState,
    *,
    motivo: str = "decisão substituída",
) -> TraceEvent | None:
    """Invalida a decisão ativa e registra a transição no rastro."""

    active = state["decisao"] or state["decisao_pendente"]
    if not isinstance(active, Mapping):
        return None
    decision_id = active.get("decisao_id")
    if not isinstance(decision_id, str) or not decision_id.strip():
        return None
    if active.get("status") == "invalidada":
        return None
    invalidated = cast(dict[str, object], deepcopy(dict(active)))
    invalidated["status"] = "invalidada"
    state["decisao"] = invalidated
    state["decisao_pendente"] = None
    return append_trace_event(
        state,
        "invalidacao",
        decisao_id=decision_id,
        dados={"motivo": motivo},
    )


def _apply_preset_state(name: PresetName) -> None:
    """Aplica somente ambiente e dispositivos, sem registrar transição."""

    preset = deepcopy(PRESETS[name])
    estado_quarto["hora"] = preset["hora"]
    estado_quarto["temperatura_externa"] = preset["temperatura_externa"]
    estado_quarto["temperatura_interna"] = preset["temperatura_interna"]
    estado_quarto["umidade"] = preset["umidade"]
    estado_quarto["luminosidade"] = _PRESET_LUMINOSITY[name]
    estado_quarto["chuva"] = preset["chuva"]
    estado_quarto["presenca_interna"] = preset["presenca_interna"]
    estado_quarto["presenca_externa"] = preset["presenca_externa"]
    estado_quarto["dormir"] = preset["dormir"]
    estado_quarto["dispositivos"] = preset["dispositivos"]
    estado_quarto["preset_atual"] = name
    estado_quarto["ultima_acao_confirmada"] = None
    estado_quarto["decisao"] = None
    estado_quarto["etapas"] = []
    estado_quarto["feedbacks"] = []
    estado_quarto["decisao_pendente"] = None
    estado_quarto["execucao_automatica"] = {"pausada": True}


def apply_preset(preset_name: PresetName | str) -> None:
    """Aplica o ambiente solicitado e limpa o runtime da decisão anterior.

    Args:
        preset_name: Nome do cenário determinístico a aplicar.

    Raises:
        PresetError: Se ``preset_name`` não corresponder a um preset conhecido.
    """

    name = _preset_name(preset_name)
    estado_quarto["revisao_estado"] += 1
    invalidate_decision(estado_quarto, motivo="preset aplicado")
    _apply_preset_state(name)
    append_trace_event(estado_quarto, "preset", dados={"preset": name})


def reset_state() -> None:
    """Restaura a apresentação sem descartar aprendizagem ou rastro.

    O objeto global é atualizado em lugar para preservar referências já
    importadas por outros módulos do pacote.
    """

    invalidate_decision(estado_quarto, motivo="reset executado")
    _apply_preset_state("conforto")
    estado_quarto["modo"] = "reativo"
    estado_quarto["preset_atual"] = None
    estado_quarto["ultima_acao_confirmada"] = None
    estado_quarto["decisao"] = None
    estado_quarto["etapas"] = []
    estado_quarto["feedbacks"] = []
    estado_quarto["decisao_pendente"] = None
    estado_quarto["execucao_automatica"] = {"pausada": True}
    append_trace_event(estado_quarto, "reset", dados={"preset": None})
