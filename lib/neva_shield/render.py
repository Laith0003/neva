"""Text, JSON, and SARIF 2.1.0 output for Neva Shield. Standard library only."""
import json

from .model import SEVERITIES, WEIGHTS

SARIF_LEVELS = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}
SARIF_RANK = {"critical": 10.0, "high": 8.0, "medium": 5.0, "low": 2.0}
VERSION = "1.0"
INFORMATION_URI = "https://github.com/Laith0003/neva/blob/main/docs/harness/07-shield.md"
GRADE_LINE = "Grade is 100 points less 30 per critical, 15 per high, 6 per medium, 2 per low: A from 90, B from 75, C from 60, D from 40, F below. A skipped location caps the score at 89."


def text(result):
    notes = [item for item in result.findings if not item.scored]
    findings = [item for item in result.findings if item.scored]
    if result.empty:
        lines = [
            "Neva Shield  no grade",
            "Root: " + result.root,
            "Files scanned: 0",
            "",
            "No harness configuration found under " + result.root + ".",
        ]
    else:
        counts = result.counts()
        lines = [
            "Neva Shield  grade " + result.grade + "  score " + str(result.score) + "/100",
            "Root: " + result.root,
            "Files scanned: " + str(result.files_scanned) + "    Findings: "
            + ", ".join(str(counts[name]) + " " + name for name in SEVERITIES)
            + ("    Suppressed: " + str(result.suppressed) if result.suppressed else "")
            + ("    Skipped locations: " + str(result.skipped_targets) if result.skipped_targets else ""),
        ]
        if not findings:
            lines.extend(("", "No findings. " + GRADE_LINE))
    for item in findings:
        lines.append("")
        lines.append(item.severity.upper() + "  " + item.rule_id + "  " + item.path + ":" + str(item.line))
        lines.append("  " + item.message)
        lines.append("  Fix: " + item.fix)
    if notes:
        lines.append("")
        lines.append("LOW  LINK002  Symlinks not followed: " + str(len(notes)) + ". What the harness loads through them was not read, and they do not change the grade.")
        lines.extend("  " + item.path for item in notes)
        lines.append("  Fix: " + notes[0].fix)
    if findings:
        lines.append("")
        lines.append(GRADE_LINE)
    return "\n".join(lines)


def json_text(result):
    return json.dumps(result.as_dict(), sort_keys=True, indent=2)


def sarif(result):
    """A SARIF 2.1.0 log that GitHub code scanning accepts.

    Rules are emitted once each with a defaultConfiguration level, and every result
    carries ruleId, ruleIndex, a message, and a physical location with a startLine,
    which are the fields the GitHub upload validates.
    """
    order = []
    rules = {}
    for item in result.findings:
        if item.rule_id not in rules:
            rules[item.rule_id] = {
                "id": item.rule_id,
                "name": item.rule_id,
                "shortDescription": {"text": _short(item.rule_id)},
                "fullDescription": {"text": item.message},
                "help": {"text": item.fix, "markdown": "**Fix:** " + item.fix},
                "defaultConfiguration": {"level": SARIF_LEVELS[item.severity]},
                "properties": {
                    "security-severity": str(SARIF_RANK[item.severity]),
                    "tags": ["security", _family(item.rule_id)],
                    "weight": WEIGHTS[item.severity],
                },
            }
            order.append(item.rule_id)

    results = []
    for item in result.findings:
        results.append({
            "ruleId": item.rule_id,
            "ruleIndex": order.index(item.rule_id),
            "level": SARIF_LEVELS[item.severity],
            "message": {"text": item.message + " Fix: " + item.fix},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": item.path.replace("\\", "/"), "uriBaseId": "%SRCROOT%"},
                    "region": {"startLine": item.line},
                },
            }],
            "partialFingerprints": {"nevaShieldRuleLocation": item.rule_id + ":" + item.path + ":" + str(item.line)},
        })

    return json.dumps({
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "Neva Shield",
                "version": VERSION,
                "informationUri": INFORMATION_URI,
                "rules": [rules[rule_id] for rule_id in order],
            }},
            "results": results,
            "columnKind": "utf16CodeUnits",
            "properties": {"grade": result.grade, "score": result.score},
        }],
    }, sort_keys=True, indent=2)


FAMILY_NAMES = {
    "PERM": "permissions", "BYPASS": "bypass", "HOOK": "hooks", "MCP": "mcp",
    "SECRET": "secrets", "PROMPT": "prompt-injection", "PROV": "provenance", "LINK": "coverage",
}
SHORT = {
    "PERM001": "Allow rule grants arbitrary command execution",
    "PERM002": "Allow rule grants unprompted file upload",
    "PERM003": "Allow rule grants writes outside the project",
    "PERM004": "Unrestricted fetch combined with upload",
    "PERM005": "No deny rule for secret paths",
    "BYPASS001": "Permission prompts disabled",
    "BYPASS002": "Approvals and sandbox disabled",
    "BYPASS003": "bypassPermissions is the default mode",
    "BYPASS004": "Codex runs with no approvals and full access",
    "BYPASS005": "Codex sandbox is danger-full-access",
    "BYPASS006": "Blanket auto approval enabled",
    "HOOK001": "Hook splices payload into a shell command",
    "HOOK002": "Hook downloads and executes remote code",
    "HOOK003": "Hook makes outbound network calls",
    "HOOK004": "Hook swallows a blocking decision",
    "HOOK005": "Hook script is world writable",
    "MCP001": "MCP launcher package is not pinned",
    "MCP002": "MCP server reached over plaintext http",
    "MCP003": "Inline credential in MCP environment",
    "MCP004": "Remote MCP server has no authentication",
    "SECRET001": "Credential material in a harness file",
    "SECRET002": "Literal credential assigned to a secret field",
    "PROMPT001": "Invisible Unicode tag characters",
    "PROMPT002": "Bidirectional override character",
    "PROMPT003": "Instruction override directive",
    "PROMPT004": "Large base64 blob in instructions",
    "PROMPT005": "Download and execute in instructions",
    "PROMPT006": "Zero width character in instructions",
    "PROMPT007": "Instruction override text inside prose",
    "PROV001": "Plugin source is not over https",
    "PROV002": "Credential file readable by others",
    "PROV003": "Configuration file is world writable",
    "PROV004": "Plugin source is not pinned",
    "LINK001": "Symlink hides configuration from the scan",
    "LINK002": "Symlink not followed",
}


def _family(rule_id):
    for prefix, name in FAMILY_NAMES.items():
        if rule_id.startswith(prefix):
            return name
    return "other"


def _short(rule_id):
    return SHORT.get(rule_id, rule_id)
