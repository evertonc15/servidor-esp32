"""Ponte HTTP para o firmware de pulsos; não presume estado físico."""
import http.client
import ipaddress
import socket
from copy import deepcopy
from threading import Lock

from flask import Blueprint, jsonify, request
from agente_peas import config, services

bp = Blueprint('esp_backend', __name__)
command_lock = Lock()


def consultar_esp(ip, caminho):
    # Somente IP registrado e rotas fixas; sem redirects, proxies ou retries.
    ip = str(ipaddress.IPv4Address(ip))
    conn = http.client.HTTPConnection(ip, 80, timeout=3)
    try:
        conn.request('GET', caminho)
        response = conn.getresponse()
        body = response.read(4096).decode('utf-8', errors='replace').strip()
        if response.status != 200:
            raise OSError(f'ESP32 respondeu HTTP {response.status}')
        return body
    finally:
        conn.close()


def instalar(app, database):
    def placa_alvo():
        nome = request.args.get('placa')
        with database() as conn:
            if nome:
                rows = conn.execute('SELECT * FROM placas WHERE placa=?', (nome,)).fetchall()
            else:
                rows = conn.execute('SELECT * FROM placas').fetchall()
        if len(rows) != 1:
            return None
        return dict(rows[0])

    def pulsar(dispositivo):
        placa = placa_alvo()
        if placa is None:
            return jsonify(erro='Registre a ESP32 em /meuip e informe ?placa=NOME se houver varias placas.'), 409
        # Requisições concorrentes não devem provocar pulsos duplicados.
        if not command_lock.acquire(blocking=False):
            return jsonify(erro='Outro comando esta em andamento.'), 409
        try:
            resposta = consultar_esp(placa['ip'], '/' + dispositivo)
            if resposta != 'OK':
                return jsonify(erro='Resposta inesperada da ESP32.', estado_fisico='desconhecido'), 502
            return jsonify(ok=True, placa=placa['placa'], dispositivo=dispositivo,
                           comando='pulso', estado_fisico='desconhecido', resposta_esp=resposta)
        except (OSError, http.client.HTTPException, socket.timeout):
            return jsonify(erro='Sem confirmacao da ESP32. O pulso pode ter ocorrido; nao repetir automaticamente.',
                           estado_fisico='desconhecido'), 502
        finally:
            command_lock.release()

    @bp.post('/ventilador')
    @bp.post('/interf/ligarventilador')
    def ventilador():
        return pulsar('ventilador')

    @bp.post('/umidificador')
    @bp.post('/interf/ligarumidificador')
    def umidificador():
        return pulsar('umidificador')

    @bp.get('/esp/conexao')
    def conexao():
        placa = placa_alvo()
        if placa is None:
            return jsonify(erro='Nenhuma placa unica selecionada. Registre em /meuip.'), 409
        try:
            nivel = consultar_esp(placa['ip'], '/nivel')
            if nivel not in ('0', '1'):
                raise OSError('Resposta inesperada')
            return jsonify(ok=True, placa=placa['placa'], ip=placa['ip'], nivel=int(nivel))
        except (OSError, http.client.HTTPException):
            return jsonify(erro='Nao foi possivel consultar /nivel na ESP32.'), 502

    @bp.post('/agente/decidir')
    def decidir():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {'modo'}:
            return jsonify(erro='Envie JSON com apenas modo: reativo ou cognitivo.'), 400
        modo = payload.get('modo', 'reativo')
        if modo not in ('reativo', 'cognitivo'):
            return jsonify(erro='Modo invalido.'), 400
        placa = placa_alvo()
        if placa is None:
            return jsonify(erro='Registre e selecione uma placa.'), 409
        with database() as conn:
            leitura = conn.execute('SELECT * FROM leituras WHERE origem=? ORDER BY id DESC LIMIT 1', (placa['ip'],)).fetchone()
        if leitura is None:
            return jsonify(erro='Nenhuma leitura recebida dessa placa em /ajustar.'), 409
        from datetime import datetime, timezone
        idade = (datetime.now(timezone.utc) - datetime.fromisoformat(leitura['recebido'])).total_seconds()
        if idade > 300:
            return jsonify(erro='Leitura antiga. Aguarde nova leitura da ESP32.'), 409
        state = deepcopy(config.estado_quarto)
        state['preset_atual'] = 'conforto'
        state['temperatura_interna'] = leitura['temperatura']
        state['umidade'] = leitura['umidade']
        decisao = services.make_decision(state, modo)
        return jsonify(decisao=decisao, executado=False,
                       leitura=dict(leitura),
                       contexto='Demais sensores e estados usam o preset conforto, nao medicoes reais.',
                       limitacao='Firmware possui pulsos, nao comandos de estado. Plano nao executado automaticamente.')

    app.register_blueprint(bp)
