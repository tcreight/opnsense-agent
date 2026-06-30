"""Integration test guardrails. Tests opt-in only.

Required env:
  OPN_AGENT_INTEGRATION_TEST=1
  OPN_AGENT_INTEGRATION_HOST=<expected host>  # must match settings.firewall.host
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator

import pytest

from opnsense_agent.client.api import OpnApiClient
from opnsense_agent.config import Settings, load_settings
from opnsense_agent.safety.backup import BackupStore


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("OPN_AGENT_INTEGRATION_TEST") != "1":
        skip = pytest.mark.skip(reason="set OPN_AGENT_INTEGRATION_TEST=1 to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = load_settings()
    expected_host = os.environ.get("OPN_AGENT_INTEGRATION_HOST")
    if expected_host and s.firewall.host != expected_host:
        pytest.fail(
            f"Refusing to run integration tests against {s.firewall.host!r}; "
            f"OPN_AGENT_INTEGRATION_HOST is {expected_host!r}."
        )
    return s


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[OpnApiClient]:
    client = OpnApiClient(firewall=settings.firewall, auth=settings.auth)
    yield client
    await client.close()


@pytest.fixture(autouse=True)
async def session_backup(settings: Settings, api: OpnApiClient) -> AsyncIterator[str]:
    """Snapshot before each integration test; restore afterward.

    We restore unconditionally in v1 to keep the firewall in a known state.
    Could be made conditional on test outcome later.
    """
    store = BackupStore(runs_dir=settings.runtime.runs_dir, retention=999)
    backup_id = await store.create(api=api, label="integration-pre")
    yield backup_id
    # Best-effort cleanup; a restore failure must never mask the test result.
    with contextlib.suppress(Exception):
        await store.restore(api=api, backup_id=backup_id)
