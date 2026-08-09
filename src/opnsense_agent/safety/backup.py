"""Pre-change config backups: pull, save, list, restore, retention."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient

logger = logging.getLogger(__name__)

# Backup ids arrive from MCP tool arguments; allowlist the charset so an id can
# only name a file inside backups/ (no path separators, no traversal). ".." is
# not special-cased: the ".xml" suffix makes a bare ".." just an odd filename.
_BACKUP_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


class ConfigDownloadError(Exception):
    """Raised when the firewall's config download yields no XML.

    Fail-closed: silently writing an empty backup would void the rollback
    safety net — restoring it later would push an empty config to the firewall
    exactly when the operator most needs the backup to be real.
    """


# OPNsense exposes config download at this endpoint.
# Returns the raw config.xml as text (verified during integration test).
DOWNLOAD_PATH = "/api/backup/backup/download"
RESTORE_PATH = "/api/backup/backup/restore"


@dataclass(frozen=True)
class BackupRecord:
    id: str
    path: Path
    label: str | None
    created: datetime


class BackupStore:
    def __init__(self, runs_dir: Path, retention: int = 50) -> None:
        self.runs_dir = runs_dir
        self.retention = retention
        (runs_dir / "backups").mkdir(parents=True, exist_ok=True)

    def _backup_path(self, backup_id: str) -> Path:
        if not _BACKUP_ID_RE.fullmatch(backup_id):
            raise ValueError(f"Invalid backup id: {backup_id!r}")
        return self.runs_dir / "backups" / f"{backup_id}.xml"

    async def fetch_current_xml(self, api: OpnApiClient) -> str:
        """Pull the live config.xml as text. Shared by create() and config diffs.

        Raises ConfigDownloadError instead of degrading to "" on an unexpected
        response shape — an empty string here would become an empty backup file.
        """
        raw: Any = await api.get(DOWNLOAD_PATH)  # type: ignore[arg-type]
        xml_text: str = raw if isinstance(raw, str) else raw.get("data", "")
        if not xml_text:
            raise ConfigDownloadError(f"{DOWNLOAD_PATH} returned no config XML")
        return xml_text

    async def create(self, api: OpnApiClient, label: str | None = None) -> str:
        xml_text = await self.fetch_current_xml(api)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        suffix = f"-{label}" if label else ""
        backup_id = f"{ts}{suffix}"
        path = self._backup_path(backup_id)
        path.write_text(xml_text)
        logger.info("Backup created: %s", backup_id)
        return backup_id

    def read_xml(self, backup_id: str) -> str:
        """Read a stored backup's config.xml. Raises FileNotFoundError if absent."""
        # try/except instead of exists()-then-read: race-free if the file is
        # pruned between check and read, with the same exception contract.
        try:
            return self._backup_path(backup_id).read_text()
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Backup not found: {backup_id}") from e

    def list(self) -> list[BackupRecord]:
        records: list[BackupRecord] = []
        for path in (self.runs_dir / "backups").iterdir():
            if path.suffix != ".xml":
                continue
            stem = path.stem
            ts_part, _, label = stem.partition("-")
            try:
                created = datetime.strptime(ts_part, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
            except ValueError:
                continue
            records.append(
                BackupRecord(
                    id=stem,
                    path=path,
                    label=label or None,
                    created=created,
                )
            )
        records.sort(key=lambda r: r.created, reverse=True)
        return records

    def prune(self) -> int:
        unlabeled = [r for r in self.list() if r.label is None]
        # Keep newest `retention` unlabeled; delete the rest.
        to_delete = unlabeled[self.retention :]
        for record in to_delete:
            record.path.unlink()
            logger.info("Pruned backup: %s", record.id)
        return len(to_delete)

    async def restore(self, api: OpnApiClient, backup_id: str) -> None:
        xml_text = self.read_xml(backup_id)
        await api.post(RESTORE_PATH, json={"data": xml_text})
        logger.info("Backup restored: %s", backup_id)
