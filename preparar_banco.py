"""Cria banco PostgreSQL dedicado; não altera o serviço PostgreSQL existente."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess

from dotenv import dotenv_values
import psycopg

ROOT = Path(__file__).resolve().parent
DATA = ROOT / '.postgres-data'


def run(args, **kwargs):
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def ensure_database():
    settings = dotenv_values(ROOT / '.env')
    pg_bin = settings.get('LOCAL_PG_BIN')
    if not pg_bin or not (DATA / 'PG_VERSION').exists():
        return
    bin_dir = Path(pg_bin)
    suffix = '.exe' if os.name == 'nt' else ''
    status = subprocess.run([str(bin_dir / ('pg_ctl' + suffix)), '-D', str(DATA), 'status'], capture_output=True)
    if status.returncode != 0:
        run([bin_dir / ('pg_ctl' + suffix), '-D', DATA, '-l', ROOT / 'postgres.log', '-w', 'start'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--docker', action='store_true')
    parser.add_argument('--pg-bin', default=r'C:\Program Files\PostgreSQL\17\bin')
    args = parser.parse_args()
    env_path = ROOT / '.env'
    if not env_path.exists():
        password = secrets.token_hex(24)
        settings = f'DATABASE_URL=postgresql+psycopg://esp32:{password}@127.0.0.1:55432/servidor_esp32\nPOSTGRES_USER=esp32\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=servidor_esp32\n'
        if not args.docker:
            settings += f'LOCAL_PG_BIN={args.pg_bin}\n'
        env_path.write_text(settings, encoding='utf-8')
    settings = dotenv_values(env_path)
    if args.docker:
        run(['docker', 'compose', 'up', '-d', '--wait', 'postgres'], cwd=ROOT)
    else:
        bin_dir = Path(args.pg_bin)
        suffix = '.exe' if os.name == 'nt' else ''
        if not (bin_dir / ('initdb' + suffix)).exists():
            raise SystemExit('PostgreSQL nativo nao encontrado. Use --pg-bin ou --docker.')
        if not (DATA / 'PG_VERSION').exists():
            pwfile = ROOT / '.postgres-password'
            try:
                pwfile.write_text(settings['POSTGRES_PASSWORD'], encoding='utf-8')
                run([bin_dir / ('initdb' + suffix), '-D', DATA, '-U', settings['POSTGRES_USER'],
                     '--auth=scram-sha-256', '--pwfile', pwfile, '--encoding=UTF8', '--no-locale'])
            finally:
                pwfile.unlink(missing_ok=True)
            with (DATA / 'postgresql.conf').open('a', encoding='utf-8') as f:
                f.write("\nlisten_addresses = '127.0.0.1'\nport = 55432\n")
        ensure_database()
    if not args.docker:
        with psycopg.connect(host='127.0.0.1', port=55432, user=settings['POSTGRES_USER'],
                             password=settings['POSTGRES_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5) as conn:
            exists = conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (settings['POSTGRES_DB'],)).fetchone()
            if not exists:
                conn.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(settings['POSTGRES_DB'])))
    print('Banco servidor_esp32 preparado em 127.0.0.1:55432. Credenciais salvas apenas no .env local.')


if __name__ == '__main__':
    main()
