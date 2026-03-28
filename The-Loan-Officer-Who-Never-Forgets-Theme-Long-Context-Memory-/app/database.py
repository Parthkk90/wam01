import json
import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, desc, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

logger = logging.getLogger(__name__)


def _to_async_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite+aiosqlite://"):
        return url
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


DEFAULT_DB_URL = "sqlite+aiosqlite:///./brainback.db"
RAW_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_URL = _to_async_database_url(RAW_DATABASE_URL) if RAW_DATABASE_URL else DEFAULT_DB_URL

engine = create_async_engine(DATABASE_URL, future=True, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class CallSession(Base):
    __tablename__ = "call_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    full_transcript: Mapped[str] = mapped_column(Text, default="")
    # Keep metadata generic and lightweight for webhook payload slices.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB().with_variant(Text, "sqlite"), nullable=True)

    turns: Mapped[list["TranscriptTurn"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(128), ForeignKey("call_sessions.call_id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow, index=True)

    session: Mapped[CallSession] = relationship(back_populates="turns")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Memory DB initialized at %s", DATABASE_URL)


def _metadata_for_storage(metadata: dict[str, Any] | None) -> dict[str, Any] | str | None:
    if metadata is None:
        return None
    if DATABASE_URL.startswith("sqlite+"):
        return json.dumps(metadata)
    return metadata


def _metadata_for_read(metadata: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if metadata is None:
        return None
    if isinstance(metadata, str):
        try:
            return json.loads(metadata)
        except Exception:
            return {"raw": metadata}
    return metadata


async def upsert_call_start(call_id: str, phone_number: str | None, metadata: dict[str, Any] | None = None) -> None:
    async with SessionLocal() as db:
        res = await db.execute(select(CallSession).where(CallSession.call_id == call_id))
        row = res.scalar_one_or_none()
        if row is None:
            row = CallSession(
                call_id=call_id,
                phone_number=phone_number,
                started_at=datetime.utcnow(),
                metadata_json=_metadata_for_storage(metadata),
            )
            db.add(row)
        else:
            row.phone_number = phone_number or row.phone_number
            if metadata:
                row.metadata_json = _metadata_for_storage(metadata)
        await db.commit()


async def add_transcript_turn(call_id: str, role: str, text: str) -> None:
    if not text.strip():
        return
    async with SessionLocal() as db:
        res = await db.execute(select(CallSession).where(CallSession.call_id == call_id))
        row = res.scalar_one_or_none()
        if row is None:
            row = CallSession(call_id=call_id, started_at=datetime.utcnow())
            db.add(row)

        turn = TranscriptTurn(call_id=call_id, role=role, text=text.strip())
        db.add(turn)
        await db.commit()


async def close_call(call_id: str, duration_seconds: int, full_transcript: str) -> None:
    async with SessionLocal() as db:
        res = await db.execute(select(CallSession).where(CallSession.call_id == call_id))
        row = res.scalar_one_or_none()
        if row is None:
            row = CallSession(call_id=call_id, started_at=datetime.utcnow())
            db.add(row)

        row.ended_at = datetime.utcnow()
        row.duration_seconds = int(duration_seconds or 0)
        row.full_transcript = full_transcript or ""
        await db.commit()


async def get_recent_memory_by_phone(phone_number: str, max_calls: int = 3, max_turns_per_call: int = 15) -> list[dict[str, Any]]:
    if not phone_number:
        return []

    async with SessionLocal() as db:
        res = await db.execute(
            select(CallSession)
            .where(CallSession.phone_number == phone_number)
            .order_by(desc(CallSession.started_at))
            .limit(max_calls)
        )
        sessions = res.scalars().all()

        output: list[dict[str, Any]] = []
        for session in sessions:
            turns_res = await db.execute(
                select(TranscriptTurn)
                .where(TranscriptTurn.call_id == session.call_id)
                .order_by(desc(TranscriptTurn.created_at))
                .limit(max_turns_per_call)
            )
            turns = list(reversed(turns_res.scalars().all()))

            output.append(
                {
                    "call_id": session.call_id,
                    "phone_number": session.phone_number,
                    "started_at": session.started_at.isoformat() if session.started_at else None,
                    "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                    "duration_seconds": session.duration_seconds,
                    "metadata": _metadata_for_read(session.metadata_json),
                    "turns": [{"role": t.role, "text": t.text, "created_at": t.created_at.isoformat()} for t in turns],
                }
            )

        return output