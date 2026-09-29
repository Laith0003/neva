---
description: "Scan agent, hook, MCP, permission, and secret surfaces with AgentShield and return a prioritized fix plan."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# /security-scan

Invoke the `neva-core:security-scan` skill with `$ARGUMENTS` (optional path and AgentShield flags) and follow it exactly.
Use scanner output as the source of truth; hand CRITICAL and HIGH findings to `neva-core:security-reviewer` for verification.
