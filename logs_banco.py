"""Consulta dos registros existentes; nao chama o controlador nem a ESP."""
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, render_template, request, url_for
from sqlalchemy import select

from storage import Command, Decision, Feedback, Plate, Reading, utc, utcnow


STATUS = {
    'pendente': 'Aguardando processamento', 'processando': 'Em processamento',
    'executada': 'Executada', 'incompleta': 'Incompleta',
    'automatico_pausado': 'Automático pausado', 'expirada': 'Leitura expirada',
    'substituida': 'Substituída por leitura mais recente', 'interrompida': 'Interrompida',
}
NOMES = {'ventilador': 'Ventilador', 'umidificador': 'Umidificador'}


def _dispositivo(nome, decisao, comando):
    proposta = next((p for p in decisao.body.get('propostas', [])
                     if p.get('dispositivo') == nome), {}) if decisao else {}
    resultado = next((r for r in decisao.body.get('resultados', [])
                      if r.get('dispositivo') == nome), {}) if decisao else {}
    estado, status, descricao = None, 'sem_decisao', 'Sem decisão registrada.'
    solicitados = confirmados = 0
    if comando is not None:
        solicitados, confirmados, status = comando.requested, comando.confirmed, comando.status
        acao = 'ligar' if comando.target else 'desligar'
        if status == 'confirmado':
            estado = comando.target
            descricao = f'{acao}: {confirmados}/{solicitados} pulsos confirmados.'
        elif status == 'executando':
            descricao = f'{acao}: execução em andamento; estado ainda não confirmado.'
        else:
            descricao = f'{acao}: {status}; {confirmados}/{solicitados} pulsos confirmados.'
            if comando.error:
                descricao += ' ' + comando.error
    elif resultado.get('status') == 'nao_executado':
        estado = proposta.get('estado_anterior')
        status, descricao = 'nao_executado', 'Não executado; automático pausado após falha em outro dispositivo.'
    elif proposta:
        if proposta.get('bloqueado'):
            status, descricao = 'estado_desconhecido', 'Estado desconhecido; sincronização necessária.'
        elif not proposta.get('alterar', True):
            estado = proposta.get('estado_anterior')
            status = 'mantido'
            descricao = 'Mantido ' + ('ligado' if estado else 'desligado') + '; sem envio de pulsos.'
        else:
            status, descricao = 'sem_confirmacao', 'Mudança proposta, sem comando confirmado.'
    label = 'Ligado' if estado is True else 'Desligado' if estado is False else 'Não confirmado'
    return {'estado_estimado': estado, 'rotulo': label, 'status': status,
            'pulsos_solicitados': solicitados, 'pulsos_confirmados': confirmados,
            'descricao': descricao, 'justificativa': proposta.get('justificativa', '')}


def instalar_logs(app, store):
    bp = Blueprint('logs_banco', __name__)
    timezone = ZoneInfo(app.config.get('TIMEZONE', 'America/Sao_Paulo'))

    def consultar():
        try:
            limite = int(request.args.get('limite', '100'))
        except ValueError:
            raise ValueError('limite deve ser um inteiro de 1 a 100.')
        if not 1 <= limite <= 100:
            raise ValueError('limite deve ser um inteiro de 1 a 100.')
        placa = request.args.get('placa') or None
        with store.session() as s:
            placas = list(s.scalars(select(Plate.name).order_by(Plate.name)))
            if placa is not None and placa not in placas:
                raise ValueError('Placa não encontrada.')
            recentes = select(Reading.id)
            if placa is not None:
                recentes = recentes.where(Reading.plate == placa)
            recentes = recentes.order_by(Reading.received.desc(), Reading.id.desc()).limit(limite)
            # O limite se aplica a leituras, antes da junção com os comandos.
            # Uma consulta reúne os dados no mesmo snapshot do PostgreSQL.
            rows = s.execute(
                select(Reading, Decision, Command, Feedback).select_from(Reading)
                .outerjoin(Decision, Decision.reading == Reading.id)
                .outerjoin(Command, Command.decision == Decision.id)
                .outerjoin(Feedback, Feedback.decision == Decision.id)
                .where(Reading.id.in_(recentes))
                .order_by(Reading.received.desc(), Reading.id.desc(), Decision.created.desc(),
                          Decision.id.desc(), Command.created.desc(), Command.id.desc())
            ).all()
            grouped = {}
            for reading, decision, command, feedback in rows:
                if reading.id not in grouped:
                    grouped[reading.id] = [reading, decision, feedback, {}]
                chosen = grouped[reading.id]
                if decision is not None and decision.id == chosen[1].id and command is not None:
                    chosen[3].setdefault(command.device, command)
            registros = []
            for reading, decision, feedback, commands in grouped.values():
                local = utc(reading.received).astimezone(timezone)
                registros.append({
                    'leitura_id': reading.id, 'placa': reading.plate, 'origem': reading.source,
                    'recebido': local.isoformat(), 'horario': local.strftime('%d/%m/%Y %H:%M:%S'),
                    'temperatura': reading.temperature, 'umidade': reading.humidity,
                    'nivel': reading.level,
                    'agua': 'Com água' if reading.level == 1 else 'Sem água' if reading.level == 0 else 'Não consultada',
                    'modo': decision.body.get('modo') if decision else None,
                    'status_leitura': reading.status, 'situacao': STATUS.get(reading.status, reading.status),
                    'erro_leitura': reading.error,
                    'decisao_id': decision.id if decision else None,
                    'decidido': utc(decision.created).astimezone(timezone).isoformat() if decision else None,
                    'status_decisao': decision.status if decision else None,
                    'feedback': feedback.liked if feedback else None,
                    'dispositivos': {nome: _dispositivo(nome, decision, commands.get(nome)) for nome in NOMES},
                })
        return {'placa': placa, 'placas': placas, 'limite': limite, 'quantidade': len(registros),
                'fuso': str(timezone), 'atualizacao_segundos': 30,
                'consultado': utcnow().astimezone(timezone).isoformat(), 'registros': registros}

    @bp.get('/log')
    def pagina():
        dados = consultar()
        return render_template('log.html', dados=dados, nomes=NOMES,
                               json_url=url_for('logs_banco.dados_json', limite=dados['limite'], placa=dados['placa']))

    @bp.get('/log/json')
    def dados_json():
        return jsonify(consultar())

    @bp.after_request
    def sem_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    app.register_blueprint(bp)
