"""API e painel mínimo. Decisões e comandos independem do navegador."""
from datetime import timedelta
import math
import re
from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, select
from agente_hardware import DISPOSITIVOS
from controller import Conflict
from esp_transport import validate_lan_ip
from storage import Command, Decision, Device, Feedback, Plate, Reading, utc, utcnow
from logs_banco import instalar_logs


def instalar(app, store, controller):
    bp = Blueprint('esp_backend', __name__)

    @bp.get('/identidade')
    def identidade():
        return 'ESP32_TCC_V1', 200, {'Content-Type': 'text/plain', 'Cache-Control': 'no-store'}

    @bp.get('/rede/status')
    def rede_status():
        discovery = app.extensions.get('discovery')
        return discovery.status() if discovery else {'ativo': False, 'erro': 'Anuncio mDNS nao iniciado neste processo.'}

    def plate_name():
        name = request.args.get('placa')
        with store.session() as s:
            names = list(s.scalars(select(Plate.name).where(Plate.name == name))) if name else list(s.scalars(select(Plate.name)))
        if len(names) != 1:
            raise Conflict('Registre a ESP32 em /meuip. Se houver varias, informe ?placa=NOME.')
        return names[0]

    def payload():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError('Envie um objeto JSON valido.')
        return value

    @bp.get('/meuip')
    def registrar_ip():
        name = request.args.get('placa', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
            raise ValueError('Nome de placa invalido.')
        ip = validate_lan_ip(request.args.get('ip'))
        fixed = request.args.get('ip_fixo')
        if fixed is not None and fixed not in ('0', '1'):
            raise ValueError('ip_fixo deve ser 0 ou 1.')
        with store.lock(name) as locked:
            if not locked:
                raise Conflict('Registro ocupado; tente no proximo ping.')
            with store.session() as s:
                other = s.scalar(select(Plate).where(Plate.ip == ip, Plate.name != name))
                if other:
                    raise Conflict('IP ja associado a outra placa.')
                p = s.get(Plate, name)
                if p is None:
                    p = Plate(name=name, ip=ip)
                    s.add(p)
                    s.flush()
                    for device in DISPOSITIVOS:
                        s.add(Device(plate=name, name=device))
                else:
                    recent = s.scalar(select(Reading).where(Reading.plate == name).order_by(Reading.id.desc()).limit(1))
                    last_seen = max(utc(p.updated), utc(recent.received)) if recent else utc(p.updated)
                    if p.ip != ip or (utcnow() - last_seen).total_seconds() > 300:
                        p.automatic = False
                        for d in s.scalars(select(Device).where(Device.plate == name)):
                            d.state = None
                p.ip, p.updated = ip, utcnow()
                if fixed is not None:
                    p.static_ip = fixed == '1'
                return {'ok': True, 'placa': name, 'ip': ip, 'ip_fixo': p.static_ip,
                        'atualizado': p.updated.isoformat()}

    @bp.get('/placas')
    def placas():
        with store.session() as s:
            return jsonify([{'placa': p.name, 'ip': p.ip, 'atualizado': utc(p.updated).isoformat(),
                             'automatico': p.automatic, 'modo': p.mode, 'ip_fixo': p.static_ip}
                            for p in s.scalars(select(Plate).order_by(Plate.name))])

    @bp.get('/ajustar')
    def receber_leitura():
        try:
            t, u = float(request.args['temperatura']), float(request.args['umidade'])
        except (KeyError, ValueError):
            raise ValueError('Informe temperatura e umidade numericas.')
        if not math.isfinite(t) or not math.isfinite(u) or not -40 <= t <= 80 or not 0 <= u <= 100:
            raise ValueError('Leitura fora dos limites aceitos.')
        source = request.remote_addr
        with store.session() as s:
            p = s.scalar(select(Plate).where(Plate.ip == source))
            if p is None:
                raise Conflict('IP de origem nao registrado; envie /meuip primeiro.')
            r = Reading(plate=p.name, temperature=t, humidity=u, source=source,
                        ready=utcnow() + timedelta(seconds=1))
            s.add(r)
            s.flush()
            return {'ok': True, 'temperatura': t, 'umidade': u, 'leitura_id': r.id, 'enfileirada': True}

    @bp.get('/temperatura')
    def temperatura():
        name = plate_name()
        with store.session() as s:
            r = s.scalar(select(Reading).where(Reading.plate == name).order_by(Reading.id.desc()).limit(1))
            if r is None:
                return {'erro': 'Nenhuma leitura recebida.'}, 404
            return {'temperatura': r.temperature, 'umidade': r.humidity, 'origem': r.source,
                    'recebido': utc(r.received).isoformat(), 'nivel': r.level, 'status': r.status}

    @bp.get('/esp/conexao')
    def conexao():
        name = plate_name()
        with store.session() as s:
            ip = s.get(Plate, name).ip
        value = controller.transport.read(ip, '/nivel')
        if value not in ('0', '1'):
            raise OSError('Resposta invalida da boia')
        return {'ok': True, 'placa': name, 'ip': ip, 'nivel': int(value)}

    @bp.post('/agente/sincronizar')
    def sincronizar():
        value = payload()
        controller.synchronize(plate_name(), value)
        return {'ok': True, 'estados_estimados': value, 'pulsos': 0}

    @bp.post('/agente/configurar')
    def configurar():
        name, value = plate_name(), payload()
        if set(value) - {'automatico', 'modo'} or not value:
            raise ValueError('Informe automatico e/ou modo.')
        if 'automatico' in value and type(value['automatico']) is not bool:
            raise ValueError('automatico deve ser true ou false.')
        if value.get('modo', 'cognitivo') not in ('reativo', 'cognitivo'):
            raise ValueError('Modo invalido.')
        with store.lock(name) as locked:
            if not locked:
                raise Conflict('Aguarde o ciclo atual terminar.')
            with store.session() as s:
                p = s.get(Plate, name)
                if value.get('automatico') and any(d.state is None for d in s.scalars(select(Device).where(Device.plate == name))):
                    raise Conflict('Sincronize os dois aparelhos antes de ativar.')
                p.automatic = value.get('automatico', p.automatic)
                p.mode = value.get('modo', p.mode)
                return {'ok': True, 'automatico': p.automatic, 'modo': p.mode}

    def command(device, target):
        result = controller.command(plate_name(), device, target)
        if result['status'] == 'estado_desconhecido':
            return result, 409
        if result['status'] == 'falhou':
            return result, 502
        return dict(result, ok=True)

    @bp.post('/ventilador/ligar')
    @bp.post('/ventilador')
    @bp.post('/interf/ligarventilador')
    def ligar_ventilador():
        return command('ventilador', True)

    @bp.post('/ventilador/desligar')
    @bp.post('/interf/desligarventilador')
    def desligar_ventilador():
        return command('ventilador', False)

    @bp.post('/umidificador/ligar')
    @bp.post('/umidificador')
    @bp.post('/interf/ligarumidificador')
    def ligar_umidificador():
        return command('umidificador', True)

    @bp.post('/umidificador/desligar')
    @bp.post('/interf/desligarumidificador')
    def desligar_umidificador():
        return command('umidificador', False)

    @bp.post('/agente/decidir')
    def decidir():
        value = payload()
        if set(value) - {'modo'}:
            raise ValueError('Informe apenas modo.')
        return {'decisao': controller.preview(plate_name(), value.get('modo')), 'executado': False}

    @bp.post('/agente/feedback')
    @bp.post('/interf/feedback')
    def feedback():
        value = payload()
        if set(value) != {'decisao_id', 'gostei'} or not isinstance(value['decisao_id'], str):
            raise ValueError('Informe decisao_id e gostei booleano.')
        return controller.feedback(value['decisao_id'], value['gostei'])

    @bp.get('/agente/status')
    @bp.get('/status')
    def status():
        name = plate_name()
        with store.session() as s:
            p = s.get(Plate, name)
            d = s.scalar(select(Decision).where(Decision.plate == name).order_by(Decision.created.desc()).limit(1))
            states = {d.name: d.state for d in s.scalars(select(Device).where(Device.plate == name))}
            feedback = s.get(Feedback, d.id) if d else None
            return {'placa': name, 'ip': p.ip, 'automatico': p.automatic, 'modo': p.mode,
                    'ip_fixo': p.static_ip,
                    'estados_estimados': states, 'preferencias': store.preferences(s, name),
                    'decisao': None if not d else dict(d.body, decisao_id=d.id, status=d.status),
                    'feedback': None if feedback is None else feedback.liked}

    @bp.get('/historico')
    def historico():
        name = plate_name()
        with store.session() as s:
            decisions = s.scalars(select(Decision).where(Decision.plate == name).order_by(Decision.created.desc()).limit(50))
            return jsonify([{'decisao_id': d.id, 'criado': utc(d.created).isoformat(), 'status': d.status, **d.body} for d in decisions])

    @bp.get('/analise')
    def analise():
        name = plate_name()
        with store.session() as s:
            counts = {label: s.scalar(select(func.count()).select_from(model).where(field == name))
                      for label, model, field in [('leituras', Reading, Reading.plate),
                                                 ('decisoes', Decision, Decision.plate),
                                                 ('comandos', Command, Command.plate)]}
            counts['feedbacks'] = s.scalar(select(func.count()).select_from(Feedback).join(Decision).where(Decision.plate == name))
            counts['comandos_falhos'] = s.scalar(select(func.count()).select_from(Command).where(Command.plate == name, Command.status == 'falhou'))
            means = s.execute(select(func.avg(Reading.temperature), func.avg(Reading.humidity)).where(Reading.plate == name)).one()
            return {'placa': name, 'contagens': counts, 'medias': {'temperatura': means[0], 'umidade': means[1]}}

    @bp.get('/')
    @bp.get('/agente')
    def pagina():
        return render_template('painel.html')

    app.register_blueprint(bp)
    instalar_logs(app, store)
