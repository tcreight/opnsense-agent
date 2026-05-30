"""Plan persistence: save, load, list, finalize (immutable after non-draft)."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from opnsense_agent.plans.schema import Plan, PlanStatus

logger = logging.getLogger(__name__)


class PlanStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        (runs_dir / "plans").mkdir(parents=True, exist_ok=True)

    def save(self, plan: Plan) -> str:
        path = self.runs_dir / "plans" / f"{plan.plan_id}.yaml"
        if path.exists() and not (path.stat().st_mode & 0o200):
            raise PermissionError(
                f"Plan {plan.plan_id} is finalized (read-only); cannot overwrite."
            )
        text = yaml.safe_dump(
            plan.model_dump(mode="json"), sort_keys=False, default_flow_style=False
        )
        path.write_text(text)
        path.chmod(0o644)
        logger.info("Plan saved: %s (status=%s)", plan.plan_id, plan.status)
        return plan.plan_id

    def load(self, plan_id: str) -> Plan:
        path = self.runs_dir / "plans" / f"{plan_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Plan not found: {plan_id}")
        return Plan.model_validate(yaml.safe_load(path.read_text()))

    def list(self) -> list[Plan]:
        plans: list[Plan] = []
        for path in sorted((self.runs_dir / "plans").iterdir(), reverse=True):
            if path.suffix != ".yaml":
                continue
            try:
                plans.append(Plan.model_validate(yaml.safe_load(path.read_text())))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping malformed plan file: %s", path)
        return plans

    def finalize(self, plan: Plan) -> None:
        """Save plan in a non-draft status and chmod 0444 for audit immutability."""
        if plan.status is PlanStatus.draft:
            raise ValueError(
                "Cannot finalize a plan still in draft status. "
                "Set status to applied/failed/rolled_back first."
            )
        path = self.runs_dir / "plans" / f"{plan.plan_id}.yaml"
        if path.exists():
            path.chmod(0o644)
        text = yaml.safe_dump(
            plan.model_dump(mode="json"), sort_keys=False, default_flow_style=False
        )
        path.write_text(text)
        path.chmod(0o444)
        logger.info("Plan finalized: %s -> %s", plan.plan_id, plan.status)
