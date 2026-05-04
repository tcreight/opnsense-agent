# OPNsense Agent

A Claude Code plugin for managing a single OPNsense firewall via a plan-then-apply workflow. Uses the OPNsense REST API for config mutations and SSH for diagnostics.

> **Status:** v1 — covers VLANs, interfaces, DHCP. See [roadmap](#roadmap) for future phases.

## ⚠️ Secrets handling

This plugin requires an OPNsense API key/secret and an SSH key. **They are never stored in this repository.**

- Secrets live in `~/.config/opnsense-agent/config.toml` (mode `0600`, refused if wider).
- The repo's `.gitignore` denies `.env`, `*.key`, `*.pem`, `*_rsa`, `*_ed25519`, `secrets/`, `config.local.*`, `apikey.txt`, `runs/`, and config backups.
- A `pre-commit` hook runs `gitleaks` on every commit and blocks anything that looks like a secret.
- A CI test (`tests/test_no_secrets_in_repo.py`) greps the working tree for OPNsense-shaped API keys and SSH private-key headers; CI fails on a match.

If you find a way to commit a secret, that is a bug. File an issue.

## Setup

(Filled in by Task 22 — the README finalization task.)

## Roadmap

- v1 — VLANs, interfaces, DHCP, basic gateway/DNS *(this release)*
- v2 — VPN (WireGuard, OpenVPN)
- v3 — Firewall rules, aliases, NAT, port forwards
- v4 — Drift detection + monitoring daemon

## License

MIT
