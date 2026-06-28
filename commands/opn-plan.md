---
description: Draft an OPNsense change plan from a natural language description. Returns a plan_id you can apply with /opn-apply.
argument-hint: <description of the desired change>
---

Use the `opn-planner` subagent to draft a plan for: $ARGUMENTS

The planner will:
1. Load the relevant skills
2. Draft a plan YAML
3. Save it as a draft
4. Show you a preview
5. Tell you the plan_id to apply
