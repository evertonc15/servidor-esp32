import ipaddress
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
DATABASE = Path(os.environ.get('ESP32_DB', str(Path(__file__).with_name('dados.sqlite3'))))

@contextmanager
def db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS placas (placa TEXT PRIMARY KEY, ip TEXT, atualizado TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS leituras (id INTEGER PRIMARY KEY, temperatura REAL, umidade REAL, origem TEXT, recebido TEXT)')
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def agora():
    return datetime.now(timezone.utc).isoformat()

@app.get('/meuip')
def registrar_ip():
    placa = request.args.get('placa', '').strip()
    ip = request.args.get('ip', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', placa):
        return jsonify(erro='Informe placa com 1 a 64 letras, numeros, _ ou -.'), 400
    try:
        ip = str(ipaddress.IPv4Address(ip))
    except ValueError:
        return jsonify(erro='Informe um IPv4 valido no parametro ip.'), 400
    registro = dict(placa=placa, ip=ip, atualizado=agora())
    with db() as conn:
        conn.execute('INSERT INTO placas VALUES (:placa, :ip, :atualizado) ON CONFLICT(placa) DO UPDATE SET ip=excluded.ip, atualizado=excluded.atualizado', registro)
    return jsonify(ok=True, **registro)

@app.get('/placas')
def listar_placas():
    with db() as conn:
        registros = [dict(r) for r in conn.execute('SELECT * FROM placas ORDER BY placa')]
    return jsonify(registros)

@app.get('/ajustar')
def receber_leitura():
    try:
        t = float(request.args['temperatura'])
        u = float(request.args['umidade'])
        if not math.isfinite(t) or not math.isfinite(u) or not 0 <= u <= 100:
            raise ValueError()
    except (KeyError, ValueError):
        return jsonify(erro='Informe temperatura numerica e umidade entre 0 e 100.'), 400
    with db() as conn:
        conn.execute('INSERT INTO leituras (temperatura, umidade, origem, recebido) VALUES (?, ?, ?, ?)', (t, u, request.remote_addr, agora()))
    return jsonify(ok=True, temperatura=t, umidade=u)

@app.get('/temperatura')
def ultima_leitura():
    with db() as conn:
        registro = conn.execute('SELECT temperatura, umidade, origem, recebido FROM leituras ORDER BY id DESC LIMIT 1').fetchone()
    if registro is None:
        return jsonify(erro='Nenhuma leitura recebida.'), 404
    return jsonify(dict(registro))

@app.get('/')
def pagina():
    with db() as conn:
        placas = conn.execute('SELECT * FROM placas ORDER BY placa').fetchall()
    return render_template_string('''<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32 — Placas registradas</title>
<style>body{font:17px system-ui;max-width:900px;margin:50px auto;padding:20px;background:#f3f6fa;color:#172b42}table{width:100%;border-collapse:collapse;background:white}td,th{padding:16px;text-align:left;border-bottom:1px solid #ddd}a{color:#075db3}</style>
<h1>Placas ESP32</h1><p>Servidor na porta 5050. Atualize esta página para consultar novos registros.</p>
<table><tr><th>Placa</th><th>Endereço</th><th>Último registro (UTC)</th></tr>
{% for p in placas %}<tr><td>{{p.placa}}</td><td><a href="http://{{p.ip}}/">{{p.ip}}</a></td><td>{{p.atualizado}}</td></tr>
{% else %}<tr><td colspan="3">Nenhuma placa registrada ainda.</td></tr>{% endfor %}</table>
<p><a href="/placas">Consultar JSON das placas</a> · <a href="/temperatura">Última leitura do DHT11</a></p></html>''', placas=placas)

if __name__ == '__main__':
    from waitress import serve
    print('Servidor ESP32: http://localhost:5050', flush=True)
    serve(app, host='0.0.0.0', port=5050)
