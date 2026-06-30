from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from opnsense_agent.safety.backup import BackupStore


@pytest.fixture
def store(tmp_path: Path) -> BackupStore:
    return BackupStore(runs_dir=tmp_path, retention=3)


async def test_create_pulls_config_and_saves_with_timestamp(
    store: BackupStore,
) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<opnsense><test/></opnsense>"
    backup_id = await store.create(api=fake_api, label="manual-test")
    files = list((store.runs_dir / "backups").iterdir())
    assert len(files) == 1
    assert files[0].name.endswith("-manual-test.xml")
    assert backup_id == files[0].stem


async def test_list_returns_sorted_descending(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<x/>"
    a = await store.create(api=fake_api)
    b = await store.create(api=fake_api)
    c = await store.create(api=fake_api)
    listing = store.list()
    assert [r.id for r in listing] == [c, b, a]


async def test_retention_prunes_unlabeled_only(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<x/>"
    for _ in range(4):
        await store.create(api=fake_api)
    await store.create(api=fake_api, label="keep-me")
    store.prune()
    surviving = [r.label for r in store.list()]
    assert surviving.count(None) == 3
    assert "keep-me" in surviving


async def test_restore_posts_xml(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<original/>"
    backup_id = await store.create(api=fake_api)
    fake_api.post.return_value = {"status": "ok"}
    await store.restore(api=fake_api, backup_id=backup_id)
    assert fake_api.post.called


async def test_fetch_current_xml_returns_config_text(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<opnsense><a/></opnsense>"
    xml = await store.fetch_current_xml(api=fake_api)
    assert xml == "<opnsense><a/></opnsense>"


async def test_read_xml_round_trips_a_created_backup(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<opnsense><b>1</b></opnsense>"
    backup_id = await store.create(api=fake_api)
    assert store.read_xml(backup_id) == "<opnsense><b>1</b></opnsense>"


def test_read_xml_unknown_id_raises(store: BackupStore) -> None:
    with pytest.raises(FileNotFoundError):
        store.read_xml("does-not-exist")
