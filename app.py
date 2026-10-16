"""Servidor do TCC: sensores -> agente PEAS -> ESP32 -> feedback persistente."""
import logging
import http.client
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

from controller import Controller, Conflict
from esp_backend import instalar
from storage import Store
from esp_transport import EspTransport


def create_app(config=None, transport=None):
    load_dotenv(Path(__file__).with_name('.env'))
    app = Flask(__name__)
    app.config.update(DATABASE_URL=os.getenv('DATABASE_URL'), START_WORKER=True,
                      SENSOR_MAX_AGE=300, TIMEZONE='America/Sao_Paulo',
                      ESP_COMMAND_TIMEOUT=os.getenv('ESP_COMMAND_TIMEOUT', '10'))
    if config:
        app.config.update(config)
    if not app.config['DATABASE_URL']:
        raise RuntimeError('Configure DATABASE_URL no arquivo .env. Veja README.md ou execute preparar_banco.py.')
    store = Store(app.config['DATABASE_URL'])
    store.initialize()
    if transport is None:
        transport = EspTransport(command_timeout=app.config['ESP_COMMAND_TIMEOUT'])
    controller = Controller(store, transport, app.config['SENSOR_MAX_AGE'], app.config['TIMEZONE'])
    app.extensions.update(store=store, controller=controller)
    instalar(app, store, controller)

    @app.errorhandler(Conflict)
    def conflict(error):
        return {'erro': str(error)}, 409

    @app.errorhandler(ValueError)
    def bad_input(error):
        return {'erro': str(error)}, 400

    @app.errorhandler(OSError)
    @app.errorhandler(http.client.HTTPException)
    def unreachable(error):
        return {'erro': 'ESP32 indisponivel; confira IP e conexao.'}, 502

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        app.logger.error('Falha de banco: %s', type(error).__name__)
        return {'erro': 'Banco de dados indisponivel.'}, 503

    if app.config['START_WORKER']:
        controller.start()
    return app


if __name__ == '__main__':
    from waitress import serve
    from preparar_banco import ensure_database
    from network_discovery import ServerDiscovery
    logging.basicConfig(level=logging.INFO)
    try:
        ensure_database()
        app = create_app()
    except (RuntimeError, SQLAlchemyError):
        raise SystemExit('Nao foi possivel iniciar o banco. Confira .env e README.md.') from None
    print('Servidor ESP32: http://localhost:5050', flush=True)
    discovery = None
    try:
        discovery = ServerDiscovery(network=os.getenv('DISCOVERY_NETWORK', '192.168.2.0/24'),
                                    esp_ip=os.getenv('ESP_FIXED_IP', '192.168.2.5'))
        app.extensions['discovery'] = discovery
        discovery.start()
        serve(app, host='0.0.0.0', port=5050)
    finally:
        if discovery is not None:
            discovery.stop()
        app.extensions['controller'].stop()
