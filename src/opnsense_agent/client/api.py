"""Async REST client for the OPNsense API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from opnsense_agent.config import AuthSettings, FirewallSettings

logger = logging.getLogger(__name__)


class OpnApiClient:
    """Wraps httpx.AsyncClient with OPNsense auth + redacted logging.

    Uses HTTP Basic auth (api_key:api_secret), per OPNsense docs.
    All log lines redact the auth header. Never prints api_key/api_secret.
    """

    def __init__(
        self,
        firewall: FirewallSettings,
        auth: AuthSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = f"https://{firewall.host}:{firewall.api_port}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=(auth.api_key, auth.api_secret),
            verify=firewall.verify_tls,
            timeout=httpx.Timeout(10.0, connect=5.0),
            transport=transport,
        )

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.debug("API %s %s (auth: <redacted>)", method, path)
        response = await self._client.request(method, path, params=params, json=json)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OpnApiClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
