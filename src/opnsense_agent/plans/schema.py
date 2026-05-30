"""Pydantic models for plans, ops, and execution state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanStatus(StrEnum):
    draft = "draft"
    applied = "applied"
    failed = "failed"
    rolled_back = "rolled_back"


class PlanOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class PlanTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    api_user: str | None = None


class OpResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    status: str
    response: dict[str, Any] | None = None
    error: str | None = None


class PlanExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_id: str | None = None
    applied_at: datetime | None = None
    results: list[OpResult] = Field(default_factory=list)
    rollback_reason: str | None = None


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    description: str
    created: datetime
    status: PlanStatus = PlanStatus.draft
    target: PlanTarget
    ops: list[PlanOp] = Field(min_length=1)
    execution: PlanExecution = Field(default_factory=PlanExecution)
