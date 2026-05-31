"""Post-apply reachability probe."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient

logger = logging.getLogger(__name__)

PROBE_PATH = "/api/diagnostics/system/system_information"


async def reachability_probe(
    *,
    api: OpnApiClient,
    max_seconds: int = 30,
    interval_seconds: int = 3,
) -> bool:
    """Returns True as soon as the firewall responds; False if all attempts fail."""
    elapsed = 0
    attempt = 0
    while elapsed <= max_seconds:
        attempt += 1
        try:
            await api.get(PROBE_PATH)
            logger.info("Reachability probe: success on attempt %d", attempt)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("Reachability probe attempt %d failed: %s", attempt, e)
        if elapsed + interval_seconds > max_seconds:
            break
        await asyncio.sleep(interval_seconds)
        elapsed += interval_seconds
    logger.warning("Reachability probe: all %d attempts failed", attempt)
    return False
