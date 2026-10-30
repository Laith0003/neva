"""Prompt injection rules: text in an instruction file that redirects the agent.

An instruction file is read by the model every session, so hidden characters and override
text in one are not a theoretical risk. Two severities are used deliberately. A directive
line that starts with override text is high. The same phrase quoted inside prose, which is
what a security document discussing injection looks like, is medium and says so, because
no text heuristic can tell a citation from a live directive with certainty.
"""
import re

from . import shared

KINDS = ("instructions",)

TAG_CHARS = re.compile(r"[\U000e0000-\U000e007f]")
BIDI = re.compile(r"[‪-‮⁦-⁩]")
ZERO_WIDTH = re.compile(r"[​-‏⁠﻿]")
OVERRIDE = re.compile(
    r"(?i)\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+)*"
    r"(?:previous|prior|preceding|above|earlier|former|original|system)\s+"
    r"(?:instructions?|prompts?|rules?|directives?|guidelines?)"
)
PERSONA = re.compile(r"(?i)\byou\s+are\s+now\s+(?:a|an|in)\b|\bnew\s+system\s+prompt\b|\bdeveloper\s+mode\s+enabled\b")
BASE64_BLOB = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{96,}={0,2}(?![A-Za-z0-9+/=])")
FETCH_TO_SHELL = re.compile(r"\b(?:curl|wget)\b[^|\n]*https?://[^|\n]*\|\s*(?:sudo\s+)?(?:ba|z|d)?sh\b")
LIST_PREFIX = re.compile(r"^[\s>*\-+#|]*(?:\d+[.)]\s*)?")


def _directive(text, start):
    """True when the match begins a line, which is how a live injected instruction reads."""
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start]
    return LIST_PREFIX.fullmatch(prefix) is not None


def check(source, add):
    text = source.text
    fenced = shared.fenced_lines(text)

    for found in TAG_CHARS.finditer(text):
        add("PROMPT001", "critical", source.line_of(found.start()),
            "Unicode tag characters (U+E00xx) are embedded here. They are invisible in every editor and carry instructions only the model reads.",
            "Delete the invisible characters on this line, then check git history for who added them.")
    for found in BIDI.finditer(text):
        add("PROMPT002", "high", source.line_of(found.start()),
            "A bidirectional override character (U+" + format(ord(found.group(0)), "04X") + ") is embedded here, so the rendered text differs from what the model reads.",
            "Delete the override character on this line and rewrite the sentence in plain text.")
    for found in ZERO_WIDTH.finditer(text):
        add("PROMPT006", "medium", source.line_of(found.start()),
            "A zero width character (U+" + format(ord(found.group(0)), "04X") + ") is embedded here and may be splitting a word the model reads.",
            "Delete the zero width character on this line.")

    for pattern in (OVERRIDE, PERSONA):
        for found in pattern.finditer(text):
            line = source.line_of(found.start())
            if _directive(text, found.start()):
                add("PROMPT003", "high", line,
                    "This line is a standing directive to " + found.group(0).strip().lower() + ".",
                    "Delete this line. An instruction file must not tell the agent to drop its own instructions.")
            else:
                add("PROMPT007", "medium", line,
                    "Override text (" + found.group(0).strip().lower() + ") appears inside prose here. Shield cannot tell a quoted example from a live directive.",
                    "Confirm this is a quoted example, and add the comment neva-shield: ignore PROMPT007 on this line if it is.")

    for found in BASE64_BLOB.finditer(text):
        blob = found.group(0)
        if not (re.search(r"[a-z]", blob) and re.search(r"[A-Z]", blob) and re.search(r"[0-9]", blob)):
            continue
        add("PROMPT004", "medium", source.line_of(found.start()),
            "A " + str(len(blob)) + " character base64 blob sits in an instruction file, which is how hidden text is smuggled past a reader.",
            "Decode it, confirm what it says, and replace it with the plain text, or delete it.")

    for found in FETCH_TO_SHELL.finditer(text):
        line = source.line_of(found.start())
        severity = "medium" if line in fenced else "high"
        add("PROMPT005", severity, line,
            "Instruction file tells the agent to download a remote script and pipe it into a shell.",
            "Replace it with a pinned download, a checksum check, then a separate run of the verified file.")
