---
description: Review and apply a saved plan. Runs lockout check, asks for confirmation, executes via the apply pipeline.
argument-hint: <plan_id>
---

Apply plan: $ARGUMENTS

Procedure:
1. Call `opn_plan_load($ARGUMENTS)` and show the ops to the user.
2. Call `opn_lockout_check($ARGUMENTS)`. If warnings exist, list each one and ask the user to type the configured confirmation phrase to override.
3. Ask the user to type the configured confirmation phrase (default: `yes apply`) to proceed.
4. Call `opn_plan_apply(plan_id=$ARGUMENTS, confirm=true, override_lockout=<true if warnings were overridden>)`.
5. Report results: status, backup_id, per-op results. If status is `failed` or `rolled_back`, surface the rollback_reason prominently.

**Never** call `opn_plan_apply` without explicit user confirmation in chat. The `confirm=true` flag is necessary but not sufficient — wait for the typed confirmation phrase before invoking the tool.
