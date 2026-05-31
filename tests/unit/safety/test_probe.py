from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.safety.probe import reachability_probe


@pytest.mark.asyncio
async def test_probe_returns_true_on_first_success() -> None:
    api = AsyncMock()
    api.get.return_value = {"status": "ok"}
    result = await reachability_probe(api=api, max_seconds=10, interval_seconds=1)
    assert result is True
    assert api.get.call_count == 1


@pytest.mark.asyncio
async def test_probe_returns_false_when_all_fail() -> None:
    api = AsyncMock()
    api.get.side_effect = Exception("connection refused")
    result = await reachability_probe(api=api, max_seconds=3, interval_seconds=1)
    assert result is False
    assert api.get.call_count >= 2
