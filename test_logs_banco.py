"""Logs historicos, somente leitura e sem acesso ao hardware."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from sqlalchemy import event, select, func

from app import create_app
from storage import Command, Decision, Device, Feedback, Plate, Reading, utcnow


class LogsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.transport = Mock()
        database = 'sqlite:///' + str(Path(self.temp.name) / 'logs.sqlite3').replace('\\', '/')
        self.app = create_app({'DATABASE_URL': database, 'START_WORKER': False}, self.transport)
        self.client = self.app.test_client()
        self.store = self.app.extensions['store']

    def tearDown(self):
        self.app.extensions['controller'].stop()
        self.store.engine.dispose()
        self.temp.cleanup()

    def seed(self, failed=False, executing=False):
        with self.store.session() as s:
            s.add(Plate(name='teste', ip='192.168.2.5', mode='reativo'))
            s.flush()
            # Estado atual diferente do historico: a pagina nao pode usa-lo no passado.
            s.add(Device(plate='teste', name='ventilador', state=True))
            s.add(Device(plate='teste', name='umidificador', state=False))
            when = datetime(2026, 10, 14, 2, 6, tzinfo=timezone.utc)
            reading = Reading(plate='teste', temperature=22, humidity=42, level=1,
                              source='192.168.2.5', received=when, ready=when,
                              status='processando' if executing else 'incompleta' if failed else 'executada')
            s.add(reading)
            s.flush()
            self.reading_id = reading.id
            body = {'modo': 'cognitivo', 'propostas': [
                {'dispositivo': 'ventilador', 'estado_anterior': True, 'ligado': False,
                 'alterar': True, 'bloqueado': False, 'justificativa': 'Temperatura em 23 C ou menos.'},
                {'dispositivo': 'umidificador', 'estado_anterior': True, 'ligado': True,
                 'alterar': False, 'bloqueado': False, 'justificativa': 'Conservar estado.'}]}
            s.add(Decision(id='d1', plate='teste', reading=reading.id, created=when,
                           body=body, status=reading.status if not executing else 'executando'))
            s.flush()
            s.add(Command(id='c1', plate='teste', decision='d1', device='ventilador', target=False,
                          requested=1, confirmed=0 if failed or executing else 1,
                          attempted=1, status='executando' if executing else 'falhou' if failed else 'confirmado',
                          created=when, error='<script>alert(1)</script>' if failed else None))
            if not failed and not executing:
                s.add(Feedback(decision='d1', liked=True, changes=[]))
            s.add(Reading(plate='teste', temperature=24, humidity=45, level=None,
                          source='192.168.2.5', received=when+timedelta(minutes=2),
                          ready=when+timedelta(minutes=2), status='automatico_pausado'))

    def test_empty_and_bad_filters(self):
        self.assertEqual(self.client.get('/log').status_code, 200)
        self.assertIn('Nenhuma leitura registrada', self.client.get('/log').get_data(as_text=True))
        self.assertEqual(self.client.get('/log/json').json['registros'], [])
        for query in ('limite=0', 'limite=101', 'limite=abc', 'placa=inexistente'):
            self.assertEqual(self.client.get('/log/json?' + query).status_code, 400)
        self.transport.read.assert_not_called()
        self.transport.set_state.assert_not_called()

    def test_historical_states_paused_reading_and_no_side_effects(self):
        self.seed()
        statements = []
        def capture(conn, cursor, statement, params, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(self.store.engine, 'before_cursor_execute', capture)
        try:
            result = self.client.get('/log/json')
            html = self.client.get('/log')
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', capture)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(set(statements), {'SELECT'})
        self.assertEqual(result.headers['Cache-Control'], 'no-store')
        paused, previous = result.json['registros']
        self.assertIsNone(paused['modo'])
        self.assertIsNone(paused['dispositivos']['ventilador']['estado_estimado'])
        self.assertEqual(paused['agua'], 'Não consultada')
        self.assertEqual(previous['horario'], '13/10/2026 23:06:00')
        self.assertEqual(previous['modo'], 'cognitivo')
        self.assertFalse(previous['dispositivos']['ventilador']['estado_estimado'])
        self.assertEqual(previous['dispositivos']['ventilador']['pulsos_confirmados'], 1)
        self.assertTrue(previous['dispositivos']['umidificador']['estado_estimado'])
        self.assertEqual(previous['dispositivos']['umidificador']['status'], 'mantido')
        self.assertTrue(previous['feedback'])
        page = html.get_data(as_text=True)
        self.assertIn('http-equiv="refresh" content="30"', page)
        self.assertIn('sem envio de pulsos', page)
        self.assertIn('Automático pausado', page)
        self.assertIn('Gostei', page)
        with self.store.session() as s:
            self.assertTrue(s.get(Device, ('teste', 'ventilador')).state)
            self.assertEqual(s.scalar(select(func.count()).select_from(Command)), 1)
            self.assertEqual(s.scalar(select(func.count()).select_from(Reading)), 2)
        self.transport.read.assert_not_called()
        self.transport.set_state.assert_not_called()

    def test_partial_failure_is_unknown_and_error_is_html_escaped(self):
        self.seed(failed=True)
        record = self.client.get('/log/json').json['registros'][1]
        self.assertIsNone(record['dispositivos']['ventilador']['estado_estimado'])
        self.assertEqual(record['dispositivos']['ventilador']['status'], 'falhou')
        page = self.client.get('/log').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.transport.set_state.assert_not_called()

    def test_in_flight_command_does_not_claim_target_state(self):
        self.seed(executing=True)
        record = self.client.get('/log/json').json['registros'][1]
        self.assertIsNone(record['dispositivos']['ventilador']['estado_estimado'])
        self.assertIn('andamento', record['dispositivos']['ventilador']['descricao'])

    def test_limit_applies_to_readings_and_plate_filter(self):
        self.seed()
        with self.store.session() as s:
            s.add(Plate(name='outra', ip='192.168.2.8'))
            s.flush()
            now = utcnow()
            for index in range(102):
                s.add(Reading(plate='outra', temperature=27, humidity=50, source='192.168.2.8',
                              received=now+timedelta(seconds=index), ready=now, status='pendente'))
        self.assertEqual(self.client.get('/log/json').json['quantidade'], 100)
        result = self.client.get('/log/json?placa=teste&limite=1').json
        self.assertEqual(result['quantidade'], 1)
        self.assertEqual(result['registros'][0]['placa'], 'teste')
        self.assertEqual(result['registros'][0]['status_leitura'], 'automatico_pausado')
        self.assertIn('/log/json?limite=1&amp;placa=teste', self.client.get('/log?placa=teste&limite=1').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
