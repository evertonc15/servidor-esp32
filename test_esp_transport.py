"""Testes sem hardware: nenhuma requisição real é enviada à ESP32."""

import http.client
import unittest
from unittest.mock import Mock, call, patch

from esp_transport import EspTransport, PulseError, validate_lan_ip


class PulseTransportTest(unittest.TestCase):
    def setUp(self):
        self.sleep = Mock()
        self.transport = EspTransport(timeout=3, pulse_gap=0.35, sleep=self.sleep)
        self.ip = "192.168.2.9"

    def test_ligar_tres_pulsos_e_duas_pausas(self):
        for dispositivo in ("ventilador", "umidificador"):
            with self.subTest(dispositivo=dispositivo):
                self.sleep.reset_mock()
                with patch.object(self.transport, "read", return_value="OK") as read:
                    confirmed = self.transport.set_state(self.ip, dispositivo, True)
                self.assertEqual(confirmed, 3)
                self.assertEqual(read.call_args_list, [call(self.ip, "/" + dispositivo)] * 3)
                self.assertEqual(self.sleep.call_args_list, [call(0.35), call(0.35)])

    def test_desligar_um_pulso_sem_pausa(self):
        for dispositivo in ("ventilador", "umidificador"):
            with self.subTest(dispositivo=dispositivo):
                with patch.object(self.transport, "read", return_value="OK") as read:
                    confirmed = self.transport.set_state(self.ip, dispositivo, False)
                self.assertEqual(confirmed, 1)
                read.assert_called_once_with(self.ip, "/" + dispositivo)
        self.sleep.assert_not_called()

    def test_timeout_no_segundo_pulso_aborta_sem_retry(self):
        with patch.object(self.transport, "read", side_effect=["OK", TimeoutError("timeout")]) as read:
            with self.assertRaises(PulseError) as context:
                self.transport.set_state(self.ip, "ventilador", True)
        self.assertEqual(context.exception.confirmed, 1)
        self.assertEqual(context.exception.attempted, 2)
        self.assertEqual(read.call_count, 2)
        self.sleep.assert_called_once_with(0.35)

    def test_primeiro_pulso_sem_confirmacao_nao_repete(self):
        with patch.object(self.transport, "read", side_effect=http.client.RemoteDisconnected()) as read:
            with self.assertRaises(PulseError) as context:
                self.transport.set_state(self.ip, "umidificador", False)
        self.assertEqual(context.exception.confirmed, 0)
        self.assertEqual(context.exception.attempted, 1)
        self.assertEqual(read.call_count, 1)
        self.sleep.assert_not_called()

    def test_corpo_diferente_de_ok_nao_confirma_pulso(self):
        with patch.object(self.transport, "read", side_effect=["OK", "ERRO"]) as read:
            with self.assertRaises(PulseError) as context:
                self.transport.set_state(self.ip, "umidificador", True)
        self.assertEqual(context.exception.confirmed, 1)
        self.assertEqual(context.exception.attempted, 2)
        self.assertEqual(read.call_count, 2)

    def test_validacao_antes_de_qualquer_pulso(self):
        with patch.object(self.transport, "read") as read:
            for ip, dispositivo, ligado in (
                ("8.8.8.8", "ventilador", True),
                (self.ip, "arcondicionado", True),
                (self.ip, "umidificador", "false"),
            ):
                with self.subTest(ip=ip, dispositivo=dispositivo, ligado=ligado):
                    with self.assertRaises(ValueError):
                        self.transport.set_state(ip, dispositivo, ligado)
        read.assert_not_called()


class ReadTransportTest(unittest.TestCase):
    def setUp(self):
        self.transport = EspTransport(timeout=3, sleep=Mock())

    @patch("esp_transport.http.client.HTTPConnection")
    def test_get_fixo_sem_redirect_e_conexao_fechada(self, factory):
        connection = factory.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b" 1\n"
        self.assertEqual(self.transport.read("192.168.2.9", "/nivel"), "1")
        factory.assert_called_once_with("192.168.2.9", 80, timeout=3)
        connection.request.assert_called_once_with("GET", "/nivel")
        connection.close.assert_called_once()

    @patch("esp_transport.http.client.HTTPConnection")
    def test_redirect_recusado_sem_segunda_requisicao(self, factory):
        connection = factory.return_value
        connection.getresponse.return_value.status = 302
        with self.assertRaises(OSError):
            self.transport.read("192.168.2.9", "/nivel")
        connection.request.assert_called_once_with("GET", "/nivel")
        connection.close.assert_called_once()

    @patch("esp_transport.http.client.HTTPConnection")
    def test_timeout_fecha_conexao_sem_retry(self, factory):
        connection = factory.return_value
        connection.getresponse.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.transport.read("192.168.2.9", "/temperatura")
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    @patch("esp_transport.http.client.HTTPConnection")
    def test_endpoints_arbitrarios_nao_enviam_http(self, factory):
        for endpoint in ("/", "/nivel?x=1", "http://example.com", "/outro", "/ventilador\r\n"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    self.transport.read("192.168.2.9", endpoint)
        factory.assert_not_called()

    @patch("esp_transport.http.client.HTTPConnection")
    def test_ips_fora_de_lan_nao_enviam_http(self, factory):
        for ip in ("8.8.8.8", "127.0.0.1", "169.254.1.1", "0.0.0.0", "224.0.0.1", "::1", "localhost", "http://192.168.2.9"):
            with self.subTest(ip=ip):
                with self.assertRaises(ValueError):
                    self.transport.read(ip, "/nivel")
        factory.assert_not_called()

    def test_intervalos_lan_sao_aceitos(self):
        for ip in ("10.1.2.3", "172.16.1.2", "172.31.255.254", "192.168.2.9"):
            self.assertEqual(validate_lan_ip(ip), ip)

    @patch("esp_transport.http.client.HTTPConnection")
    def test_resposta_excessiva_nao_aceita_truncamento(self, factory):
        connection = factory.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b"x" * 4097
        with self.assertRaises(OSError):
            self.transport.read("192.168.2.9", "/temperatura")
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
