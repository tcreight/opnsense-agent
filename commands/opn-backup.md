---
description: Create a manual backup of OPNsense config. Use before risky external work.
argument-hint: [optional label]
---

Call `opn_backup_create(label=$ARGUMENTS)` (omit label if no argument given).
Report the returned backup_id.

Manually-labeled backups are kept regardless of retention; unlabeled ones are pruned past the configured limit.
