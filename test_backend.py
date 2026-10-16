"""Testes do fluxo real com transporte HTTP substituído por fixture."""
from pathlib import Path
import os
import http.client
import tempfile
import unittest
from unittest.mock import Mock
from uuid import uuid4
from datetime import timedelta

from sqlalchemy import select, create_engine, text
from sqlalchemy.engine import make_url

from app import create_app
from storage import Command, Decision, Device, Feedback, Plate, Preference, Reading, utcnow, utc
from esp_transport import PulseError


class ControllerIntegrationTest(unittest.TestCase):
    def setUp(self):
        # O sandbox Windows usa um TEMP que nao aceita SQLite; use a pasta
        # da suite. TemporaryDirectory limita limpeza a este diretorio unico.
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.url = 'sqlite:///' + str(Path(self.tmp.name) / 'agente.sqlite3').replace('\\', '/')
        self.pg_engine = None
        if os.getenv('TEST_DATABASE_URL'):
            self.pg_engine = create_engine(os.environ['TEST_DATABASE_URL'])
            self.schema = 'tcc_test_' + uuid4().hex
            with self.pg_engine.begin() as conn:
                conn.execute(text('CREATE SCHEMA "' + self.schema + '"'))
            url = make_url(os.environ['TEST_DATABASE_URL'])
            self.url = url.set(query=dict(url.query, options='-csearch_path=' + self.schema)).render_as_string(hide_password=False)
        self.transport = Mock()
        self.transport.read.return_value = '1'
        self.transport.set_state.side_effect = lambda ip, device, target: 3 if target else 1
        self.app = create_app({'DATABASE_URL': self.url, 'START_WORKER': False}, transport=self.transport)
        self.client = self.app.test_client()
        self.controller = self.app.extensions['controller']
        self.store = self.app.extensions['store']
        self.apps = [self.app]

    def tearDown(self):
        for app in self.apps:
            app.extensions['controller'].stop()
            app.extensions['store'].engine.dispose()
        self.tmp.cleanup()
        if self.pg_engine:
            with self.pg_engine.begin() as conn:
                conn.execute(text('DROP SCHEMA "' + self.schema + '" CASCADE'))
            self.pg_engine.dispose()

    def test_partial_failure_invalidates_state_and_does_not_retry(self):
        self.setup_plate()
        self.transport.set_state.side_effect = PulseError(1, 2, 'timeout')
        first = self.client.post('/ventilador/ligar')
        self.assertEqual(first.status_code, 502)
        second = self.client.post('/ventilador/ligar')
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self.transport.set_state.call_count, 1)
        with self.store.session() as s:
            self.assertIsNone(s.get(Device, ('teste', 'ventilador')).state)
            self.assertFalse(s.get(Plate, 'teste').automatic)
            c = s.scalar(select(Command))
            self.assertEqual((c.confirmed, c.attempted, c.status), (1, 2, 'falhou'))
        status = self.client.get('/agente/status').json
        self.assertTrue(status['precisa_sincronizar'])
        self.assertIn('ventilador', status['alerta'])
        self.assertEqual(self.client.post('/agente/configurar', json={'automatico': True}).status_code, 409)

    def test_automatic_failure_stops_remaining_device_and_later_cycles(self):
        self.setup_plate(mode='reativo')
        self.transport.set_state.side_effect = PulseError(1, 2, 'timeout')
        _, _, _, result = self.reading(temperature=30, humidity=35)
        self.assertEqual(result, 'incompleta')
        self.assertEqual(self.transport.set_state.call_args.args, ('192.168.2.9', 'ventilador', True))
        self.transport.set_state.assert_called_once()
        with self.store.session() as s:
            d = s.scalar(select(Decision))
            self.assertEqual(d.body['resultados'][1]['status'], 'nao_executado')
            self.assertFalse(s.get(Device, ('teste', 'umidificador')).state)
            self.assertFalse(s.get(Plate, 'teste').automatic)
        pending = self.reading(temperature=30, humidity=35, process=False)
        self.controller.process_reading(pending)
        self.transport.set_state.assert_called_once()
        with self.store.session() as s:
            self.assertEqual(s.get(Reading, pending).status, 'automatico_pausado')

    def test_existing_unknown_state_pauses_worker_and_sync_clears_warning(self):
        self.setup_plate(mode='reativo')
        with self.store.session() as s:
            s.get(Device, ('teste', 'ventilador')).state = None
        self.reading(temperature=30, humidity=35)
        self.transport.set_state.assert_not_called()
        status = self.client.get('/agente/status').json
        self.assertFalse(status['automatico'])
        self.assertTrue(status['precisa_sincronizar'])
        self.client.post('/agente/sincronizar', json={'ventilador': False, 'umidificador': False})
        status = self.client.get('/agente/status').json
        self.assertFalse(status['precisa_sincronizar'])
        self.assertIsNone(status['alerta'])
        self.assertFalse(status['automatico'])

    def test_humidifier_partial_failure_like_overnight_test_pauses_automation(self):
        self.setup_plate(mode='reativo')
        self.transport.set_state.side_effect = PulseError(1, 2, 'timed out')
        _, _, _, status = self.reading(temperature=22.3, humidity=38)
        self.assertEqual(status, 'incompleta')
        self.transport.set_state.assert_called_once_with('192.168.2.9', 'umidificador', True)
        current = self.client.get('/agente/status').json
        self.assertFalse(current['automatico'])
        self.assertIsNone(current['estados_estimados']['umidificador'])
        self.assertFalse(current['estados_estimados']['ventilador'])
        with self.store.session() as s:
            command = s.scalar(select(Command))
            self.assertEqual((command.requested, command.confirmed, command.attempted), (3, 1, 2))

    def test_unknown_second_device_cancels_first_device_before_any_pulse(self):
        self.setup_plate(mode='reativo')
        with self.store.session() as s:
            s.get(Device, ('teste', 'umidificador')).state = None
        _, _, plan, status = self.reading(temperature=30, humidity=35)
        self.assertEqual(status, 'incompleta')
        self.assertEqual([r['status'] for r in plan['resultados']], ['nao_executado', 'estado_desconhecido'])
        self.transport.set_state.assert_not_called()
        with self.store.session() as s:
            self.assertFalse(s.get(Device, ('teste', 'ventilador')).state)
            self.assertFalse(s.get(Plate, 'teste').automatic)

    def test_command_wait_can_be_configured_without_changing_sensor_timeout(self):
        app = create_app({'DATABASE_URL': self.url, 'START_WORKER': False, 'ESP_COMMAND_TIMEOUT': '12'})
        self.apps.append(app)
        transport = app.extensions['controller'].transport
        self.assertEqual(transport.command_timeout, 12)
        self.assertEqual(transport.timeout, 3)

    def test_fixed_ip_metadata_and_panel_alias_do_not_send_pulses(self):
        result = self.client.get('/meuip?placa=teste&ip=192.168.2.5&ip_fixo=1')
        self.assertTrue(result.json['ip_fixo'])
        self.assertTrue(self.client.get('/placas').json[0]['ip_fixo'])
        self.assertTrue(self.client.get('/agente/status').json['ip_fixo'])
        # Ping de firmware anterior não deve apagar o metadado.
        self.client.get('/meuip?placa=teste&ip=192.168.2.5')
        self.assertTrue(self.client.get('/placas').json[0]['ip_fixo'])
        self.assertEqual(self.client.get('/agente').status_code, 200)
        self.assertEqual(self.client.get('/identidade').data, b'ESP32_TCC_V1')
        self.assertFalse(self.client.get('/rede/status').json['ativo'])
        self.assertEqual(self.client.get('/meuip?placa=teste&ip=192.168.2.5&ip_fixo=talvez').status_code, 400)
        self.transport.set_state.assert_not_called()

    def test_new_reading_during_probe_supersedes_old(self):
        self.setup_plate()
        reading_id = self.reading(process=False)
        def probe(*args):
            self.reading(temperature=22, process=False)
            return '1'
        self.transport.read.side_effect = probe
        self.controller.process_reading(reading_id)
        self.transport.set_state.assert_not_called()
        with self.store.session() as s:
            self.assertEqual(s.get(Reading, reading_id).status, 'substituida')

    def test_http_protocol_error_has_backoff_and_no_pulses(self):
        self.setup_plate()
        reading_id = self.reading(process=False)
        self.transport.read.side_effect = http.client.BadStatusLine('invalid')
        self.controller.process_reading(reading_id)
        self.transport.set_state.assert_not_called()
        with self.store.session() as s:
            self.assertGreater(utc(s.get(Reading, reading_id).ready), utcnow())
        self.assertEqual(self.client.get('/esp/conexao').status_code, 502)

    def test_busy_plate_blocks_concurrent_command(self):
        self.setup_plate()
        with self.store.lock('teste') as locked:
            self.assertTrue(locked)
            self.assertEqual(self.client.post('/ventilador/ligar').status_code, 409)
        self.transport.set_state.assert_not_called()

    def test_long_ping_with_recent_reading_preserves_sync(self):
        from storage import Plate
        self.setup_plate()
        self.reading(process=False)
        with self.store.session() as s:
            s.get(Plate, 'teste').updated = utcnow() - timedelta(hours=1)
        self.client.get('/meuip?placa=teste&ip=192.168.2.9')
        self.assertTrue(self.client.get('/agente/status').json['automatico'])

    def setup_plate(self, mode='cognitivo', automatic=True):
        self.assertEqual(self.client.get('/meuip?placa=teste&ip=192.168.2.9').status_code, 200)
        sync = self.client.post('/agente/sincronizar', json={'ventilador': False, 'umidificador': False})
        self.assertEqual(sync.status_code, 200)
        configured = self.client.post('/agente/configurar', json={'automatico': automatic, 'modo': mode})
        self.assertEqual(configured.status_code, 200)

    def reading(self, temperature=30, humidity=55, process=True):
        response = self.client.get(
            f'/ajustar?temperatura={temperature}&umidade={humidity}',
            environ_overrides={'REMOTE_ADDR': '192.168.2.9'},
        )
        self.assertEqual(response.status_code, 200, response.json)
        reading_id = response.json['leitura_id']
        if process:
            self.controller.process_reading(reading_id)
            with self.store.session() as session:
                decision = session.scalar(select(Decision).where(Decision.reading == reading_id))
                self.assertIsNotNone(decision)
                return reading_id, decision.id, decision.body, decision.status
        return reading_id

    def test_reading_only_enqueues_and_worker_dispatches_without_ui(self):
        self.setup_plate()
        reading_id = self.reading(humidity=30, process=False)
        self.transport.set_state.assert_not_called()
        self.transport.read.assert_not_called()
        with self.store.session() as session:
            self.assertEqual(session.get(Reading, reading_id).status, 'pendente')
        self.controller.process_reading(reading_id)
        self.assertEqual(self.transport.set_state.call_count, 2)
        self.transport.set_state.assert_any_call('192.168.2.9', 'ventilador', True)
        self.transport.set_state.assert_any_call('192.168.2.9', 'umidificador', True)
        with self.store.session() as session:
            commands = list(session.scalars(select(Command)))
            self.assertEqual([(c.requested, c.confirmed) for c in commands], [(3, 3), (3, 3)])
            self.assertEqual(session.get(Reading, reading_id).status, 'executada')
        # Mesmo ciclo não executa duas vezes.
        self.controller.process_reading(reading_id)
        self.assertEqual(self.transport.set_state.call_count, 2)

    def test_rejections_change_future_decision_and_survive_restart(self):
        self.setup_plate()
        ids = []
        for _ in range(3):
            _, decision_id, body, status = self.reading()
            ids.append(decision_id)
            self.assertEqual(status, 'executada')
            self.assertTrue(body['propostas'][0]['ligado'])
            response = self.client.post('/agente/feedback', json={'decisao_id': decision_id, 'gostei': False})
            self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(set(ids)), 3)
        # Rejeitar não dispara diretamente nenhum comando adicional.
        self.assertEqual(self.transport.set_state.call_count, 1)
        _, _, adapted, status = self.reading()
        self.assertEqual(status, 'executada')
        self.assertTrue(adapted['adaptado'])
        self.assertFalse(adapted['propostas'][0]['ligado'])
        self.transport.set_state.assert_called_with('192.168.2.9', 'ventilador', False)
        self.assertEqual(self.transport.set_state.call_count, 2)
        with self.store.session() as session:
            self.assertFalse(session.get(Device, ('teste', 'ventilador')).state)
            commands = list(session.scalars(select(Command).order_by(Command.created)))
            self.assertEqual([c.requested for c in commands], [3, 1])
            self.assertEqual(len(list(session.scalars(select(Feedback)))), 3)
            fan_key = adapted['propostas'][0]['alternativas'][1]['preferencia_chave']
            self.assertEqual(session.get(Preference, ('teste', fan_key)).value, -3)
        new_app = create_app({'DATABASE_URL': self.url, 'START_WORKER': False}, transport=self.transport)
        self.apps.append(new_app)
        preview = new_app.test_client().post('/agente/decidir', json={'modo': 'cognitivo'})
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertFalse(preview.json['decisao']['propostas'][0]['ligado'])
        self.assertTrue(preview.json['decisao']['adaptado'])
        self.assertFalse(preview.json['executado'])
        self.assertEqual(self.transport.set_state.call_count, 2)

    def test_feedback_duplicate_is_idempotent_conflicting_is_rejected(self):
        self.setup_plate()
        _, decision_id, body, _ = self.reading()
        key = body['propostas'][0]['preferencia_chave']
        first = self.client.post('/agente/feedback', json={'decisao_id': decision_id, 'gostei': True})
        duplicate = self.client.post('/agente/feedback', json={'decisao_id': decision_id, 'gostei': True})
        conflicting = self.client.post('/agente/feedback', json={'decisao_id': decision_id, 'gostei': False})
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json['idempotente'])
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json['idempotente'])
        self.assertEqual(conflicting.status_code, 409)
        with self.store.session() as session:
            self.assertEqual(session.get(Preference, ('teste', key)).value, 1)
            self.assertEqual(len(list(session.scalars(select(Feedback)))), 1)

    def test_sensor_origin_priority_and_manual_state_methods(self):
        self.setup_plate()
        invalid = self.client.get('/ajustar?temperatura=30&umidade=20')
        self.assertEqual(invalid.status_code, 409)
        self.transport.read.return_value = '0'
        _, _, body, _ = self.reading(temperature=33, humidity=20)
        self.assertTrue(body['propostas'][0]['ligado'])
        self.assertFalse(body['propostas'][1]['ligado'])
        self.transport.set_state.assert_called_once_with('192.168.2.9', 'ventilador', True)
        blocked = self.client.post('/umidificador/ligar')
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(self.transport.set_state.call_count, 1)
        off = self.client.post('/ventilador/desligar')
        self.assertEqual(off.status_code, 200)
        self.assertEqual(off.json['pulsos'], 1)
        second_off = self.client.post('/ventilador/desligar')
        self.assertEqual(second_off.status_code, 200)
        self.assertEqual(second_off.json['pulsos'], 0)
        self.assertEqual(self.transport.set_state.call_count, 2)

    def test_reactive_feedback_not_learned(self):
        self.setup_plate(mode='reativo')
        _, decision_id, _, status = self.reading()
        self.assertEqual(status, 'executada')
        response = self.client.post('/agente/feedback', json={'decisao_id': decision_id, 'gostei': True})
        self.assertEqual(response.status_code, 409)
        with self.store.session() as session:
            self.assertEqual(list(session.scalars(select(Preference))), [])


if __name__ == '__main__':
    unittest.main()
