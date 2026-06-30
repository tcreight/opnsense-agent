from __future__ import annotations

import pytest

from opnsense_agent.config import ConfigError
from opnsense_agent.safety.diff import diff_config_xml


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
