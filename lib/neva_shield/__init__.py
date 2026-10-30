"""Neva Shield: a security scanner for agent harness configuration.

Reads Claude Code, Codex, OpenCode, Cursor, and Gemini configuration and reports the
permission, bypass, hook, MCP, secret, prompt injection, and provenance problems in it.
Python standard library only. It redacts known credential shapes and prints less by design.
It is a best-effort scanner, not a proof.
"""
from .engine import scan_machine, scan_path
from .model import SEVERITIES, SEVERITY_RANK, WEIGHTS, Finding, ScanResult

__all__ = ["scan_machine", "scan_path", "Finding", "ScanResult", "SEVERITIES", "SEVERITY_RANK", "WEIGHTS"]
