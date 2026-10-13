"""Decisão e execução automática em fila, independente da interface."""
from datetime import datetime, timedelta, timezone
import logging
import http.client
import threading
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from agente_hardware import DISPOSITIVOS, aprender, decidir
from esp_transport import EspTransport, PulseError
from storage import Command, Decision, Device, Feedback, Plate, Preference, Reading, utc, utcnow


class Conflict(ValueError):
    pass


class Controller:
    def __init__(self, store, transport=None, max_age=300, timezone_name='America/Sao_Paulo'):
        self.store = store
        self.transport = transport or EspTransport()
        self.max_age = max_age
        self.timezone = ZoneInfo(timezone_name)
        self.stop_event = threading.Event()
        self.thread = None
        self.log = logging.getLogger('agente')

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._worker, daemon=True, name='agente-esp32')
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _worker(self):
        while not self.stop_event.wait(0.5):
            try:
                self.process_pending()
            except Exception:
                self.log.exception('Falha na fila do agente')

    def process_pending(self):
        with self.store.session() as s:
            ids = list(s.scalars(select(Reading.id).where(
                Reading.status == 'pendente', Reading.ready <= utcnow()
            ).order_by(Reading.id).limit(20)))
        for reading_id in ids:
            self.process_reading(reading_id)

    def _snapshot(self, s, plate, reading, mode, level):
        states = {d.name: d.state for d in s.scalars(select(Device).where(Device.plate == plate.name))}
        return decidir({'temperatura': reading.temperature, 'umidade': reading.humidity, 'nivel': level},
                       states, self.store.preferences(s, plate.name), mode,
                       datetime.now(self.timezone).hour)

    def process_reading(self, reading_id):
        with self.store.session() as s:
            r = s.get(Reading, reading_id)
            if r is None or r.status != 'pendente':
                return
            name = r.plate
        with self.store.lock(name) as locked:
            if not locked:
                return
            with self.store.session() as s:
                r = s.get(Reading, reading_id)
                if r.status != 'pendente':
                    return
                if (utcnow() - utc(r.received)).total_seconds() > self.max_age:
                    r.status = 'expirada'
                    return
                newer = s.scalar(select(Reading.id).where(Reading.plate == name, Reading.id > r.id).limit(1))
                if newer:
                    r.status = 'substituida'
                    return
                plate = s.get(Plate, name)
                if not plate.automatic:
                    r.status = 'automatico_pausado'
                    return
                ip, mode = plate.ip, plate.mode
            # O atraso da fila e a consulta de boia dão tempo ao HTTPClient da ESP.
            # Esta leitura é repetível: não aciona relés.
            try:
                level_text = self.transport.read(ip, '/nivel')
                if level_text not in ('0', '1'):
                    raise OSError('Resposta invalida da boia')
                level = int(level_text)
            except (OSError, http.client.HTTPException):
                with self.store.session() as s:
                    r = s.get(Reading, reading_id)
                    r.error = 'Nao foi possivel consultar a boia.'
                    r.ready = utcnow() + timedelta(seconds=10)
                return
            with self.store.session() as s:
                r = s.get(Reading, reading_id)
                plate = s.get(Plate, name)
                if r.status != 'pendente':
                    return
                if (utcnow() - utc(r.received)).total_seconds() > self.max_age:
                    r.status = 'expirada'
                    return
                if s.scalar(select(Reading.id).where(Reading.plate == name, Reading.id > r.id).limit(1)):
                    r.status = 'substituida'
                    return
                # Registro/IP pode mudar enquanto a leitura HTTP está em andamento.
                if plate.ip != ip or not plate.automatic:
                    return
                plan = self._snapshot(s, plate, r, mode, level)
                decision_id = str(uuid4())
                s.add(Decision(id=decision_id, plate=name, reading=r.id, body=plan, status='executando'))
                r.level = level
                r.status = 'processando'
            results = []
            for proposal in plan['propostas']:
                if proposal['bloqueado']:
                    results.append({'dispositivo': proposal['dispositivo'], 'status': 'estado_desconhecido'})
                    continue
                if not proposal['alterar']:
                    results.append({'dispositivo': proposal['dispositivo'], 'status': 'mantido'})
                    continue
                results.append(self._command(name, proposal['dispositivo'], proposal['ligado'], decision_id))
            failed = any(r['status'] in ('falhou', 'estado_desconhecido') for r in results)
            with self.store.session() as s:
                d = s.get(Decision, decision_id)
                d.body = dict(plan, resultados=results)
                d.status = 'incompleta' if failed else 'executada'
                s.get(Reading, reading_id).status = d.status

    def preview(self, name, mode=None):
        with self.store.session() as s:
            plate = s.get(Plate, name)
            reading = s.scalar(select(Reading).where(Reading.plate == name).order_by(Reading.id.desc()).limit(1))
            if reading is None or (utcnow() - utc(reading.received)).total_seconds() > self.max_age:
                raise Conflict('Aguarde uma leitura recente da ESP32.')
            ip = plate.ip
        level = self.transport.read(ip, '/nivel')
        if level not in ('0', '1'):
            raise OSError('Resposta invalida da boia')
        with self.store.session() as s:
            return self._snapshot(s, s.get(Plate, name), reading, mode or plate.mode, int(level))

    def command(self, name, device, target):
        if device not in DISPOSITIVOS or type(target) is not bool:
            raise ValueError('Dispositivo ou comando invalido.')
        with self.store.lock(name) as locked:
            if not locked:
                raise Conflict('Outro comando desta placa esta em andamento.')
            # Confere disponibilidade antes de enviar a sequência.
            with self.store.session() as s:
                ip = s.get(Plate, name).ip
            level = self.transport.read(ip, '/nivel')
            if level not in ('0', '1'):
                raise OSError('Resposta invalida da boia')
            if device == 'umidificador' and target and level != '1':
                raise Conflict('Sem agua: ligar o umidificador esta bloqueado.')
            return self._command(name, device, target)

    def _command(self, name, device, target, decision_id=None):
        with self.store.session() as s:
            plate = s.get(Plate, name)
            d = s.get(Device, (name, device))
            if d.state is None:
                return {'dispositivo': device, 'status': 'estado_desconhecido', 'erro': 'Sincronize o estado fisico antes de enviar pulsos.'}
            if d.state == target:
                return {'dispositivo': device, 'status': 'mantido', 'pulsos': 0, 'ligado_estimado': target}
            # Salva intenção e estado incerto ANTES de atuar: crash nunca repete.
            cmd_id = str(uuid4())
            ip = plate.ip
            s.add(Command(id=cmd_id, plate=name, decision=decision_id, device=device, target=target,
                          requested=3 if target else 1, status='executando'))
            d.state = None
        try:
            count = self.transport.set_state(ip, device, target)
        except PulseError as error:
            with self.store.session() as s:
                c = s.get(Command, cmd_id)
                c.status, c.error = 'falhou', str(error)
                c.confirmed, c.attempted = error.confirmed, error.attempted
                c.finished = utcnow()
            return {'dispositivo': device, 'status': 'falhou', 'comando_id': cmd_id,
                    'pulsos_confirmados': error.confirmed, 'estado_estimado': None}
        with self.store.session() as s:
            c = s.get(Command, cmd_id)
            c.status, c.confirmed, c.attempted = 'confirmado', count, count
            c.finished = utcnow()
            d = s.get(Device, (name, device))
            d.state = target
        return {'dispositivo': device, 'status': 'confirmado', 'comando_id': cmd_id,
                'pulsos': count, 'ligado_estimado': target, 'estado_fisico': 'nao_medido'}

    def synchronize(self, name, states):
        if set(states) != set(DISPOSITIVOS) or any(type(v) is not bool for v in states.values()):
            raise ValueError('Informe ventilador e umidificador como booleanos.')
        with self.store.lock(name) as locked:
            if not locked:
                raise Conflict('Espere o comando em andamento terminar.')
            with self.store.session() as s:
                for device, state in states.items():
                    d = s.get(Device, (name, device))
                    d.state, d.synchronized = state, utcnow()
                s.execute(update(Command).where(Command.plate == name, Command.status == 'executando').values(
                    status='interrompido', error='Execucao interrompida; estado ressincronizado pelo usuario.'))
                s.execute(update(Decision).where(Decision.plate == name, Decision.status == 'executando').values(status='interrompida'))
                s.execute(update(Reading).where(Reading.plate == name, Reading.status == 'processando').values(status='interrompida'))

    def feedback(self, decision_id, liked):
        if type(liked) is not bool:
            raise ValueError('gostei deve ser true ou false.')
        with self.store.session() as s:
            d = s.get(Decision, decision_id)
            if d is None:
                raise Conflict('Decisao inexistente.')
            plate = d.plate
        with self.store.lock(plate) as locked:
            if not locked:
                raise Conflict('Aguarde o ciclo terminar antes de enviar feedback.')
            with self.store.session() as s:
                d = s.get(Decision, decision_id)
                if d.status != 'executada' or d.body['modo'] != 'cognitivo':
                    raise Conflict('Feedback adaptativo requer decisao cognitiva executada.')
                existing = s.get(Feedback, decision_id)
                if existing:
                    if existing.liked != liked:
                        raise Conflict('Esta decisao ja recebeu outro feedback.')
                    return {'ok': True, 'idempotente': True, 'aprendizagem': existing.changes}
                preferences = self.store.preferences(s, plate)
                changes = []
                for proposal in d.body['propostas']:
                    if proposal['prioridade_reativa']:
                        continue
                    key = proposal['preferencia_chave']
                    learned = aprender(preferences, key, liked)
                    entry = s.get(Preference, (plate, key))
                    if entry is None:
                        s.add(Preference(plate=plate, key=key, value=learned['preferencia_atual']))
                    else:
                        entry.value = learned['preferencia_atual']
                    changes.append(dict(learned, dispositivo=proposal['dispositivo']))
                s.add(Feedback(decision=decision_id, liked=liked, changes=changes))
                return {'ok': True, 'idempotente': False, 'aprendizagem': changes}
