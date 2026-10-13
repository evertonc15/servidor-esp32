"""Persistência do histórico, da fila e da aprendizagem (PostgreSQL)."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import threading

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        JSON, String, Text, create_engine, inspect, select, text)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class Plate(Base):
    __tablename__ = 'esp_placas'
    name = Column(String(64), primary_key=True)
    ip = Column(String(15), nullable=False, unique=True)
    updated = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    automatic = Column(Boolean, nullable=False, default=False)
    mode = Column(String(16), nullable=False, default='cognitivo')
    static_ip = Column(Boolean, nullable=False, default=False, server_default=text('false'))


class Device(Base):
    __tablename__ = 'esp_dispositivos'
    plate = Column(String(64), ForeignKey('esp_placas.name'), primary_key=True)
    name = Column(String(24), primary_key=True)
    state = Column(Boolean, nullable=True)
    synchronized = Column(DateTime(timezone=True), nullable=True)


class Reading(Base):
    __tablename__ = 'esp_leituras'
    id = Column(Integer, primary_key=True)
    plate = Column(String(64), ForeignKey('esp_placas.name'), nullable=False, index=True)
    temperature = Column(Float, nullable=False)
    humidity = Column(Float, nullable=False)
    level = Column(Integer, nullable=True)
    source = Column(String(15), nullable=False)
    received = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    ready = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(32), nullable=False, default='pendente', index=True)
    error = Column(Text, nullable=True)


class Decision(Base):
    __tablename__ = 'esp_decisoes'
    id = Column(String(36), primary_key=True)
    plate = Column(String(64), ForeignKey('esp_placas.name'), nullable=False, index=True)
    reading = Column(Integer, ForeignKey('esp_leituras.id'), nullable=False)
    created = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    body = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False)


class Command(Base):
    __tablename__ = 'esp_comandos'
    id = Column(String(36), primary_key=True)
    plate = Column(String(64), ForeignKey('esp_placas.name'), nullable=False, index=True)
    decision = Column(String(36), ForeignKey('esp_decisoes.id'), nullable=True)
    device = Column(String(24), nullable=False)
    target = Column(Boolean, nullable=False)
    requested = Column(Integer, nullable=False)
    confirmed = Column(Integer, nullable=False, default=0)
    attempted = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False)
    error = Column(Text, nullable=True)
    created = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished = Column(DateTime(timezone=True), nullable=True)


class Preference(Base):
    __tablename__ = 'esp_preferencias'
    plate = Column(String(64), ForeignKey('esp_placas.name'), primary_key=True)
    key = Column(String(512), primary_key=True)
    value = Column(Integer, nullable=False, default=0)


class Feedback(Base):
    __tablename__ = 'esp_feedbacks'
    decision = Column(String(36), ForeignKey('esp_decisoes.id'), primary_key=True)
    liked = Column(Boolean, nullable=False)
    created = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    changes = Column(JSON, nullable=False)


class Store:
    def __init__(self, url):
        options = {'pool_pre_ping': True}
        if url.startswith('postgresql'):
            options['connect_args'] = {'connect_timeout': 5}
        if url.startswith('sqlite'):
            options['connect_args'] = {'check_same_thread': False}
            if ':memory:' in url:
                options['poolclass'] = StaticPool
        self.engine = create_engine(url, **options)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self._locks = {}
        self._guard = threading.Lock()

    def initialize(self):
        Base.metadata.create_all(self.engine)
        # Migração pequena para instalações anteriores, preservando os dados.
        with self.engine.begin() as connection:
            if self.engine.dialect.name == 'postgresql':
                connection.execute(text('ALTER TABLE esp_placas ADD COLUMN IF NOT EXISTS static_ip BOOLEAN NOT NULL DEFAULT FALSE'))
            elif 'static_ip' not in {c['name'] for c in inspect(connection).get_columns('esp_placas')}:
                connection.execute(text('ALTER TABLE esp_placas ADD COLUMN static_ip BOOLEAN NOT NULL DEFAULT FALSE'))

    @contextmanager
    def session(self):
        with self.Session.begin() as session:
            yield session

    @contextmanager
    def lock(self, plate):
        """Serializa comandos por placa também entre processos PostgreSQL."""
        with self._guard:
            mutex = self._locks.setdefault(plate, threading.Lock())
        local_locked = mutex.acquire(blocking=False)
        acquired = local_locked
        connection = None
        pg_locked = False
        key = int.from_bytes(hashlib.sha256(plate.encode()).digest()[:8], 'big', signed=True)
        try:
            if acquired and self.engine.dialect.name == 'postgresql':
                connection = self.engine.connect()
                pg_locked = bool(connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}))
                acquired = pg_locked
            yield acquired
        finally:
            try:
                if connection is not None:
                    try:
                        if pg_locked:
                            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                    finally:
                        connection.close()
            finally:
                if local_locked:
                    mutex.release()

    def preferences(self, session, plate):
        return {p.key: p.value for p in session.scalars(select(Preference).where(Preference.plate == plate))}
