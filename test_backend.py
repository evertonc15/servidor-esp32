import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as servidor


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = servidor.DATABASE
        servidor.DATABASE = Path(self.tmp.name) / 'test.sqlite3'
        self.client = servidor.app.test_client()

    def tearDown(self):
        servidor.DATABASE = self.original
        self.tmp.cleanup()

    def registrar(self):
        self.client.get('/meuip?placa=esp32c3vent&ip=192.168.2.50')

    def test_sem_placa(self):
        self.assertEqual(self.client.post('/ventilador').status_code, 409)

    @patch('esp_backend.consultar_esp', return_value='OK')
    def test_pulsos_nas_rotas_corretas(self, enviar):
        self.registrar()
        for rota, alvo in [('/ventilador', '/ventilador'),
                           ('/interf/ligarventilador', '/ventilador'),
                           ('/umidificador', '/umidificador'),
                           ('/interf/ligarumidificador', '/umidificador')]:
            resposta = self.client.post(rota)
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(resposta.json['estado_fisico'], 'desconhecido')
            enviar.assert_called_with('192.168.2.50', alvo)
        self.assertEqual(enviar.call_count, 4)

    @patch('esp_backend.consultar_esp', side_effect=TimeoutError())
    def test_falha_nao_repete(self, enviar):
        self.registrar()
        self.assertEqual(self.client.post('/umidificador').status_code, 502)
        self.assertEqual(enviar.call_count, 1)

    @patch('esp_backend.consultar_esp', return_value='1')
    def test_consulta_nao_aciona(self, enviar):
        self.registrar()
        self.assertEqual(self.client.get('/esp/conexao').json['nivel'], 1)
        enviar.assert_called_once_with('192.168.2.50', '/nivel')

    @patch('esp_backend.consultar_esp')
    def test_agente_usa_sensor_sem_simular_ou_acionar(self, enviar):
        self.registrar()
        self.client.get('/ajustar?temperatura=28&umidade=30', environ_overrides={'REMOTE_ADDR': '192.168.2.50'})
        for modo in ('reativo', 'cognitivo'):
            resposta = self.client.post('/agente/decidir', json={'modo': modo})
            self.assertEqual(resposta.status_code, 200)
            self.assertFalse(resposta.json['executado'])
            self.assertEqual(resposta.json['leitura']['temperatura'], 28)
        enviar.assert_not_called()

    def test_nao_utiliza_sensor_de_outra_placa(self):
        self.registrar()
        self.client.get('/ajustar?temperatura=28&umidade=30')
        self.assertEqual(self.client.post('/agente/decidir', json={}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
