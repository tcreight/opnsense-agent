from __future__ import annotations

import logging

import httpx
import pytest

from opnsense_agent.client.api import OpnApiClient
from opnsense_agent.config import AuthSettings, FirewallSettings


@pytest.fixture
def firewall() -> FirewallSettings:
    return FirewallSettings(
        host="opnsense.test",
        api_port=443,
        ssh_port=22,
        verify_tls=False,
        ssh_user="root",
        ssh_key_path="/dev/null",  # type: ignore[arg-type]
    )


@pytest.fixture
def auth() -> AuthSettings:
    return AuthSettings(api_key="THE_KEY_VALUE", api_secret="THE_SECRET_VALUE")


async def test_get_returns_parsed_json(firewall: FirewallSettings, auth: AuthSettings) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"status": "ok"}))
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    result = await client.get("/api/diagnostics/system/system_information")
    assert result == {"status": "ok"}
    await client.close()


async def test_post_sends_basic_auth_header(firewall: FirewallSettings, auth: AuthSettings) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    await client.post("/api/some/endpoint", json={"k": "v"})
    assert captured["authorization"].startswith("Basic ")
    await client.close()


async def test_logs_redact_secrets(
    firewall: FirewallSettings,
    auth: AuthSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    with caplog.at_level(logging.DEBUG, logger="opnsense_agent.client.api"):
        await client.get("/api/anything")
    full_log = "\n".join(record.getMessage() for record in caplog.records)
    assert "THE_KEY_VALUE" not in full_log
    assert "THE_SECRET_VALUE" not in full_log
    await client.close()


async def test_raises_on_non_2xx(firewall: FirewallSettings, auth: AuthSettings) -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"message": "unauthorized"})
    )
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/api/whatever")
    await client.close()
