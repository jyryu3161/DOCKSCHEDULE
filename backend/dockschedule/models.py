from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid():
    return uuid4().hex


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    student_number: Mapped[str] = mapped_column(String(80), default='')
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default='student')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    cpu_override: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LoginSession(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Settings(Base):
    __tablename__ = 'settings'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
    available_cpus: Mapped[list] = mapped_column(JSON, default=list)
    scheduler_error: Mapped[str | None] = mapped_column(Text)


class Upload(Base):
    __tablename__ = 'uploads'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(250))
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Receptor(Base):
    __tablename__ = 'receptors'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    upload_id: Mapped[str] = mapped_column(ForeignKey('uploads.id'))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default='queued')
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    structure: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    receptor_id: Mapped[str] = mapped_column(ForeignKey('receptors.id'), index=True)
    library_id: Mapped[str | None] = mapped_column(ForeignKey('uploads.id'))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[str | None] = mapped_column(String(32))
    cpu_ids: Mapped[list] = mapped_column(JSON, default=list)
    worker_pid: Mapped[int | None] = mapped_column(Integer)
    worker_created: Mapped[float | None] = mapped_column(Float)
    artifact_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    log_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime)


class Compound(Base):
    __tablename__ = 'compounds'
    __table_args__ = (UniqueConstraint('task_id', 'row_number'),
                     Index('compound_results', 'task_id', 'affinity'),
                     Index('compound_status', 'task_id', 'status', 'row_number'))
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'))
    row_number: Mapped[int] = mapped_column(Integer)
    cid: Mapped[str] = mapped_column(Text)
    smiles: Mapped[str] = mapped_column(Text)
    normalized_smiles: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    affinity: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    artifact_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    elapsed: Mapped[float | None] = mapped_column(Float)


class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


ACTIVE = ('reserved', 'running')
FINISHED = ('completed', 'partial', 'failed', 'cancelled')
