from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opnsense_agent.plans.schema import Plan, PlanStatus
from opnsense_agent.plans.store import PlanStore

SAMPLE_YAML = """
plan_id: 2026-05-03T14-30-22Z-test
description: test
created: 2026-05-03T14:30:22Z
status: draft
target: { host: opnsense.lan }
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1 }
"""


@pytest.fixture
def store(tmp_path: Path) -> PlanStore:
    return PlanStore(runs_dir=tmp_path)


def _make_plan() -> Plan:
    return Plan.model_validate(yaml.safe_load(SAMPLE_YAML))


def test_save_writes_yaml_at_0644(store: PlanStore) -> None:
    plan = _make_plan()
    plan_id = store.save(plan)
    path = store.runs_dir / "plans" / f"{plan_id}.yaml"
    assert path.exists()
    mode = path.stat().st_mode & 0o777
    assert mode == 0o644


def test_load_roundtrips(store: PlanStore) -> None:
    plan = _make_plan()
    plan_id = store.save(plan)
    loaded = store.load(plan_id)
    assert loaded == plan


def test_list_includes_status(store: PlanStore) -> None:
    plan = _make_plan()
    store.save(plan)
    listing = store.list()
    assert len(listing) == 1
    assert listing[0].status is PlanStatus.draft


def test_finalize_chmods_file_to_0444(store: PlanStore) -> None:
    plan = _make_plan()
    plan_id = store.save(plan)
    plan_applied = plan.model_copy(update={"status": PlanStatus.applied})
    store.finalize(plan_applied)
    path = store.runs_dir / "plans" / f"{plan_id}.yaml"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o444


def test_finalize_refuses_when_status_still_draft(store: PlanStore) -> None:
    plan = _make_plan()
    store.save(plan)
    with pytest.raises(ValueError, match="finalize"):
        store.finalize(plan)
