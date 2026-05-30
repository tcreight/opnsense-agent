from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from opnsense_agent.plans.schema import Plan, PlanStatus

SAMPLE_YAML = """
plan_id: 2026-05-03T14-30-22Z-iot-vlan
description: Stand up VLAN 30 for IoT
created: 2026-05-03T14:30:22Z
status: draft
target:
  host: opnsense.lan
  api_user: claude-agent
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1, description: "IoT" }
execution:
  backup_id: null
  applied_at: null
  results: []
  rollback_reason: null
"""


def test_parses_valid_plan() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    plan = Plan.model_validate(data)
    assert plan.plan_id == "2026-05-03T14-30-22Z-iot-vlan"
    assert plan.status is PlanStatus.draft
    assert len(plan.ops) == 1
    assert plan.ops[0].op == "vlan.create"
    assert plan.ops[0].params["tag"] == 30


def test_rejects_unknown_status() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    data["status"] = "exploded"
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_rejects_empty_ops() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    data["ops"] = []
    with pytest.raises(ValidationError, match="at least 1"):
        Plan.model_validate(data)


def test_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        Plan.model_validate({"plan_id": "x"})


def test_yaml_roundtrip() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    plan = Plan.model_validate(data)
    dumped = plan.model_dump(mode="json")
    plan2 = Plan.model_validate(dumped)
    assert plan2 == plan
