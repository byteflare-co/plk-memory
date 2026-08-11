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
PlkRequirement = Literal["required", "optional", "not_required"]
NoSearchReason = Literal[
    "not_applicable",
    "fresh_primary_source",
    "no_decision",
    "service_unavailable",
]
ActionPhase = Literal["attempted", "completed"]
ActionOutcome = Literal[
    "pending",
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
]
SideEffect = Literal["read", "local_write", "external_write", "destructive"]


def _request_hash(command: BaseModel) -> str:
    canonical = command.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class TelemetryError(RuntimeError):
    """A caller-visible telemetry contract error."""


class TelemetryConflict(TelemetryError):
    """An idempotency key or search was already used incompatibly."""


class FactReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str = Field(min_length=1, max_length=64)
    revision: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)


class IntentCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(min_length=1, max_length=64)
    operation_type: str = Field(min_length=1, max_length=64)
    intent: str = Field(min_length=1, max_length=500)
    target: str | None = Field(default=None, max_length=500)
    side_effect: SideEffect
    plk_requirement: PlkRequirement
    no_search_reason: NoSearchReason | None = None

    @model_validator(mode="after")
    def validate_requirement(self) -> "IntentCommand":
        if (
            self.side_effect in {"external_write", "destructive"}
            and self.plk_requirement != "required"
        ):
            raise ValueError(
                f"side_effect={self.side_effect} requires plk_requirement=required"
            )
        if self.plk_requirement == "not_required":
            if self.no_search_reason is None:
                raise ValueError(
                    "plk_requirement=not_required requires no_search_reason"
                )
        elif self.no_search_reason is not None:
            raise ValueError(
                "no_search_reason is allowed only when PLK is not required"
            )
        return self

    def request_hash(self) -> str:
        return _request_hash(self)


class ActionCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=64)
    trace_id: str = Field(min_length=1, max_length=64)
    phase: ActionPhase
    action_type: str = Field(min_length=1, max_length=64)
    tool_name: str | None = Field(default=None, max_length=255)
    target: str | None = Field(default=None, max_length=500)
    side_effect: SideEffect
    outcome: ActionOutcome
    decision_id: str | None = Field(default=None, max_length=64)
    error_category: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_phase(self) -> "ActionCommand":
        if self.phase == "attempted" and self.outcome != "pending":
            raise ValueError("phase=attempted requires outcome=pending")
        if self.phase == "completed" and self.outcome == "pending":
            raise ValueError("phase=completed requires a terminal outcome")
        if self.outcome != "failed" and self.error_category is not None:
            raise ValueError("error_category is allowed only when outcome=failed")
        return self

    def request_hash(self) -> str:
        return _request_hash(self)


class DecisionCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(min_length=1, max_length=64)
    search_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    used_fact_ids: tuple[str, ...] = Field(default=(), max_length=100)
    effect: DecisionEffect
    no_use_reason: NoUseReason | None = None
    trace_id: str | None = Field(default=None, min_length=1, max_length=64)

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
        trace_id: str | None = None,
    ) -> None: ...

    async def record_intent(self, *, client: str, command: IntentCommand) -> dict: ...

    async def record_decision(
        self,
        *,
        client: str,
        command: DecisionCommand,
    ) -> dict: ...

    async def record_action(self, *, client: str, command: ActionCommand) -> dict: ...

    async def list_usage(self) -> list[dict]: ...
