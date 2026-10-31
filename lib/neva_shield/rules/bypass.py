"""Bypass rules: flags and modes that switch the approval or sandbox layer off."""
import re

KINDS = ("settings", "codex", "hooks_config", "hook_script", "script", "instructions", "mcp", "marketplace")

SKIP_PERMISSIONS = re.compile(r"--dangerously-skip-permissions|[\"']?dangerouslySkipPermissions[\"']?\s*[:=]\s*true")
BYPASS_APPROVALS = re.compile(r"--dangerously-bypass-approvals-and-sandbox|--yolo\b")
DEFAULT_MODE = re.compile(r"[\"']defaultMode[\"']\s*:\s*[\"']bypassPermissions[\"']")
APPROVAL_NEVER = re.compile(r"(?m)^\s*approval_policy\s*=\s*[\"']never[\"']")
SANDBOX_DANGER = re.compile(r"(?m)^\s*sandbox_mode\s*=\s*[\"']danger-full-access[\"']")
TRUST_ALL = re.compile(r"[\"'](?:bypassPermissions|autoApprove|auto_approve|skipConfirmation|trustAllTools|yolo)[\"']\s*:\s*true")


def check(source, add):
    text = source.text
    for found in SKIP_PERMISSIONS.finditer(text):
        add("BYPASS001", "critical", source.line_of(found.start()),
            "Permission prompts are switched off here by " + found.group(0).strip() + ".",
            "Delete --dangerously-skip-permissions from this command and grant the specific tools in permissions.allow instead.")
    for found in BYPASS_APPROVALS.finditer(text):
        add("BYPASS002", "critical", source.line_of(found.start()),
            "Approvals and the sandbox are switched off here by " + found.group(0).strip() + ".",
            "Delete " + found.group(0).strip() + " and run with the default sandbox, approving each action that needs it.")

    data = source.data()
    mode = None
    if isinstance(data, dict):
        block = data.get("permissions")
        if isinstance(block, dict):
            mode = block.get("defaultMode")
    if mode == "bypassPermissions" or DEFAULT_MODE.search(text):
        add("BYPASS003", "critical", source.find_line('"defaultMode"', "defaultMode"),
            "permissions.defaultMode is bypassPermissions, so every tool call runs unprompted.",
            'Set "defaultMode" to "default" or "acceptEdits" and list the tools you trust in permissions.allow.')
    for found in TRUST_ALL.finditer(text):
        add("BYPASS006", "high", source.line_of(found.start()),
            "A blanket auto-approval flag is enabled: " + found.group(0).strip() + ".",
            "Set that flag to false and approve tools individually.")

    if source.has("codex") or source.path.suffix.lower() == ".toml":
        never = APPROVAL_NEVER.search(text)
        danger = SANDBOX_DANGER.search(text)
        if never and danger:
            add("BYPASS004", "critical", source.line_of(never.start()),
                'Codex runs with approval_policy = "never" and sandbox_mode = "danger-full-access", which is full host access with no prompt.',
                'Set sandbox_mode = "workspace-write" and approval_policy = "on-request" in this config.toml.')
        elif danger:
            add("BYPASS005", "high", source.line_of(danger.start()),
                'Codex sandbox_mode is "danger-full-access", so tools reach the whole filesystem and the network.',
                'Set sandbox_mode = "workspace-write" in this config.toml.')
