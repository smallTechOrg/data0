from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Integer, Text, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class DatasetRow(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    col_count: Mapped[int] = mapped_column(Integer, nullable=False)
    columns_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    derived_from_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    derived_from_dataset_ids: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    derivation_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    parquet_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_notes_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_facts: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    # C36 (Phase 9) — external database connector provenance. All nullable;
    # only set when origin="connected". source_uri_raw is secret-bearing (see
    # spec/data.md + spec/capabilities/external-db-connectors.md -> "Credential
    # Hygiene") and MUST NEVER be included in any API response.
    source_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_uri_display: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_table_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_uri_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class QueryRunRow(Base):
    __tablename__ = "query_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_history: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # C39 — cache-served subset of tokens_input (0 <= tokens_cached <= tokens_input).
    # Nullable with server-default '0' so pre-Phase-14 rows read as 0; API reads
    # use `or 0` defensively (spec/data.md).
    tokens_cached: Mapped[int | None] = mapped_column(
        Integer, nullable=True, server_default="0"
    )
    prompt_breakdown: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    charts_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    dataset_ids_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    selector_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    fast_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class ConversationSessionRow(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_ids_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )
