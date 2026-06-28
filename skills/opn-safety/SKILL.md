---
name: opn-safety
description: Use whenever planning or applying changes to OPNsense — covers backup-before-apply, lockout reasoning, two-stage commit, and rollback procedure.
---

# OPNsense Safety Patterns

## Two-stage commit

Every mutation goes through `/opn-plan` then `/opn-apply`. Never call `opn_plan_apply` from inside diagnostic conversations.

## Lockout reasoning

Before any apply, the lockout check inspects the plan for ops that would:
- Disable the management interface
- Change the management interface IP
- Disable SSH or the API/web service
- Delete a firewall rule that allows traffic from the operator's IP

If warnings appear, surface them to the user and require explicit override.

## Rollback procedure

1. The apply pipeline auto-restores the pre-apply backup on:
   - Op execution failure (any non-ok result)
   - Reachability probe failure (firewall stopped responding)
2. Manual rollback: `/opn-rollback <backup_id>` — two-step confirm.
3. If the firewall is fully unreachable: physical/console access required (no software fix).

## Patterns
- Always backup before any external change (manual `/opn-backup` if you're about to do GUI work).
- Prefer making one logical change per plan — easier to reason about, easier to roll back.
- After apply, verify intent matches reality: `/opn-status` and check the relevant subsystem.
