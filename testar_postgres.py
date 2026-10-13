"""Executa a suite funcional em schemas temporários no PostgreSQL local."""
import os
import unittest
from pathlib import Path
from dotenv import dotenv_values
from preparar_banco import ensure_database

if __name__ == '__main__':
    ensure_database()
    root = Path(__file__).resolve().parent
    settings = dotenv_values(root / '.env')
    if not settings.get('DATABASE_URL', '').startswith('postgresql'):
        raise SystemExit('Configure o PostgreSQL em .env primeiro.')
    os.environ['TEST_DATABASE_URL'] = settings['DATABASE_URL']
    suite = unittest.defaultTestLoader.discover(str(root), pattern='test_backend.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
