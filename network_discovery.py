"""Publica o Flask via mDNS e avisa diretamente a ESP por HTTP."""
import http.client
import ipaddress
import logging
import socket
import threading
import time

import ifaddr
from zeroconf import IPVersion, ServiceInfo, Zeroconf

SERVICE_TYPE = '_esp32tcc._tcp.local.'
SERVICE_NAME = 'Servidor ESP32.' + SERVICE_TYPE


def lan_addresses(network='192.168.2.0/24'):
    subnet = ipaddress.IPv4Network(network)
    result = set()
    for adapter in ifaddr.get_adapters():
        for address in adapter.ips:
            if isinstance(address.ip, str):
                ip = ipaddress.ip_address(address.ip)
                if ip.version == 4 and ip in subnet and not ip.is_loopback:
                    result.add(str(ip))
    return tuple(sorted(result))


class ServerDiscovery:
    def __init__(self, network='192.168.2.0/24', port=5050, interval=10,
                 addresses=None, factory=Zeroconf, esp_ip='192.168.2.5',
                 http_factory=http.client.HTTPConnection):
        subnet = ipaddress.IPv4Network(network)
        target = ipaddress.IPv4Address(esp_ip)
        if target not in subnet or target in (subnet.network_address, subnet.broadcast_address):
            raise ValueError('IP da ESP deve pertencer a rede configurada.')
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError('Porta HTTP invalida.')
        self.network, self.port, self.interval = network, port, interval
        self.addresses = addresses or (lambda: lan_addresses(network))
        self.factory = factory
        self.esp_ip = str(target)
        self.http_factory = http_factory
        self.last_notice = None
        self.last_notice_addresses = ()
        self.notice = {'ip_esp': self.esp_ip, 'aceito': False, 'erro': 'Aviso HTTP ainda nao enviado.'}
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.zc = None
        self.info = None
        self.published = ()
        self.error = None
        self.log = logging.getLogger('descoberta')

    def _close(self):
        zc, info = self.zc, self.info
        self.zc = self.info = None
        self.published = ()
        if zc is not None:
            try:
                if info is not None:
                    zc.unregister_service(info)
            except Exception as error:
                self.log.warning('Falha ao retirar anuncio antigo: %s', type(error).__name__)
            finally:
                try:
                    zc.close()
                except Exception as error:
                    self.log.warning('Falha ao fechar mDNS antigo: %s', type(error).__name__)

    def refresh(self):
        with self.lock:
            try:
                addresses = tuple(sorted(set(self.addresses())))
                if addresses and addresses == self.published:
                    return
                self._close()
                if not addresses:
                    self.error = 'Nenhum IPv4 na rede configurada.'
                    return
                zc = self.factory(interfaces=list(addresses), ip_version=IPVersion.V4Only)
                try:
                    info = ServiceInfo(SERVICE_TYPE, SERVICE_NAME, port=self.port,
                                       addresses=[socket.inet_aton(ip) for ip in addresses],
                                       server='servidor-esp32.local.',
                                       properties={'projeto': 'servidor_esp32', 'versao': '1'})
                    zc.register_service(info, allow_name_change=False)
                except Exception:
                    zc.close()
                    raise
                self.zc, self.info = zc, info
                self.published, self.error = addresses, None
                self.log.info('Flask anunciado para ESP32: %s:%s', ', '.join(addresses), self.port)
            except Exception as error:
                self.error = 'Falha na descoberta: ' + type(error).__name__
                self.log.warning('%s; nova tentativa em %s s.', self.error, self.interval)

    def status(self):
        with self.lock:
            return {'ativo': self.zc is not None, 'servico': SERVICE_TYPE,
                    'enderecos': list(self.published), 'porta': self.port,
                    'rede': self.network, 'erro': self.error, 'aviso_http': dict(self.notice)}

    def notify_esp(self):
        """Avisa somente /servidor; nao consulta sensores nem aciona reles.

        A ESP captura o IP de origem e confirma /identidade depois de responder,
        para evitar que os dois HTTPClients aguardem um ao outro.
        """
        now = time.monotonic()
        try:
            addresses = tuple(ip for ip in sorted(set(self.addresses())) if ip != self.esp_ip)
            if (addresses == self.last_notice_addresses and self.last_notice is not None
                    and now - self.last_notice < 30):
                return
            self.last_notice, self.last_notice_addresses = now, addresses
            notice = {'ip_esp': self.esp_ip, 'aceito': False, 'erro': 'Nenhum IPv4 local para avisar a ESP.'}
            for address in addresses:
                if self.stop_event.is_set():
                    break
                connection = None
                try:
                    connection = self.http_factory(self.esp_ip, 80, timeout=2,
                                                   source_address=(address, 0))
                    connection.request('GET', '/servidor')
                    response = connection.getresponse()
                    accepted = response.status == 200 and response.read(128).decode('ascii', errors='replace').strip() == 'DESCOBERTA_ACEITA'
                    notice = {'ip_esp': self.esp_ip, 'ip_servidor': address, 'aceito': accepted,
                              'erro': None if accepted else 'Aviso nao aceito (HTTP %s). Confira o novo firmware.' % response.status}
                    if accepted:
                        break
                except (OSError, http.client.HTTPException) as error:
                    notice = {'ip_esp': self.esp_ip, 'ip_servidor': address, 'aceito': False,
                              'erro': 'ESP indisponivel para aviso: ' + type(error).__name__}
                finally:
                    if connection is not None:
                        connection.close()
            with self.lock:
                self.notice = notice
        except Exception as error:
            with self.lock:
                self.notice = {'ip_esp': self.esp_ip, 'aceito': False,
                               'erro': 'Falha no aviso HTTP: ' + type(error).__name__}

    def _run(self):
        while not self.stop_event.is_set():
            self.refresh()
            self.notify_esp()
            self.stop_event.wait(self.interval)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name='mdns-flask')
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
        with self.lock:
            self._close()
