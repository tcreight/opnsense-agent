from __future__ import annotations

import pytest

from opnsense_agent.config import ConfigError
from opnsense_agent.safety.diff import ConfigDiff, diff_config_xml


def test_identical_documents_have_empty_diff() -> None:
    xml = "<opnsense><system><hostname>fw</hostname></system></opnsense>"
    diff = diff_config_xml(xml, xml)
    assert diff.is_empty
    assert "No differences" in diff.render()


def test_changed_leaf_is_reported_with_old_and_new() -> None:
    a = "<opnsense><system><hostname>fw1</hostname></system></opnsense>"
    b = "<opnsense><system><hostname>fw2</hostname></system></opnsense>"
    diff = diff_config_xml(a, b)
    assert [(c.path, c.old, c.new) for c in diff.changed] == [("system/hostname", "fw1", "fw2")]
    assert not diff.added and not diff.removed


def test_added_and_removed_sections() -> None:
    a = "<opnsense><dns/></opnsense>"
    b = "<opnsense><ntp/></opnsense>"
    diff = diff_config_xml(a, b)
    assert [c.path for c in diff.removed] == ["dns"]
    assert [c.path for c in diff.added] == ["ntp"]


def test_revision_block_is_ignored() -> None:
    a = "<opnsense><revision><time>1</time></revision><x>a</x></opnsense>"
    b = "<opnsense><revision><time>2</time></revision><x>a</x></opnsense>"
    diff = diff_config_xml(a, b)
    assert diff.is_empty


def test_repeated_siblings_matched_positionally() -> None:
    a = "<opnsense><s><item><x>a</x></item><item><x>b</x></item></s></opnsense>"
    b = "<opnsense><s><item><x>a</x></item><item><x>c</x></item></s></opnsense>"
    diff = diff_config_xml(a, b)
    assert [(c.path, c.old, c.new) for c in diff.changed] == [("s/item[#1]/x", "b", "c")]


def test_render_summary_line_and_markers() -> None:
    a = "<opnsense><a>1</a><b>x</b></opnsense>"
    b = "<opnsense><a>2</a><c>y</c></opnsense>"
    out = diff_config_xml(a, b).render(from_label="current", to_label="backup X")
    assert out.splitlines()[0] == "Changes from current to backup X:"
    assert "  ~ a: 1 -> 2" in out
    assert "  - b" in out
    assert "  + c" in out
    assert out.splitlines()[-1] == "3 changes across 3 sections"


def test_render_singular_summary_line() -> None:
    """Exactly one change in one section uses the singular summary wording."""
    a = "<opnsense><system><hostname>fw1</hostname></system></opnsense>"
    b = "<opnsense><system><hostname>fw2</hostname></system></opnsense>"
    out = diff_config_xml(a, b).render()
    assert out.splitlines()[-1] == "1 change across 1 section"


def test_diff_direction_is_asymmetric() -> None:
    """diff(a, b) reports B relative to A; flipping the args flips the roles."""
    a = "<opnsense><a>1</a><b>x</b></opnsense>"
    b = "<opnsense><a>2</a><c>y</c></opnsense>"
    forward = diff_config_xml(a, b)
    reverse = diff_config_xml(b, a)
    # Changed leaf: old/new swap.
    assert [(c.path, c.old, c.new) for c in forward.changed] == [("a", "1", "2")]
    assert [(c.path, c.old, c.new) for c in reverse.changed] == [("a", "2", "1")]
    # Added/removed swap roles.
    assert [c.path for c in forward.removed] == ["b"]
    assert [c.path for c in forward.added] == ["c"]
    assert [c.path for c in reverse.removed] == ["c"]
    assert [c.path for c in reverse.added] == ["b"]


def test_malformed_xml_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        diff_config_xml("<not-closed>", "<opnsense/>")


def test_explicit_ignore_paths_overrides_default() -> None:
    """Passing ignore_paths=frozenset() means revision changes ARE reported."""
    a = "<opnsense><revision><time>1</time></revision><x>a</x></opnsense>"
    b = "<opnsense><revision><time>2</time></revision><x>a</x></opnsense>"
    diff = diff_config_xml(a, b, ignore_paths=frozenset())
    # With no paths ignored the revision/time change must appear in changed.
    assert not diff.is_empty
    assert any(c.path == "revision/time" for c in diff.changed)


def test_uuid_keyed_modify_is_change_not_add_remove_even_when_reordered() -> None:
    a = (
        "<opnsense><vlans>"
        '<vlan uuid="u1"><descr>one</descr></vlan>'
        '<vlan uuid="u2"><descr>two</descr></vlan>'
        "</vlans></opnsense>"
    )
    # Reordered AND u2's descr changed.
    b = (
        "<opnsense><vlans>"
        '<vlan uuid="u2"><descr>TWO</descr></vlan>'
        '<vlan uuid="u1"><descr>one</descr></vlan>'
        "</vlans></opnsense>"
    )
    diff = diff_config_xml(a, b)
    assert not diff.added and not diff.removed
    assert [(c.path, c.old, c.new) for c in diff.changed] == [
        ("vlans/vlan[u2]/descr", "two", "TWO")
    ]


def test_identifying_child_keying_uses_tag() -> None:
    a = (
        "<opnsense><vlans>"
        "<vlan><tag>30</tag><descr>iot</descr></vlan>"
        "<vlan><tag>40</tag><descr>cam</descr></vlan>"
        "</vlans></opnsense>"
    )
    b = (
        "<opnsense><vlans>"
        "<vlan><tag>30</tag><descr>IOT</descr></vlan>"
        "<vlan><tag>40</tag><descr>cam</descr></vlan>"
        "</vlans></opnsense>"
    )
    diff = diff_config_xml(a, b)
    assert [(c.path, c.old, c.new) for c in diff.changed] == [
        ("vlans/vlan[tag=30]/descr", "iot", "IOT")
    ]


def test_positional_fallback_when_no_identity() -> None:
    a = "<opnsense><s><item><x>a</x></item><item><x>b</x></item></s></opnsense>"
    b = "<opnsense><s><item><x>a</x></item><item><x>c</x></item></s></opnsense>"
    diff = diff_config_xml(a, b)
    assert [c.path for c in diff.changed] == ["s/item[#1]/x"]


def _all_values(diff: ConfigDiff) -> list[str]:
    """Every non-None old/new value across the structured change lists."""
    return [
        v
        for c in (*diff.changed, *diff.removed, *diff.added)
        for v in (c.old, c.new)
        if v is not None
    ]


def test_changed_secret_leaf_is_redacted_everywhere() -> None:
    psk_old = "hunter2-old-psk-value"
    psk_new = "hunter2-new-psk-value"
    a = f"<opnsense><ipsec><presharedkey>{psk_old}</presharedkey></ipsec></opnsense>"
    b = f"<opnsense><ipsec><presharedkey>{psk_new}</presharedkey></ipsec></opnsense>"
    diff = diff_config_xml(a, b)
    rendered = diff.render()
    # The literal secret appears NOWHERE: not rendered, not structured.
    for secret in (psk_old, psk_new):
        assert secret not in rendered
        assert secret not in _all_values(diff)
    # But the path still shows as changed.
    assert [(c.path, c.old, c.new) for c in diff.changed] == [
        ("ipsec/presharedkey", "[redacted]", "[redacted]")
    ]
    assert "  ~ ipsec/presharedkey: [redacted] -> [redacted]" in rendered


def test_added_secret_leaf_is_redacted() -> None:
    # Deliberately low-entropy fake so gitleaks doesn't flag it as a real key.
    key = "fake-test-key-not-a-secret"
    a = "<opnsense><wireguard><server><name>wg0</name></server></wireguard></opnsense>"
    b = (
        "<opnsense><wireguard><server><name>wg0</name>"
        f"<privatekey>{key}</privatekey></server></wireguard></opnsense>"
    )
    diff = diff_config_xml(a, b)
    assert key not in diff.render()
    assert key not in _all_values(diff)
    assert [(c.path, c.new) for c in diff.added] == [("wireguard/server/privatekey", "[redacted]")]


def test_removed_secret_leaf_is_redacted() -> None:
    pw = "s3cret-radius-pw"
    a = f"<opnsense><system><user><password>{pw}</password></user></system></opnsense>"
    b = "<opnsense><system><user/></system></opnsense>"
    diff = diff_config_xml(a, b)
    assert pw not in diff.render()
    assert pw not in _all_values(diff)
    assert [(c.path, c.old) for c in diff.removed] == [("system/user/password", "[redacted]")]


def test_secret_suffix_and_case_insensitive_matching() -> None:
    a = (
        "<opnsense><auth>"
        "<radius_secret>old-shared</radius_secret>"
        "<Remote_Password>old-pw</Remote_Password>"
        "<wpa_psk>old-wpa</wpa_psk>"
        "</auth></opnsense>"
    )
    b = (
        "<opnsense><auth>"
        "<radius_secret>new-shared</radius_secret>"
        "<Remote_Password>new-pw</Remote_Password>"
        "<wpa_psk>new-wpa</wpa_psk>"
        "</auth></opnsense>"
    )
    diff = diff_config_xml(a, b)
    rendered = diff.render()
    for secret in ("old-shared", "new-shared", "old-pw", "new-pw", "old-wpa", "new-wpa"):
        assert secret not in rendered
    assert {(c.old, c.new) for c in diff.changed} == {("[redacted]", "[redacted]")}
    # Paths themselves are never redacted.
    assert {c.path for c in diff.changed} == {
        "auth/radius_secret",
        "auth/Remote_Password",
        "auth/wpa_psk",
    }


def test_review_flagged_gap_tags_are_redacted() -> None:
    """Code-review gap coverage: proxy credentials (<proxypass>), plugin
    *_pass fields, and private-key tags excluded by the no-"key"-suffix rule
    (accountkey, sslclientkey) must all redact."""
    a = (
        "<opnsense>"
        "<system><proxypass>old-proxy-pw</proxypass></system>"
        "<ups><upsmon_pass>old-ups-pw</upsmon_pass></ups>"
        "<acme><accountkey>old-acme-key</accountkey></acme>"
        "<proxy><sslclientkey>old-ssl-key</sslclientkey></proxy>"
        "</opnsense>"
    )
    b = a.replace("old-", "new-")
    diff = diff_config_xml(a, b)
    rendered = diff.render()
    for prefix in ("old-", "new-"):
        for suffix in ("proxy-pw", "ups-pw", "acme-key", "ssl-key"):
            assert f"{prefix}{suffix}" not in rendered
    assert {(c.old, c.new) for c in diff.changed} == {("[redacted]", "[redacted]")}


def test_bypass_lists_are_not_redacted() -> None:
    """The "_pass" suffix must not swallow non-secret <bypass> tags."""
    a = "<opnsense><proxy><bypass>lan.example</bypass></proxy></opnsense>"
    b = "<opnsense><proxy><bypass>lan2.example</bypass></proxy></opnsense>"
    rendered = diff_config_xml(a, b).render()
    assert "lan.example -> lan2.example" in rendered
    assert "[redacted]" not in rendered


def test_public_keys_are_not_redacted() -> None:
    a = "<opnsense><wg><pubkey>PUBLIC-A</pubkey><publickey>PK-A</publickey></wg></opnsense>"
    b = "<opnsense><wg><pubkey>PUBLIC-B</pubkey><publickey>PK-B</publickey></wg></opnsense>"
    diff = diff_config_xml(a, b)
    rendered = diff.render()
    assert "PUBLIC-A -> PUBLIC-B" in rendered
    assert "PK-A -> PK-B" in rendered
    assert "[redacted]" not in rendered


def test_redaction_can_be_disabled_but_defaults_on() -> None:
    a = "<opnsense><u><password>old-pw</password></u></opnsense>"
    b = "<opnsense><u><password>new-pw</password></u></opnsense>"
    # Default: redacted.
    assert "old-pw" not in diff_config_xml(a, b).render()
    # Library-level escape hatch shows the raw values.
    off = diff_config_xml(a, b, redact_secrets=False)
    assert [(c.old, c.new) for c in off.changed] == [("old-pw", "new-pw")]


def test_duplicate_identity_siblings_do_not_swallow_each_other() -> None:
    # Two rules with identical <descr> and no uuid. Removing the second must be
    # reported as a removal, not silently overwritten by identity collision.
    # BEFORE the fix: second rule's key overwrote the first in _key_map, so the
    # diff matched the second rule (port=443) against the surviving rule (port=80)
    # and reported a spurious port change instead of a removal.
    a = (
        "<opnsense><filter>"
        "<rule><descr>web</descr><port>80</port></rule>"
        "<rule><descr>web</descr><port>443</port></rule>"
        "</filter></opnsense>"
    )
    b = "<opnsense><filter><rule><descr>web</descr><port>80</port></rule></filter></opnsense>"
    diff = diff_config_xml(a, b)
    assert diff.added == []
    assert diff.changed == []
    assert [c.path for c in diff.removed] == ["filter/rule[descr=web#1]"]
