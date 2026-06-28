---
description: Restore an OPNsense config backup. Two-step confirmation required.
argument-hint: <backup_id>
---

Procedure for rollback to: $ARGUMENTS

1. Call `opn_backup_list()` and confirm `$ARGUMENTS` is in the list. Show its timestamp and label.
2. Show a brief diff: call `opn_config_diff(backup_id_a=$ARGUMENTS)` (compares to current).
3. Ask the user to type the configured confirmation phrase to proceed.
4. Call `opn_backup_restore(backup_id=$ARGUMENTS, confirm=true)`.
5. After restore, call `opn_status()` to verify the firewall came back.

**Never** call `opn_backup_restore` without explicit user confirmation in chat.
