"""Transporte para o firmware existente: cada endpoint gera um pulso.

Uma resposta OK confirma o pulso no firmware, e não o estado físico.
Não há repetição automática: após falha o chamador deve invalidar o estado.
"""

import http.client
import ipaddress
import math
import time


_LAN_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
_ENDPOINTS = frozenset(("/nivel", "/temperatura", "/ventilador", "/umidificador"))
_DEVICES = frozenset(("ventilador", "umidificador"))


def validate_lan_ip(ip):
    """Aceita somente IPv4 literal nos intervalos LAN privados RFC 1918."""
    try:
        address = ipaddress.IPv4Address(ip)
    except (ipaddress.AddressValueError, TypeError) as exc:
        raise ValueError("Informe um IPv4 privado da rede local.") from exc
    if not any(address in network for network in _LAN_NETWORKS):
        raise ValueError("O IP da ESP32 deve pertencer a uma rede privada local.")
    return str(address)


class PulseError(OSError):
    """Falha que mantém o número de pulsos confirmados e tentativas."""

    def __init__(self, confirmed, attempted, mensagem):
        super().__init__(mensagem)
        self.confirmed = confirmed
        self.attempted = attempted


class EspTransport:
    def __init__(self, timeout=3, pulse_gap=0.35, sleep=time.sleep, command_timeout=10):
        timeout = float(timeout)
        command_timeout = float(command_timeout)
        pulse_gap = float(pulse_gap)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout deve ser finito e maior que zero.")
        if not math.isfinite(command_timeout) or command_timeout <= 0:
            raise ValueError("command_timeout deve ser finito e maior que zero.")
        if not math.isfinite(pulse_gap) or pulse_gap < 0:
            raise ValueError("pulse_gap deve ser finito e não negativo.")
        self.timeout = timeout
        self.command_timeout = command_timeout
        self.pulse_gap = pulse_gap
        self.sleep = sleep

    def read(self, ip, endpoint, *, timeout=None):
        ip = validate_lan_ip(ip)
        if endpoint not in _ENDPOINTS:
            raise ValueError("Endpoint da ESP32 não permitido.")
        connection = http.client.HTTPConnection(ip, 80, timeout=self.timeout if timeout is None else timeout)
        try:
            connection.request("GET", endpoint)
            response = connection.getresponse()
            if response.status != 200:
                raise OSError(f"ESP32 respondeu HTTP {response.status}.")
            body = response.read(4097)
            if len(body) > 4096:
                raise OSError("Resposta da ESP32 excede o limite permitido.")
            return body.decode("utf-8", errors="replace").strip()
        finally:
            connection.close()

    def set_state(self, ip, dispositivo, ligado):
        ip = validate_lan_ip(ip)
        if dispositivo not in _DEVICES:
            raise ValueError("Dispositivo deve ser ventilador ou umidificador.")
        if not isinstance(ligado, bool):
            raise ValueError("ligado deve ser booleano.")
        total = 3 if ligado else 1
        confirmed = 0
        for attempt in range(1, total + 1):
            try:
                response = self.read(ip, "/" + dispositivo, timeout=self.command_timeout)
                if response != "OK":
                    raise OSError("Resposta da ESP32 não confirmou o pulso com OK.")
            except (OSError, http.client.HTTPException) as exc:
                raise PulseError(
                    confirmed, attempt,
                    "Sem confirmação do pulso; ele pode ter ocorrido. "
                    f"Não repetir automaticamente. {dispositivo}, chamada {attempt}/{total}, "
                    f"espera de {self.command_timeout:g} s. " + str(exc),
                ) from exc
            confirmed += 1
            if attempt < total:
                self.sleep(self.pulse_gap)
        return confirmed
