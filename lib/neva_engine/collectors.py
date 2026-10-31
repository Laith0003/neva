"""One function a source: read, normalize, raise ShapeError on anything unexpected. Files are opened read-only through
Reader, which refuses a denied path before opening it.

File shapes, in the owner's notes folder:
- goals: a `## Current Move` section with `- Move:`, `- Win condition:` (last ISO date is the date), `- Set on:` lines,
  plus a folder of dated proposal notes and an optional JSON stall counter.
- ledger: Markdown with a fenced yaml block of one-line flow maps under `projects:` and a `totals:` row.
- ledger_events: a yaml `payments:` list of flow maps, dated `- YYYY-MM-DD: <project> paid N` bullets, and an optional
  JSON schedule whose rows quote the source line that says each amount.
- queue: a folder of job JSON files.
- leads: a folder of notes with front matter.
- dates: any notes; a deadline is a date on a line with a deadline word.
"""
from __future__ import annotations

import calendar
import datetime
import glob
import hashlib
import json
import os
import re
from dataclasses import dataclass

from .model import Denied, Fact, ShapeError

ISO = re.compile(r"\b20\d\d-\d\d-\d\d\b")
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
MONTHS["sept"] = 9
MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
ORDINAL = r"(?:st|nd|rd|th)?"
MONTH_DAY = re.compile(rf"\b({MONTH})\.? (\d{{1,2}}){ORDINAL}\b(?:,? (\d{{4}})\b)?", re.I)
DAY_MONTH = re.compile(rf"\b(\d{{1,2}}){ORDINAL} ({MONTH})\b\.?(?:,? (\d{{4}})\b)?", re.I)
FLOW_ROW = re.compile(r"^\s*(\w+):\s*\{(.*)\}\s*$")
ITEM_ROW = re.compile(r"^\s*-\s*\{(.*)\}\s*$")
PAID = re.compile(r"\bpaid\s+([\d,]+)", re.I)
BULLET = re.compile(r"^- (20\d\d-\d\d-\d\d):\s*(.*)$")
NEAR_CHARS = 16


class Reader:
    """The only door to the notes. Paths in config are relative to root, or absolute for files outside it. note() is
    the check every note passes: name and path, then its header. Nothing a collector does runs on a note that failed."""

    def __init__(self, root, deny):
        self.root = os.path.realpath(os.path.expanduser(root))
        self.deny = deny
        self.denied = 0
        self.first_hash = ""
        self.first_path = ""

    def full(self, path):
        return os.path.join(self.root, os.path.expanduser(path))

    def rel(self, path):
        real = os.path.realpath(path)
        return os.path.relpath(real, self.root) if real.startswith(self.root + os.sep) else real

    def allowed(self, path):
        return not self.deny.path_denied(self.rel(path))

    def load(self, full):
        """Text as the gate reads it: no BOM, every line ending a newline, so a line number means the same in both."""
        with open(full, "rb") as f:
            raw = f.read()
        return raw, raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")

    def remember(self, raw, full):
        if not self.first_hash:
            self.first_hash, self.first_path = hashlib.sha256(raw).hexdigest(), full

    def text(self, path):
        """A file with no header to check, such as a plain list. Denied paths still stop here."""
        full = self.full(path)
        if not self.allowed(full):
            self.denied += 1
            raise Denied()
        raw, text = self.load(full)
        self.remember(raw, full)
        return text

    def note(self, path):
        """(text, header), or None for a denied note, counted. Name and path go first, so a denied note is never opened."""
        full = self.full(path)
        rel = self.rel(full)
        if self.deny.path_denied(rel) or self.deny.hit(rel):
            self.denied += 1
            return None
        try:
            raw, text = self.load(full)
        except UnicodeDecodeError:
            self.denied += 1
            return None
        header = read_header(text)
        if header is None or self.deny.tagged(header.tags):
            self.denied += 1
            return None
        self.remember(raw, full)
        return text, header

    def required(self, path):
        """A note a source cannot run without. Denied stops the source, and the error says no more than that."""
        note = self.note(path)
        if note is None:
            raise Denied()
        return note

    def matches(self, pattern):
        """Every file a glob names, in order, denied paths left closed and counted."""
        out = []
        for path in sorted(glob.glob(glob.escape(self.root) + os.sep + pattern)):
            if not os.path.isfile(path):
                continue
            if self.allowed(path):
                out.append(path)
            else:
                self.denied += 1
        return out


@dataclass
class Header:
    fields: dict
    body_at: int
    tags: list


TAG_KEY = re.compile(r"""^\s*["']?(?:tags?)["']?\s*:\s*(.*)$""", re.I)
FLAG_KEY = re.compile(r"""^\s*["']?confidential["']?\s*:\s*(.*)$""", re.I)
FIELD = re.compile(r"^([\w-]+):\s*(.*)$")
NOT_A_TAG = re.compile(r"[\[\]{}&*!|>%@`]")


def tag_tokens(value):
    """One scalar: commas or spaces between tags, quotes and a leading # taken off. ValueError when it is not plainly tags."""
    out = []
    for item in value.split(","):
        item = item.strip()
        if item[:1] in ("'", '"'):
            if len(item) < 2 or item[-1] != item[0]:
                raise ValueError("open quote")
            item = item[1:-1]
        elif item[-1:] in ("'", '"'):
            raise ValueError("open quote")
        if NOT_A_TAG.search(item):
            raise ValueError("not a tag")
        out += [t.lstrip("#") for t in item.split() if t.lstrip("#")]
    return out


def read_tags(rows):
    """Tags in any form the notes use: flow list, scalar, block list. Anything else raises: a tag list that cannot be read
    may be the one that says confidential."""
    tags, i = [], 0
    while i < len(rows):
        flag = FLAG_KEY.match(rows[i])
        if flag:
            word = flag.group(1).strip().strip("'\"").casefold()
            if word in ("true", "yes", "1"):
                tags.append("confidential")
            elif word not in ("false", "no", "0", ""):
                raise ValueError("confidential flag")
        key = TAG_KEY.match(rows[i])
        i += 1
        if not key:
            continue
        value = key.group(1).strip()
        if value.startswith("["):
            if not value.endswith("]"):
                raise ValueError("open list")
            tags += tag_tokens(value[1:-1])
        elif value and value.casefold() not in ("null", "~"):
            tags += tag_tokens(value)
        elif not value:
            while i < len(rows) and rows[i].strip():
                item = re.match(r"^\s*-\s*(.*)$", rows[i])
                if item:
                    tags += tag_tokens(item.group(1))
                elif rows[i][0] in " \t":
                    raise ValueError("indented text under tags")
                else:
                    break
                i += 1
    return tags


def read_header(text):
    """The note's header, or None when it cannot be read: no closing line, a stray opening line, or unreadable tags.
    A note with no front matter has an empty header."""
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        first = next((row for row in lines if row.strip()), "")
        return None if first.rstrip() == "---" else Header({}, 0, [])
    end = next((i for i, row in enumerate(lines[1:], 1) if row.rstrip() == "---"), None)
    if end is None:
        return None
    rows = lines[1:end]
    try:
        tags = read_tags(rows)
    except ValueError:
        return None
    fields = {}
    for row in rows:
        m = FIELD.match(row)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return Header(fields, end + 1, tags)


def real_date(text):
    """True when YYYY-MM-DD names a day that exists."""
    try:
        datetime.date.fromisoformat(text)
        return True
    except (TypeError, ValueError):
        return False


def line_no(text, index):
    return text.count("\n", 0, index) + 1


def flow_map(body):
    """`a: 1, b: "x, y"` to a dict. Numbers become ints; a quoted string may hold commas."""
    out = {}
    for m in re.finditer(r'(\w+):\s*("(?:[^"\\]|\\.)*"|[^,]+)', body):
        raw = m.group(2).strip()
        out[m.group(1)] = raw[1:-1] if raw.startswith('"') else int(raw) if re.fullmatch(r"-?\d+", raw) else raw
    return out


def yaml_block(text, need, where):
    for m in re.finditer(r"^```yaml\n(.*?)^```", text, re.S | re.M):
        if re.search(rf"^{need}:", m.group(1), re.M):
            return m.group(1), line_no(text, m.start(1))
    raise ShapeError(f"{where}: no fenced yaml block with `{need}:`. Add the block back.")


def collect_goals(cfg, reader, today):
    where = cfg["path"]
    text, _ = reader.required(cfg["path"])
    m = re.search(r"^## Current Move\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        raise ShapeError(f"{where}: no `## Current Move` section. Add it back.")
    block, offset = m.group(1), m.start(1)
    path = reader.full(cfg["path"])
    title = re.search(r"^- Move:[ \t]*(.+)$", block, re.M)
    value = {"win_by": None, "set_on": None}
    memo = {"title": ""}
    facts = []
    if title:
        raw = title.group(1).strip()
        link = re.match(r"\[\[([^\]]+)\]\]", raw)
        memo["title"] = link.group(1) if link else raw.split(". ")[0].rstrip(".")
        win = re.search(r"^- Win condition:[ \t]*(.+)$", block, re.M)
        dates = ISO.findall(win.group(1)) if win else []
        if dates:
            value["win_by"], value["win_line"] = dates[-1], line_no(text, offset + win.start())
        seton = re.search(r"^- Set on:[ \t]*(20\d\d-\d\d-\d\d)", block, re.M)
        if seton:
            value["set_on"], value["set_line"] = seton.group(1), line_no(text, offset + seton.start())
        for key in ("win_by", "set_on"):
            if value[key] and not real_date(value[key]):
                raise ShapeError(f"{where}: {value[key]} in Current Move is not a real date. Fix the date.")
    facts.append(Fact("goals", "move", "current", value, path, line_no(text, offset + title.start()) if title else None,
                      quote=title.group(0) if title else "", memo=memo))
    if cfg.get("stall_state"):
        state = os.path.expanduser(cfg["stall_state"])
        try:
            with open(state, encoding="utf-8") as f:
                stall = json.load(f)
        except FileNotFoundError:
            stall = None
        except ValueError as e:
            raise ShapeError(f"{state}: not JSON ({e}). Fix or remove the file.")
        if stall is not None:
            if not isinstance(stall.get("stalled_days"), int):
                raise ShapeError(f"{state}: no integer `stalled_days`. Fix or remove the file.")
            facts.append(Fact("goals", "stall", "current", {"days": stall["stalled_days"]}, state))
    facts.extend(collect_proposals(cfg, reader))
    return facts


def collect_proposals(cfg, reader):
    if not cfg.get("proposals"):
        return []
    markers = cfg.get("failed_markers", [])
    notes = reader.matches(os.path.join(cfg["proposals"], cfg.get("proposal_glob", "*.md")))
    dated = sorted((d[0], p) for p in notes for d in [ISO.findall(os.path.basename(p))] if d and real_date(d[0]))
    failed_on = []
    if cfg.get("failure_file"):
        try:
            note = reader.note(cfg["failure_file"])
        except FileNotFoundError:
            note = None
        failed_on = [d for d in re.findall(cfg["failure_pattern"], note[0]) if real_date(d)] if note else []
    newest_good = None
    newest_failed = max(failed_on) if failed_on else None
    for day, path in reversed(dated):
        note = reader.note(path)
        if note is None:
            continue
        body = note[0]
        if any(m in body for m in markers) or re.search(r"(?m)^status: failed$", body):
            newest_failed = max(newest_failed or "", day)
            continue
        newest_good = (day, path, body)
        break
    facts = []
    if newest_failed:
        facts.append(Fact("goals", "proposal_failed", "newest", {"date": newest_failed}, ts=newest_failed,
                          path=reader.full(cfg.get("failure_file") or cfg["proposals"])))
    if newest_good:
        day, path, body = newest_good
        picked = re.search(r"(?m)^\s*\|\s*1\s*\|\s*([^|]+?)\s*\|", body)
        do = re.search(r"\*\*Do (\w)\.\*\*\s*([^\n]*)", body)
        if do:
            named = re.search(rf"\*\*{do.group(1)}\. (.+?)\.?\*\*", body)
            title, line = (named.group(1), line_no(body, named.start())) if named else (f"Option {do.group(1)}", line_no(body, do.start()))
        elif picked:
            title, line = picked.group(1), line_no(body, picked.start(1))
        else:
            raise ShapeError(f"{os.path.basename(path)}: no rank 1 row and no `**Do X.**` line. Add one so the pick can be read.")
        why = re.search(r"\*\*Recommendation:[^*]*\*\*\s*([^\n]*)", body) or do
        why_text, why_line = "", None
        if why:
            sentence = why.group(why.lastindex).split(". ")[0].strip()
            why_text, why_line = sentence.rstrip(".") + "." if sentence else "", line_no(body, why.start())
        # The proposal's own first step, or none. A figure here would need a source line of its own, so it stays out.
        first = re.search(r"(?m)^\s*(Start with [^\n]*?\.)(?:\s|$)", body)
        first_text = first.group(1) if first and not re.search(r"\d", first.group(1)) else None
        facts.append(Fact("goals", "proposal", "newest", {"date": day, "why_line": why_line}, path, line, ts=day, quote=title,
                          memo={"title": title, "why": why_text, "first": first_text, "name": os.path.splitext(os.path.basename(path))[0]}))
    return facts


def collect_ledger(cfg, reader, today):
    where = cfg["path"]
    text, header = reader.required(cfg["path"])
    path = reader.full(cfg["path"])
    block, start = yaml_block(text, "projects", where)
    currency = re.search(r"^currency:\s*(\w+)", block, re.M)
    if not currency:
        raise ShapeError(f"{where}: the yaml block has no `currency:`. Add it.")
    facts, in_projects = [], False
    totals = None
    for i, row in enumerate(block.split("\n")):
        no = start + i
        if row.startswith("projects:"):
            in_projects = True
            continue
        m = FLOW_ROW.match(row)
        if row.startswith("totals:"):
            in_projects = False
            if not m:
                raise ShapeError(f"{where}:{no}: `totals:` is not a one-line map. Write it as `totals: {{ remaining: 0 }}`.")
            totals = (flow_map(m.group(2)), no, row)
        elif in_projects and m:
            data = flow_map(m.group(2))
            for key in ("contract", "received", "remaining"):
                if not isinstance(data.get(key), int):
                    raise ShapeError(f"{where}:{no}: project {m.group(1)} has no integer `{key}`. Add the field.")
            facts.append(Fact("ledger", "project", m.group(1), {k: data[k] for k in ("contract", "received", "remaining")},
                              path, no, quote=row))
        elif in_projects and row.strip():
            raise ShapeError(f"{where}:{no}: a project row is not a one-line map. Write it as `Name: {{ remaining: 0 }}`.")
    if totals is None:
        raise ShapeError(f"{where}: the yaml block has no `totals:` row. Add it.")
    for key in ("received", "remaining"):
        if not isinstance(totals[0].get(key), int):
            raise ShapeError(f"{where}:{totals[1]}: `totals:` has no integer `{key}`. Add the field.")
    updated = header.fields.get("updated", "")
    if updated and not real_date(updated):
        raise ShapeError(f"{where}: updated: {updated} is not a real date. Fix the date.")
    file_day = datetime.date.fromtimestamp(os.stat(path).st_mtime).isoformat()
    upd_line = next((i + 1 for i, r in enumerate(text.split("\n")) if r.startswith("updated:")), None)
    facts.append(Fact("ledger", "totals", "ledger", {"currency": currency.group(1), "received": totals[0]["received"],
                                                     "remaining": totals[0]["remaining"], "updated": updated,
                                                     "updated_line": upd_line, "file_day": file_day},
                      path, totals[1], quote=totals[2]))
    return facts


def collect_events(cfg, reader, today):
    where = cfg["path"]
    text, _ = reader.required(cfg["path"])
    path = reader.full(cfg["path"])
    block, start = yaml_block(text, "payments", where)
    facts = []
    for i, row in enumerate(block.split("\n")):
        m = ITEM_ROW.match(row)
        if m:
            data = flow_map(m.group(1))
            for key in ("project", "amount", "date"):
                if key not in data:
                    raise ShapeError(f"{where}:{start + i}: a payment has no `{key}`. Add the field.")
            if not real_date(str(data["date"])):
                raise ShapeError(f"{where}:{start + i}: payment date {data['date']} is not YYYY-MM-DD. Fix the date.")
            facts.append(Fact("ledger_events", "payment", f"{data['project']}:{data['date']}:{start + i}",
                              {"project": data["project"], "amount": data["amount"], "date": data["date"]}, path, start + i,
                              ts=data["date"], quote=row))
    for i, row in enumerate(text.split("\n")):
        m = BULLET.match(row)
        paid = PAID.search(m.group(2)) if m else None
        if paid:
            who = re.match(r"(\w+) paid\b", m.group(2))
            if who:
                if not real_date(m.group(1)):
                    raise ShapeError(f"{where}:{i + 1}: {m.group(1)} is not a real date. Fix the date.")
                facts.append(Fact("ledger_events", "payment", f"{who.group(1)}:{m.group(1)}:{i + 1}",
                                  {"project": who.group(1), "amount": int(paid.group(1).replace(",", "")), "date": m.group(1)},
                                  path, i + 1, ts=m.group(1), quote=row))
    facts.extend(collect_schedule(cfg, reader))
    return facts


def collect_schedule(cfg, reader):
    """Rows say which part of a balance is due and which line says so. A quote that left its file is not a row: the
    project's due figure goes unknown, which is what a stale schedule should do."""
    if not cfg.get("schedule"):
        return []
    path = os.path.expanduser(cfg["schedule"])
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ShapeError(f"{path}: not JSON ({e}). Fix the file.")
    facts = []
    for n, item in enumerate(data.get("items", [])):
        for key in ("project", "label", "amount", "due", "path", "quote"):
            if key not in item:
                raise ShapeError(f"{path}: row {n + 1} has no `{key}`. Add the field.")
        body, _ = reader.required(item["path"])
        at = body.find(item["quote"])
        facts.append(Fact("ledger_events", "schedule", f"{item['project']}:{item['label']}",
                          {"project": item["project"], "label": item["label"], "amount": item["amount"], "due": bool(item["due"]),
                           "found": at >= 0}, reader.full(item["path"]), line_no(body, at) if at >= 0 else None,
                          quote=item["quote"]))
    return facts


def collect_queue(cfg, reader, today):
    state_dir = os.path.expanduser(cfg["state_dir"])
    if not os.path.isdir(state_dir):
        raise FileNotFoundError(state_dir)
    review = re.compile(cfg["review_pattern"])
    facts = []
    for path in sorted(glob.glob(glob.escape(state_dir) + "/*.json")):
        name = os.path.splitext(os.path.basename(path))[0]
        if name.startswith("_"):
            continue
        if reader.deny.hit(name) or not reader.allowed(path):
            reader.denied += 1
            continue
        try:
            with open(path, encoding="utf-8") as f:
                job = json.load(f)
        except ValueError as e:
            raise ShapeError(f"{name}: not JSON ({e}). Fix or remove {path}.")
        if not isinstance(job, dict) or not isinstance(job.get("status"), str):
            raise ShapeError(f"{name}: no `status` field. Fix or remove {path}.")
        reviewed = job.get("reviewed") or job.get("reviewed_sha") or job.get("merged") or \
            re.search(r"\bmerged\b", str(job.get("note", "")), re.I)
        waits = job["status"] == "done" and bool(review.search(str(job.get("reason", "")))) and not reviewed
        finished = job.get("finished")
        day = datetime.date.fromtimestamp(finished).isoformat() if isinstance(finished, (int, float)) else None
        facts.append(Fact("queue", "job", name, {"status": job["status"], "waits_review": waits, "finished": day}, path, ts=day))
    return facts


def collect_leads(cfg, reader, today):
    facts = []
    closed = {s.casefold() for s in cfg.get("closed", [])}
    for path in reader.matches(os.path.join(cfg["dir"], "*.md")):
        name = os.path.splitext(os.path.basename(path))[0]
        note = reader.note(path)
        if note is None:
            continue
        text, header = note
        fields = header.fields
        if "status" not in fields:
            raise ShapeError(f"{name}: no front matter with `status`. Add it to {path}.")
        rows = text.split("\n")
        best, line = "", None
        for key in ("date", "updated"):
            for i, row in enumerate(rows[:40]):
                m = re.match(rf"^{key}:\s*(20\d\d-\d\d-\d\d)", row)
                if m and real_date(m.group(1)) and m.group(1) >= best:
                    best, line = m.group(1), i + 1
        mtime = datetime.date.fromtimestamp(os.stat(path).st_mtime).isoformat()
        by_file = mtime > best
        last = mtime if by_file else best
        if last:
            facts.append(Fact("leads", "lead", name, {"status": fields["status"].casefold(), "closed": fields["status"].casefold() in closed,
                                                      "last": last, "by_file": by_file}, path, line, ts=last,
                              quote=rows[line - 1] if line else ""))
    return facts


def dates_on(row, today):
    """Every real date a line names, as (iso, printed). A year on the line is read; a month and day with no year means the
    nearest such date. "may" in lower case is a verb."""
    found = [(d, d) for d in ISO.findall(row) if real_date(d)]
    for rx, month_at, day_at in ((MONTH_DAY, 1, 2), (DAY_MONTH, 2, 1)):
        for m in rx.finditer(row):
            word = m.group(month_at)
            if word == "may":
                continue
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                d = datetime.date(year, MONTHS[word.lower()], int(m.group(day_at)))
                if not m.group(3) and (today - d).days > 180:
                    d = d.replace(year=d.year + 1)
            except ValueError:
                continue
            found.append((d.isoformat(), m.group(0)))
    return found


def near_word(row, printed, deadline):
    """A deadline word beside the date, or anywhere on a table row. A word elsewhere on a long line is about something else."""
    if row.lstrip().startswith("|"):
        return bool(deadline.search(row))
    at = row.find(printed)
    return bool(deadline.search(row[max(0, at - NEAR_CHARS):at + len(printed) + NEAR_CHARS]))


def collect_dates(cfg, reader, today):
    words = "|".join(re.escape(w) for w in cfg["words"])
    deadline = re.compile(rf"(?<![^\W\d_])(?:{words})(?![^\W\d_])", re.I)
    done = cfg.get("done_words", [])
    done_rx = re.compile(r"(?<![^\W\d_])(?:" + "|".join(re.escape(w) for w in done) + r")(?![^\W\d_])", re.I) if done else None
    closed = {s.casefold() for s in cfg.get("closed_status", [])}
    titles = cfg.get("titles", {})
    skip = set(cfg.get("skip_notes", []))
    facts, seen = [], set()
    for pattern in cfg["globs"]:
        for path in reader.matches(pattern):
            if path in seen:
                continue
            seen.add(path)
            note = reader.note(path)
            if note is None:
                continue
            text, header = note
            body_at = header.body_at
            if header.fields.get("status", "").casefold() in closed:
                continue
            name = note_name(path, cfg)
            if name in skip:
                continue
            for i, row in enumerate(text.split("\n")):
                if i < body_at or not deadline.search(row):
                    continue
                if re.match(r"\s*- \[[xX]\]", row) or "~~" in row or (done_rx and done_rx.search(row)):
                    continue
                if reader.deny.hit(row):
                    reader.denied += 1
                    continue
                for iso, printed in dates_on(row, today):
                    if not near_word(row, printed, deadline):
                        continue
                    facts.append(Fact("dates", "deadline", f"{name}:{iso}:{i + 1}",
                                      {"note": name, "date": iso}, path, i + 1, ts=iso, quote=row,
                                      memo={"title": titles.get(name, name), "printed": printed}))
    return facts


def note_name(path, cfg):
    """A project note is named CLAUDE.md or the like, so the folder names it."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.basename(os.path.dirname(path)) if stem in cfg.get("folder_named", []) else stem


COLLECTORS = {"goals": collect_goals, "ledger": collect_ledger, "ledger_events": collect_events,
              "queue": collect_queue, "leads": collect_leads, "dates": collect_dates}
LABELS = {"goals": "move", "ledger": "money", "ledger_events": "dated money", "queue": "build queue",
          "leads": "leads", "dates": "notes"}
