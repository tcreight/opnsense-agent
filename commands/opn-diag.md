---
description: Investigate an OPNsense issue read-only. No mutations possible. Use when something is broken and you need to know why.
argument-hint: <symptom or question>
---

Use the `opn-diag` subagent to investigate: $ARGUMENTS

The diag agent will:
1. Load relevant troubleshooting skills
2. Run read-only API and SSH commands
3. Report findings, diagnosis, and recommended action

If the recommended action is a mutation, the agent will tell you to run `/opn-plan "<description>"` — it will not save or apply a plan itself.
