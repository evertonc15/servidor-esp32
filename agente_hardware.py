"""Perfil PEAS para dois aparelhos reais, independente de Flask e de HTTP.

A política reativa usa histerese; a cognitiva compara duas ações binárias
pela utilidade do PEAS (60% adequação ao objetivo e 40% economia), acrescida
da preferência aprendida. O índice de adequação é explicitamente uma
heurística de decisão, não uma previsão de queda real da temperatura.
Ventiladores não são modelados como ar-condicionado e nenhuma evolução
física simulada substitui a próxima leitura do DHT11.

São reutilizadas as funções públicas calculate_comfort, calculate_cost,
calculate_economy, calculate_preference_adjustment e calculate_utility de
agente_peas.services. Janela, ar-condicionado e lâmpada não são atuadores
disponíveis neste perfil. Feedback altera somente decisões futuras.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from math import isfinite

from agente_peas import services


TEMP_LIGAR = float(services.TEMP_HOT_LIMIT_C)
TEMP_DESLIGAR = float(services.TEMP_CLIMATE_OFF_C)
TEMP_PRIORITARIA = float(services.LEARNED_HEAT_CEILING_C)
UMIDADE_LIGAR = 40.0
UMIDADE_DESLIGAR = 50.0
UMIDADE_PRIORITARIA = 80.0
DISPOSITIVOS = ("ventilador", "umidificador")


def _numero(value: object, nome: str, minimo: float, maximo: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{nome} deve ser um numero.")
    numero = float(value)
    if not isfinite(numero) or not minimo <= numero <= maximo:
        raise ValueError(f"{nome} fora do intervalo {minimo}..{maximo}.")
    return numero


def _estado(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise ValueError("Estado deve ser ligado/desligado booleano ou desconhecido (null).")


def _faixa(valor: float, baixo: float, alto: float) -> str:
    if valor < baixo:
        return "baixa"
    if valor > alto:
        return "alta"
    return "conforto"


def _chave(contexto: Mapping[str, object], dispositivo: str, ligar: bool) -> str:
    return json.dumps(
        ["hardware-v1", dispositivo, contexto["faixa_temperatura"],
         contexto["faixa_umidade"], contexto["faixa_horario"],
         "ligar" if ligar else "desligar"],
        ensure_ascii=False, separators=(",", ":"),
    )


def _preferencia(preferencias: Mapping[str, object], chave: str) -> int:
    value = preferencias.get(chave, 0)
    if type(value) is not int:
        raise ValueError("Preferencia deve ser um inteiro.")
    return max(-3, min(3, value))


def aprender(preferencias: Mapping[str, object], chave: str, gostei: bool) -> dict:
    """Devolve atualização pura; persistência e unicidade cabem ao backend."""
    if not isinstance(chave, str) or not chave:
        raise ValueError("Chave da alternativa da decisao obrigatoria.")
    if type(gostei) is not bool:
        raise ValueError("gostei deve ser booleano.")
    anterior = _preferencia(preferencias, chave)
    delta = 1 if gostei else -1
    atual = max(-3, min(3, anterior + delta))
    return {
        "chave": chave,
        "preferencia_anterior": anterior,
        "preferencia_atual": atual,
        "delta": atual - anterior,
        "limite_atingido": atual == anterior,
    }


def decidir(
    leituras: Mapping[str, object],
    estados: Mapping[str, object],
    preferencias: Mapping[str, object] | None = None,
    modo: str = "cognitivo",
    hora: int | None = None,
) -> dict:
    """Retorna propostas; não envia comandos nem altera estados/aprendizagem.

    leituras: temperatura em C, umidade em %, nivel 0/1 (agua ausente/presente).
    estados: cada dispositivo booleano ou None se ainda não sincronizado.
    preferencias: chave da alternativa -> inteiro -3..3 persistido no banco.
    """
    if modo not in ("reativo", "cognitivo"):
        raise ValueError("modo deve ser reativo ou cognitivo.")
    temperatura = _numero(leituras.get("temperatura"), "temperatura", -40, 80)
    umidade = _numero(leituras.get("umidade"), "umidade", 0, 100)
    nivel = leituras.get("nivel")
    if type(nivel) is not int or nivel not in (0, 1):
        raise ValueError("nivel deve ser 0 ou 1 obtido da boia.")
    if hora is not None and (type(hora) is not int or not 0 <= hora <= 23):
        raise ValueError("hora deve ser inteiro 0..23.")
    preferencias = preferencias or {}
    faixa_horario = (
        "nao_informado" if hora is None else
        "madrugada" if hora <= 5 else
        "amanhecer" if hora <= 8 else
        "dia" if hora <= 17 else "noite"
    )
    contexto = {
        "temperatura": temperatura,
        "umidade": umidade,
        "nivel": nivel,
        "hora": hora,
        "faixa_horario": faixa_horario,
        "faixa_temperatura": _faixa(temperatura, TEMP_DESLIGAR, TEMP_LIGAR),
        "faixa_umidade": _faixa(umidade, UMIDADE_LIGAR, UMIDADE_DESLIGAR),
    }
    atuais = {nome: _estado(estados.get(nome)) for nome in DISPOSITIVOS}
    propostas = []
    for dispositivo in DISPOSITIVOS:
        atual = atuais[dispositivo]
        prioridade = None
        if dispositivo == "ventilador":
            if temperatura > TEMP_LIGAR:
                alvo_reativo = True
                motivo = f"Temperatura acima de {TEMP_LIGAR:g} C."
            elif temperatura <= TEMP_DESLIGAR:
                alvo_reativo = False
                motivo = f"Temperatura em {TEMP_DESLIGAR:g} C ou menos."
            else:
                alvo_reativo = bool(atual)
                motivo = "Faixa de histerese termica; conservar estado."
            adequacao_atual = services.calculate_comfort(temperatura)
            if temperatura >= TEMP_PRIORITARIA:
                prioridade = "Calor extremo: manter ventilacao como prioridade reativa."
                alvo_reativo = True
        else:
            if umidade < UMIDADE_LIGAR:
                alvo_reativo = True
                motivo = f"Umidade abaixo de {UMIDADE_LIGAR:g}%."
            elif umidade >= UMIDADE_DESLIGAR:
                alvo_reativo = False
                motivo = f"Umidade em {UMIDADE_DESLIGAR:g}% ou mais."
            else:
                alvo_reativo = bool(atual)
                motivo = "Faixa de histerese da umidade; conservar estado."
            # Adequacao da umidade atual, separada do conforto termico PEAS.
            adequacao_atual = max(0.0, 1 - abs(umidade - 45.0) / 55.0)
            if nivel == 0:
                prioridade = "Sem agua: umidificador deve ficar desligado."
                alvo_reativo = False
            elif umidade >= UMIDADE_PRIORITARIA:
                prioridade = "Umidade extrema: desligar como prioridade reativa."
                alvo_reativo = False

        alternativas = []
        for ligar in (False, True):
            chave = _chave(contexto, dispositivo, ligar)
            preferencia = _preferencia(preferencias, chave)
            bloqueio = None
            if prioridade is not None and ligar != alvo_reativo:
                bloqueio = prioridade
            # Dentro da histerese não criar trocas apenas por preferência.
            na_histerese = (
                TEMP_DESLIGAR < temperatura <= TEMP_LIGAR
                if dispositivo == "ventilador"
                else UMIDADE_LIGAR <= umidade < UMIDADE_DESLIGAR
            )
            if prioridade is None and na_histerese and ligar != alvo_reativo:
                bloqueio = "Manter estado durante a histerese."
            # 0.7 evita que pequenas diferenças de economia anulem a regra.
            adequacao = 1.0 if ligar == alvo_reativo else round(0.7 * adequacao_atual, 4)
            finais = {nome: int(bool(atuais[nome])) for nome in DISPOSITIVOS}
            finais[dispositivo] = int(ligar)
            custo = services.calculate_cost(finais)
            economia = services.calculate_economy(custo)
            base = services.calculate_utility(adequacao, economia, 0)
            total = services.calculate_utility(adequacao, economia, preferencia)
            alternativas.append({
                "comando": "ligar" if ligar else "desligar",
                "ligado": ligar,
                "preferencia_chave": chave,
                "preferencia": preferencia,
                "ajuste_preferencia": services.calculate_preference_adjustment(preferencia),
                "adequacao": round(adequacao, 4),
                "economia": economia,
                "custo_relativo": custo,
                "pontuacao_base": base,
                "pontuacao_total": total,
                "elegivel": bloqueio is None,
                "motivo_bloqueio": bloqueio,
            })
        elegiveis = [item for item in alternativas if item["elegivel"]]
        if modo == "reativo" or prioridade is not None:
            escolhida = next(item for item in elegiveis if item["ligado"] == alvo_reativo)
        else:
            escolhida = max(elegiveis, key=lambda item: (
                item["pontuacao_total"], item["ligado"] == alvo_reativo,
            ))
        alvo = escolhida["ligado"]
        adaptado = modo == "cognitivo" and alvo != alvo_reativo
        estado_desconhecido = atual is None
        justificativa = prioridade or motivo
        if adaptado:
            justificativa += " Preferencia aprendida alterou a escolha pela utilidade."
        elif modo == "cognitivo" and prioridade is None:
            justificativa += " Utilidade cognitiva confirma a regra."
        if estado_desconhecido:
            justificativa += " Sincronize o estado inicial antes de enviar pulsos."
        propostas.append({
            "dispositivo": dispositivo,
            "ligado": alvo,
            "comando": escolhida["comando"],
            "estado_anterior": atual,
            "alterar": not estado_desconhecido and alvo != atual,
            "bloqueado": estado_desconhecido,
            "justificativa": justificativa,
            "preferencia_chave": escolhida["preferencia_chave"],
            "adaptado": adaptado,
            "prioridade_reativa": prioridade is not None,
            "alternativas": alternativas,
        })
    return {
        "modo": modo,
        "perfil": "hardware-v1",
        "contexto": contexto,
        "propostas": propostas,
        "adaptado": any(item["adaptado"] for item in propostas),
    }
