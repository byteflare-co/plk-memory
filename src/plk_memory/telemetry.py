"""Storage-neutral search and decision telemetry contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

DecisionEffect = Literal["changed_action", "prevented_error", "confirmed", "none"]
NoUseReason = Literal[
    "irrelevant",
    "already_known",
    "stale",
    "conflict",
    "insufficient",
]


class TelemetryError(RuntimeError):
    """A caller-visible telemetry contract error."""


class TelemetryConflict(TelemetryError):
    """An idempotency key or search was already used incompatibly."""


class FactReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str = Field(min_length=1, max_length=64)
    revision: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)


class DecisionCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(min_length=1, max_length=64)
    search_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    used_fact_ids: tuple[str, ...] = Field(default=(), max_length=100)
    effect: DecisionEffect
    no_use_reason: NoUseReason | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "DecisionCommand":
        if len(set(self.search_ids)) != len(self.search_ids):
            raise ValueError("search_ids must not contain duplicates")
        if len(set(self.used_fact_ids)) != len(self.used_fact_ids):
            raise ValueError("used_fact_ids must not contain duplicates")
        if self.effect == "none":
            if self.used_fact_ids:
                raise ValueError("effect=none requires used_fact_ids=[]")
            if self.no_use_reason is None:
                raise ValueError("effect=none requires no_use_reason")
        else:
            if not self.used_fact_ids:
                raise ValueError(f"effect={self.effect} requires used_fact_ids")
            if self.no_use_reason is not None:
                raise ValueError("no_use_reason is allowed only when effect=none")
        return self

    def request_hash(self) -> str:
        canonical = self.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


class TelemetryStore(Protocol):
    async def record_search(
        self,
        *,
        client: str,
        search_id: str,
        query: str,
        hits: int,
        latency_ms: int,
        reason: str | None,
        fact_refs: list[FactReference],
        outcome: str,
    ) -> None: ...

    async def record_decision(
        self,
        *,
        client: str,
        command: DecisionCommand,
    ) -> dict: ...

    async def list_usage(self) -> list[dict]: ...
