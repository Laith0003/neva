#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""GitHub-native epic coordination for the /epic-* commands. Python 3 standard library plus the
`gh` CLI.

The issue body is the source of truth: a fenced JSON block between
`<!-- neva-coordination:start -->` and `<!-- neva-coordination:end -->` holds status, owner,
branch, validation, review, tasks and dependencies. Labels mirror that state. A local SQLite
cache keeps one work item per epic.

Write gate (the Neva rule for anything that leaves the machine):
  Reads (issue view, issue list) always run.
  Every GitHub write (issue edit, label change, comment) is PLANNED first and never executed
  without explicit human confirmation:
    no flag      print the plan. On an interactive terminal ask "yes" before applying; anywhere
                 else (an agent's shell, CI) write nothing and exit 3.
    --yes        apply the plan. Only pass it when the human typed it in the same command or
                 answered yes to the plan just shown.
    --plan-id X  with --yes: refuse (exit 4) if the recomputed plan differs from the one shown.
    --dry-run    preview only, never writes, exit 0.
  The local cache is only written after the GitHub writes succeed.

Exit codes: 0 done, 1 error, 3 confirmation required (nothing written), 4 plan changed.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys

DEFAULT_CONFIG_FILE = "github-native-coordination.json"
DEFAULT_SECTION_MARKER = "neva-coordination"
DEFAULT_SCHEMA_VERSION = "neva.github.coordination.v1"
DEFAULT_LABELS = {
    "epic": "epic",
    "available": "coordination:available",
    "claimed": "coordination:claimed",
    "ready": "coordination:ready",
    "blocked": "coordination:blocked",
    "validated": "coordination:validated",
    "reviewRequested": "coordination:review-requested",
    "reviewApproved": "coordination:review-approved",
    "reviewChangesRequested": "coordination:review-changes-requested",
    "published": "coordination:published",
    "synced": "coordination:synced",
}
DEFAULT_POLICY = {
    "schemaVersion": DEFAULT_SCHEMA_VERSION,
    "sectionMarker": DEFAULT_SECTION_MARKER,
    "labels": dict(DEFAULT_LABELS),
    "review": {"required": True, "defaultMode": "required"},
    "validation": {"required": True},
    "branchModel": {"epicOnly": True, "taskBranches": False},
    "project": {
        "enabled": False,
        "fieldNames": {"status": "Status", "owner": "Owner", "branch": "Branch",
                       "validation": "Validation", "review": "Review"},
    },
}
ISSUE_FIELDS = "number,title,body,url,state,labels,author,updatedAt,assignees"
REVIEW_STATES = ("approved", "requested", "changes-requested", "blocked")

EXIT_CONFIRM = 3
EXIT_PLAN_CHANGED = 4


class CoordinationError(Exception):
    pass


def now_iso():
    d = datetime.datetime.now(datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def dumps(obj, indent=2):
    return json.dumps(obj, indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------- policy

def _obj(v):
    return v if isinstance(v, dict) else {}


def load_policy(root_dir=None, config_path=None):
    root_dir = root_dir or os.getcwd()
    resolved = os.path.abspath(config_path) if config_path else os.path.join(root_dir, "config", DEFAULT_CONFIG_FILE)
    base = json.loads(json.dumps(DEFAULT_POLICY))
    if not os.path.exists(resolved):
        if config_path:
            raise CoordinationError(f"--config: file not found at {resolved}. Fix the path or drop the flag.")
        base["sourcePath"] = None
        return base
    try:
        with open(resolved, encoding="utf-8") as fh:
            parsed = json.load(fh)
    except (OSError, ValueError) as e:
        raise CoordinationError(f"Failed to load policy from {resolved}: {e}")
    if not isinstance(parsed, dict):
        kind = "array" if isinstance(parsed, list) else type(parsed).__name__
        raise CoordinationError(f"Policy file {resolved} must contain a JSON object, got {kind}")
    labels = dict(DEFAULT_LABELS)
    labels.update(_obj(parsed.get("labels")))
    if not isinstance(labels.get("epic"), str) or not labels["epic"].strip():
        raise CoordinationError(f"Policy file {resolved} must define labels.epic as a non-empty string")
    project = _obj(parsed.get("project"))
    policy = dict(base)
    policy.update(parsed)
    policy["labels"] = labels
    policy["review"] = {**base["review"], **_obj(parsed.get("review"))}
    policy["validation"] = {**base["validation"], **_obj(parsed.get("validation"))}
    policy["branchModel"] = {**base["branchModel"], **_obj(parsed.get("branchModel"))}
    policy["project"] = {**base["project"], **project,
                         "fieldNames": {**base["project"]["fieldNames"], **_obj(project.get("fieldNames"))}}
    policy["sourcePath"] = resolved
    return policy


# ---------------------------------------------------------------- parsing

def extract_coordination_state(body, policy=DEFAULT_POLICY):
    marker = re.escape(policy.get("sectionMarker") or DEFAULT_SECTION_MARKER)
    rx = re.compile(r"<!--\s*" + marker + r":start\s*-->\s*```json\s*([\s\S]*?)\s*```\s*<!--\s*" + marker + r":end\s*-->", re.M)
    m = rx.search(str(body or ""))
    if not m:
        return None
    try:
        parsed = json.loads(m.group(1))
    except ValueError as e:
        raise ValueError(f"Malformed coordination JSON in body: {e}. Raw: {m.group(1)[:120]}")
    return parsed if isinstance(parsed, dict) else None


def extract_issue_references(text):
    refs = set()
    for m in re.finditer(r"(?:^|[^\d])#(\d+)\b", str(text or "")):
        refs.add(int(m.group(1)))
    return sorted(refs)


def extract_tasks(body):
    tasks = []
    in_tasks = False
    for raw in re.split(r"\r?\n", str(body or "")):
        line = raw.strip()
        if re.match(r"^#{2,3}\s+tasks\b", line, re.I) or re.match(r"^#{2,3}\s+task list\b", line, re.I):
            in_tasks = True
            continue
        if in_tasks and re.match(r"^#{2,3}\s+\S", line):
            break
        if in_tasks:
            m = re.match(r"^- \[( |x)\]\s+(.+)$", line, re.I)
            if m:
                tasks.append({"title": m.group(2).strip(), "done": m.group(1).lower() == "x"})
    return tasks


def render_coordination_state(state, policy=DEFAULT_POLICY):
    marker = policy.get("sectionMarker") or DEFAULT_SECTION_MARKER
    payload = {
        "schemaVersion": state.get("schemaVersion") or policy.get("schemaVersion") or DEFAULT_SCHEMA_VERSION,
        "kind": state.get("kind") or "epic",
        "status": state.get("status") or "available",
        "owner": state.get("owner") or None,
        "branch": state.get("branch") or None,
        "validation": state.get("validation") or "pending",
        "review": state.get("review") or "not-requested",
        "project": state.get("project") or {"state": "backlog", "fields": {}},
        "dependencies": state["dependencies"] if isinstance(state.get("dependencies"), list) else [],
        "tasks": state["tasks"] if isinstance(state.get("tasks"), list) else [],
        "labels": state["labels"] if isinstance(state.get("labels"), list) else [],
        "lastAction": state.get("lastAction") or "sync",
        "lastActionAt": state.get("lastActionAt") or now_iso(),
        "lastSyncAt": state.get("lastSyncAt") or now_iso(),
        "notes": state.get("notes") or None,
    }
    return "\n".join([f"<!-- {marker}:start -->", "```json", dumps(payload), "```", f"<!-- {marker}:end -->"])


def merge_issue_body(issue, next_state, policy=DEFAULT_POLICY):
    body = str(issue.get("body") or "")
    marker = re.escape(policy.get("sectionMarker") or DEFAULT_SECTION_MARKER)
    rendered = render_coordination_state(next_state, policy)
    rx = re.compile(r"\n?<!--\s*" + marker + r":start\s*-->[\s\S]*?<!--\s*" + marker + r":end\s*-->\n?", re.M)
    if rx.search(body):
        return rx.sub(lambda _m: "\n" + rendered + "\n", body, count=1).strip() + "\n"
    trimmed = body.rstrip()
    if not trimmed:
        return rendered + "\n"
    return f"{trimmed}\n\n{rendered}\n"


def normalize_body_for_plan(body):
    return re.sub(r'"(lastSyncAt|lastActionAt)"\s*:\s*[^,}\n]+', r'"\1": NORMALIZED', body or "")


# ---------------------------------------------------------------- gh

def normalize_repo(repo):
    parts = [p for p in str(repo or "").split("/") if p]
    if len(parts) != 2:
        raise CoordinationError(f'--repo: invalid format "{repo}". Use owner/repo, for example octo/widgets.')
    return f"{parts[0]}/{parts[1]}"


def normalize_issue_number(value, flag="issue number"):
    try:
        n = int(str(value), 10)
    except (TypeError, ValueError):
        raise CoordinationError(f"{flag}: '{value}' is not a positive integer. Pass the number only, for example 42.")
    if n <= 0:
        raise CoordinationError(f"{flag}: '{value}' is not a positive integer. Pass the number only, for example 42.")
    return n


def normalize_label(label):
    if isinstance(label, str):
        return label.strip()
    if isinstance(label, dict):
        return str(label.get("name") or label.get("label") or "").strip()
    return ""


def normalize_labels(labels):
    return sorted({normalize_label(x) for x in (labels if isinstance(labels, list) else []) if normalize_label(x)})


def run_gh(args):
    try:
        r = subprocess.run(["gh"] + args, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        raise CoordinationError("gh CLI not found on PATH. Install it from cli.github.com and run `gh auth login`.")
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()
        raise CoordinationError(f"gh {' '.join(args[:3])} failed: {detail}")
    return r.stdout or ""


def run_gh_json(args):
    out = run_gh(args)
    try:
        return json.loads(out or "null")
    except ValueError as e:
        raise CoordinationError(f"gh {' '.join(args[:3])} returned invalid JSON: {e}")


def get_issue(repo, number):
    data = run_gh_json(["issue", "view", str(number), "--repo", repo, "--json", ISSUE_FIELDS])
    if not data:
        raise CoordinationError(f"Unable to load issue #{number} from {repo}")
    return data


def list_issues(repo, state="all", limit=100, label=None, search=None):
    args = ["issue", "list", "--repo", repo, "--state", state, "--limit", str(limit)]
    if label:
        args += ["--label", label]
    if search:
        args += ["--search", search]
    args += ["--json", ISSUE_FIELDS]
    return run_gh_json(args) or []


def edit_args(repo, number, body=None, add_labels=(), remove_labels=()):
    args = ["issue", "edit", str(number), "--repo", repo]
    if body is not None:
        args += ["--body", body]
    for lab in add_labels:
        args += ["--add-label", lab]
    for lab in remove_labels:
        args += ["--remove-label", lab]
    return args


def comment_args(repo, number, body):
    return ["issue", "comment", str(number), "--repo", repo, "--body", body]


# ---------------------------------------------------------------- state

def slugify_segment(value):
    s = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return s or "unknown"


def author_login(issue):
    a = issue.get("author") if isinstance(issue, dict) else None
    return a.get("login") if isinstance(a, dict) and a.get("login") else None


def default_coordination_state(issue, policy=DEFAULT_POLICY):
    body = (issue or {}).get("body") or ""
    return {
        "schemaVersion": policy.get("schemaVersion") or DEFAULT_SCHEMA_VERSION,
        "kind": "epic",
        "status": "available",
        "owner": author_login(issue or {}),
        "branch": None,
        "validation": "pending",
        "review": "not-requested",
        "project": {"state": "backlog", "fields": {}},
        "dependencies": extract_issue_references(body),
        "tasks": extract_tasks(body),
        "labels": normalize_labels((issue or {}).get("labels")),
        "lastAction": "sync",
        "lastActionAt": now_iso(),
        "lastSyncAt": now_iso(),
        "notes": None,
    }


def get_coordination_state(issue, policy=DEFAULT_POLICY):
    try:
        existing = extract_coordination_state((issue or {}).get("body"), policy)
    except ValueError as e:
        sys.stderr.write(f"[github-coordination] Warning: {e} (issue #{(issue or {}).get('number')})\n")
        existing = None
    default = default_coordination_state(issue, policy)
    if not existing:
        return default
    body = (issue or {}).get("body") or ""
    merged = dict(default)
    merged.update(existing)
    merged["project"] = {**default["project"], **_obj(existing.get("project"))}
    merged["tasks"] = existing["tasks"] if isinstance(existing.get("tasks"), list) else extract_tasks(body)
    merged["dependencies"] = (existing["dependencies"] if isinstance(existing.get("dependencies"), list)
                              else extract_issue_references(body))
    merged["labels"] = existing["labels"] if isinstance(existing.get("labels"), list) else normalize_labels(issue.get("labels"))
    return merged


_UNSET = object()


def build_state_from_action(issue, current, action, policy=DEFAULT_POLICY, **opts):
    ts = now_iso()
    nxt = dict(current)
    nxt.update({
        "schemaVersion": policy.get("schemaVersion") or DEFAULT_SCHEMA_VERSION,
        "kind": "epic",
        "lastAction": action,
        "lastActionAt": ts,
        "lastSyncAt": ts,
        "labels": normalize_labels(issue.get("labels")),
        "dependencies": (current["dependencies"] if isinstance(current.get("dependencies"), list)
                         else extract_issue_references(issue.get("body"))),
        "tasks": current["tasks"] if isinstance(current.get("tasks"), list) else extract_tasks(issue.get("body")),
    })
    for key in ("owner", "branch", "validation", "review", "status", "notes", "tasks", "dependencies"):
        v = opts.get(key, _UNSET)
        if v is not _UNSET:
            nxt[key] = v
    ps = opts.get("projectState", _UNSET)
    if ps is not _UNSET:
        nxt["project"] = {**_obj(nxt.get("project")), "state": ps}
    return nxt


def desired_labels_for_state(state, policy=DEFAULT_POLICY):
    k = policy.get("labels") or DEFAULT_LABELS
    labels = [k.get("epic"), k.get("synced")]
    st, val, rev = state.get("status"), state.get("validation"), state.get("review")
    if st == "available":
        labels.append(k.get("available"))
    if st == "claimed":
        labels.append(k.get("claimed"))
    if st == "ready":
        labels.append(k.get("ready"))
    if st == "blocked":
        labels.append(k.get("blocked"))
    if val == "passed":
        labels.append(k.get("validated"))
    if rev == "requested":
        labels.append(k.get("reviewRequested"))
    if rev == "approved":
        labels.append(k.get("reviewApproved"))
    if rev == "changes-requested":
        labels.append(k.get("reviewChangesRequested"))
    if st == "published":
        labels.append(k.get("published"))
    return sorted({x for x in labels if x})


def stale_coordination_labels(issue, next_labels, policy):
    epic = (policy.get("labels") or {}).get("epic")
    return [x for x in normalize_labels(issue.get("labels"))
            if (x.startswith("coordination:") or x == epic) and x not in next_labels]


def build_issue_comment(action, repo, number, state, extra=None):
    lines = [
        f"Neva coordination {action}",
        f"Repo: {repo}",
        f"Issue: #{number}",
        f"Status: {state.get('status')}",
        f"Owner: {state.get('owner') or '(unassigned)'}",
        f"Branch: {state.get('branch') or '(none)'}",
        f"Validation: {state.get('validation') or 'pending'}",
        f"Review: {state.get('review') or 'not-requested'}",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    lines += ["", "This comment is part of the append-only coordination audit trail."]
    return "\n".join(lines)


def map_state_to_work_item_status(status):
    if status == "blocked":
        return "blocked"
    if status == "published":
        return "done"
    if status in ("validated", "reviewing", "claimed", "ready"):
        return "in-progress"
    if status == "changes-requested":
        return "needs-review"
    return "open"


def summarize_project(state, policy=DEFAULT_POLICY):
    proj = _obj(state.get("project"))
    return {"enabled": bool(_obj(policy.get("project")).get("enabled")),
            "state": proj.get("state") or "backlog",
            "fields": dict(_obj(proj.get("fields")))}


def epic_work_item_id(repo, number):
    return f"github-{slugify_segment(repo)}-epic-{number}"


def summarize_state(repo, issue, state, action, policy=DEFAULT_POLICY):
    return {
        "schemaVersion": state.get("schemaVersion") or policy.get("schemaVersion") or DEFAULT_SCHEMA_VERSION,
        "repo": repo,
        "issueNumber": issue.get("number"),
        "issueUrl": issue.get("url") or None,
        "issueTitle": issue.get("title"),
        "action": action,
        "status": state.get("status"),
        "owner": state.get("owner") or None,
        "branch": state.get("branch") or None,
        "validation": state.get("validation") or "pending",
        "review": state.get("review") or "not-requested",
        "project": summarize_project(state, policy),
        "dependencies": state["dependencies"] if isinstance(state.get("dependencies"), list) else [],
        "tasks": state["tasks"] if isinstance(state.get("tasks"), list) else [],
        "labels": normalize_labels(issue.get("labels")),
        "workItemId": epic_work_item_id(repo, issue.get("number")),
        "lastActionAt": state.get("lastActionAt") or None,
        "lastSyncAt": state.get("lastSyncAt") or None,
    }


def assert_claimable(issue, state):
    if str(issue.get("state") or "").lower() != "open":
        raise CoordinationError(f"Issue #{issue.get('number')} is not open. Reopen it on GitHub or pick another epic.")
    if state.get("status") == "claimed":
        raise CoordinationError(f"Issue #{issue.get('number')} is already claimed by {state.get('owner') or 'unknown'}.")


def verify_dependencies_closed(repo, deps, limit, all_issues=None):
    if not isinstance(deps, list) or not deps:
        return []
    issues = all_issues if all_issues is not None else list_issues(repo, state="all", limit=limit or 200)
    closed = []
    for n in deps:
        hit = next((i for i in issues if str(i.get("number")) == str(n)), None)
        if hit is None:
            sys.stderr.write(f"[github-coordination] Warning: dependency issue #{n} not found in issue list "
                             f"(different repo or beyond --limit)\n")
        elif str(hit.get("state") or "").lower() == "closed":
            closed.append(n)
    return closed


# ---------------------------------------------------------------- plan

class Plan:
    """Collects GitHub writes and cache upserts. Nothing touches GitHub until apply()."""

    def __init__(self, repo):
        self.repo = repo
        self.writes = []
        self.store_ops = []

    def edit(self, number, body=None, add_labels=(), remove_labels=(), summary=""):
        add_labels, remove_labels = list(add_labels), list(remove_labels)
        if body is None and not add_labels and not remove_labels:
            return
        self.writes.append({"kind": "edit", "issue": number, "body": body,
                            "addLabels": add_labels, "removeLabels": remove_labels, "summary": summary})

    def comment(self, number, body):
        self.writes.append({"kind": "comment", "issue": number, "body": body})

    def upsert(self, issue, state, action):
        self.store_ops.append((issue, state, action))

    def plan_id(self):
        canon = []
        for w in self.writes:
            c = dict(w)
            c.pop("summary", None)
            if c.get("body") is not None:
                c["body"] = normalize_body_for_plan(c["body"])
            canon.append(c)
        return hashlib.sha256(json.dumps(canon, sort_keys=True).encode("utf-8")).hexdigest()[:12]

    def describe(self):
        out = []
        for w in self.writes:
            if w["kind"] == "edit":
                d = {"kind": "edit", "issue": w["issue"]}
                if w["body"] is not None:
                    d["body"] = w["summary"] or "coordination block rewritten"
                if w["addLabels"]:
                    d["addLabels"] = w["addLabels"]
                if w["removeLabels"]:
                    d["removeLabels"] = w["removeLabels"]
                out.append(d)
            else:
                out.append({"kind": "comment", "issue": w["issue"], "body": w["body"]})
        return out

    def apply(self):
        done = 0
        try:
            for w in self.writes:
                if w["kind"] == "edit":
                    run_gh(edit_args(self.repo, w["issue"], w["body"], w["addLabels"], w["removeLabels"]))
                else:
                    run_gh(comment_args(self.repo, w["issue"], w["body"]))
                done += 1
        except CoordinationError as e:
            raise CoordinationError(f"{e}. Applied {done} of {len(self.writes)} writes before the failure; "
                                    f"run /epic-sync --repo {self.repo} to see the current state.")
        return done


def block_summary(state):
    return (f"coordination block: status={state.get('status')}, owner={state.get('owner') or '(unassigned)'}, "
            f"branch={state.get('branch') or '(none)'}, validation={state.get('validation')}, "
            f"review={state.get('review')}")


def final_labels(issue, add, remove):
    """The label set GitHub will hold after the edit. Recorded in the block so a later sync
    does not see a stale list and rewrite the body again (upstream recorded the pre-edit set)."""
    return sorted((set(normalize_labels(issue.get("labels"))) - set(remove)) | set(add))


def plan_full_update(plan, issue, next_state, policy, action, comment_action=None, extra=None):
    labels = desired_labels_for_state(next_state, policy)
    remove = stale_coordination_labels(issue, labels, policy)
    next_state["labels"] = final_labels(issue, labels, remove)
    plan.edit(issue["number"], body=merge_issue_body(issue, next_state, policy),
              add_labels=labels, remove_labels=remove, summary=block_summary(next_state))
    if comment_action:
        plan.comment(issue["number"], build_issue_comment(comment_action, plan.repo, issue["number"], next_state, extra))
    tracked = dict(issue, labels=next_state["labels"])
    plan.upsert(tracked, next_state, action)
    return tracked


# ---------------------------------------------------------------- actions

def action_claim(repo, number, opts, policy, plan):
    # Read, check, write is not atomic: two callers can both pass the check. Serialize claims
    # externally (one coordinator, or a branch-protection rule) until GitHub offers a lock.
    issue = get_issue(repo, number)
    current = get_coordination_state(issue, policy)
    assert_claimable(issue, current)
    nxt = build_state_from_action(
        issue, current, "claim", policy,
        owner=opts.actor or current.get("owner") or author_login(issue),
        branch=opts.branch or current.get("branch"),
        status=opts.status or "claimed",
        validation=opts.validation or current.get("validation") or "pending",
        # Upstream read current.review first, which always defaults to "not-requested", so a
        # required review was never requested on claim. Request it unless one is already underway.
        review=opts.review or (current.get("review") if current.get("review") not in (None, "", "not-requested")
                               else ("requested" if policy["review"].get("required") else "not-requested")),
        projectState=opts.project_state or "in-progress",
    )
    tracked = plan_full_update(plan, issue, nxt, policy, "claim", "claimed")
    return summarize_state(repo, tracked, nxt, "claim", policy)


def action_sync(repo, opts, policy, plan):
    marker = policy.get("sectionMarker") or DEFAULT_SECTION_MARKER
    by_label = list_issues(repo, state="all", limit=opts.limit, label=(policy.get("labels") or {}).get("epic"))
    by_body = list_issues(repo, state="all", limit=opts.limit, search=f'in:body "{marker}:start"')
    seen = {}
    for i in by_label + by_body:
        seen[str(i.get("number"))] = i
    synced_at = now_iso()
    items = []
    for issue in seen.values():
        current = get_coordination_state(issue, policy)
        nxt = build_state_from_action(
            issue, current, "sync", policy,
            status=current.get("status"), validation=current.get("validation"), review=current.get("review"),
            projectState=_obj(current.get("project")).get("state") or "backlog",
        )
        desired = desired_labels_for_state(nxt, policy)
        current_labels = normalize_labels(issue.get("labels"))
        add = [x for x in desired if x not in current_labels]
        remove = [x for x in current_labels
                  if (x.startswith("coordination:") or x == (policy.get("labels") or {}).get("epic")) and x not in desired]
        plan.edit(issue["number"], add_labels=add, remove_labels=remove)
        nxt["labels"] = final_labels(issue, add, remove)
        body = merge_issue_body(issue, nxt, policy)
        # Upstream ignored only lastSyncAt here, so the fresh lastActionAt made every sync rewrite every body.
        if normalize_body_for_plan(body) != normalize_body_for_plan(issue.get("body")):
            plan.edit(issue["number"], body=body, summary=block_summary(nxt))
        tracked = dict(issue, labels=nxt["labels"])
        plan.upsert(tracked, nxt, "sync")
        item = summarize_state(repo, tracked, nxt, "sync", policy)
        item.update({"syncedAt": synced_at, "labelPlan": {"addLabels": add, "removeLabels": remove}})
        items.append(item)
    return {"repo": repo, "syncedAt": synced_at, "count": len(items), "items": items}


def action_validate(repo, number, opts, policy, plan, existing=None):
    issue = existing or get_issue(repo, number)
    state = get_coordination_state(issue, policy)
    deps = state["dependencies"] if isinstance(state.get("dependencies"), list) else []
    closed = verify_dependencies_closed(repo, deps, opts.limit)
    missing = [n for n in deps if n not in closed]
    validations = ([{"check": "dependencies", "ok": False, "detail": ",".join(str(n) for n in missing)}] if missing
                   else [{"check": "dependencies", "ok": True, "detail": "closed"}])
    ok = all(v["ok"] for v in validations)
    nxt = build_state_from_action(
        issue, state, "validate", policy,
        status="validated" if ok else state.get("status"),
        validation="passed" if ok else "failed",
        projectState="ready" if ok else (_obj(state.get("project")).get("state") or "backlog"),
    )
    if plan is not None:
        tracked = plan_full_update(plan, issue, nxt, policy, "validate")
    else:
        tracked = dict(issue, labels=desired_labels_for_state(nxt, policy))
    out = summarize_state(repo, tracked, nxt, "validate", policy)
    out.update({"ok": ok, "validations": validations, "missingDependencies": missing})
    return out


def action_publish(repo, number, opts, policy, plan):
    issue = get_issue(repo, number)
    state = get_coordination_state(issue, policy)
    validation = action_validate(repo, number, opts, policy, None, existing=issue)
    if not validation["ok"]:
        detail = ", ".join(f"{v['check']}={str(v['ok']).lower()}" for v in validation["validations"])
        raise CoordinationError(f"Issue #{number} is not ready to publish: {detail}. "
                                f"Close the open dependencies ({', '.join('#' + str(n) for n in validation['missingDependencies'])}) "
                                f"then run /epic-validate {number}.")
    if policy["review"].get("required") and state.get("review") != "approved":
        raise CoordinationError(f"Issue #{number} cannot be published: review approval required "
                                f"(current: {state.get('review')}). Run /epic-review {number} --review approved first.")
    nxt = build_state_from_action(
        issue, state, "publish", policy,
        status="published", validation="passed",
        review=state.get("review") if state.get("review") == "changes-requested" else "approved",
        projectState="done",
    )
    tracked = plan_full_update(plan, issue, nxt, policy, "publish", "published", {"validation": "passed"})
    return summarize_state(repo, tracked, nxt, "publish", policy)


def action_review(repo, number, opts, policy, plan):
    review = opts.review or "approved"
    if review not in REVIEW_STATES:
        raise CoordinationError(f"--review: '{review}' is not valid. Use one of: {', '.join(REVIEW_STATES)}.")
    issue = get_issue(repo, number)
    state = get_coordination_state(issue, policy)
    nxt = build_state_from_action(
        issue, state, "review", policy,
        status="ready" if review == "approved" else ("claimed" if review == "requested" else "blocked"),
        review=review,
        projectState="ready" if review == "approved" else "blocked",
    )
    tracked = plan_full_update(plan, issue, nxt, policy, "review", "reviewed", {"review": review})
    return summarize_state(repo, tracked, nxt, "review", policy)


def action_decompose(repo, number, opts, policy, plan):
    issue = get_issue(repo, number)
    state = get_coordination_state(issue, policy)
    tasks = extract_tasks(issue.get("body"))
    deps = extract_issue_references(issue.get("body"))
    open_tasks = any(not t["done"] for t in tasks)
    nxt = build_state_from_action(
        issue, state, "decompose", policy,
        tasks=tasks, dependencies=deps,
        status="claimed" if open_tasks else state.get("status"),
        projectState="in-progress" if open_tasks else (_obj(state.get("project")).get("state") or "backlog"),
    )
    tracked = plan_full_update(plan, issue, nxt, policy, "decompose", "decomposed",
                               {"taskCount": str(len(tasks)), "dependencyCount": str(len(deps))})
    out = summarize_state(repo, tracked, nxt, "decompose", policy)
    out.update({"tasks": tasks, "dependencyCount": len(deps)})
    return out


def action_unblock(repo, opts, policy, plan):
    issues = list_issues(repo, state="all", limit=opts.limit)
    items = []
    for issue in issues:
        state = get_coordination_state(issue, policy)
        if state.get("status") != "blocked":
            continue
        deps = state["dependencies"] if isinstance(state.get("dependencies"), list) else []
        closed = verify_dependencies_closed(repo, deps, opts.limit, issues)
        if deps and len(closed) != len(deps):
            continue
        nxt = build_state_from_action(
            issue, state, "unblock", policy,
            status="ready", projectState="ready",
            validation="pending" if state.get("validation") == "failed" else state.get("validation"),
        )
        tracked = plan_full_update(plan, issue, nxt, policy, "unblock", "unblocked",
                                   {"dependencies": ",".join(str(n) for n in deps) if deps else "none"})
        items.append(summarize_state(repo, tracked, nxt, "unblock", policy))
    return {"repo": repo, "count": len(items), "items": items}


# ---------------------------------------------------------------- store

def default_db_path(home=None):
    d = os.environ.get("NEVA_DATA_DIR")
    if d:
        return os.path.join(os.path.expanduser(d), "github-coordination.db")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(home or os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "neva", "github-coordination.db")


class Store:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS work_items (
      id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, title TEXT NOT NULL,
      status TEXT NOT NULL, priority TEXT, url TEXT, owner TEXT, repo_root TEXT, session_id TEXT,
      metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_work_items_status_updated_at ON work_items (status, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_work_items_source_source_id ON work_items (source, source_id);
    """

    def __init__(self, path):
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, mode=0o700, exist_ok=True)
            if os.path.islink(path):
                raise CoordinationError(f"--db: {path} is a symlink. Point --db at a regular file.")
        self.db = sqlite3.connect(path)
        self.db.executescript(self.SCHEMA)

    def upsert(self, repo, issue, state, action, policy, repo_root):
        ts = now_iso()
        meta = {
            "schemaVersion": state.get("schemaVersion") or DEFAULT_SCHEMA_VERSION,
            "repo": repo, "issueNumber": issue.get("number"), "issueUrl": issue.get("url") or None,
            "issueTitle": issue.get("title") or None, "labels": normalize_labels(issue.get("labels")),
            "coordination": state, "projectProjection": summarize_project(state, policy),
            "action": action, "actionAt": ts, "syncedBy": "neva-github-coordination",
        }
        row = {
            "id": epic_work_item_id(repo, issue.get("number")), "source": "github-epic",
            "source_id": str(issue.get("number")), "title": f"Epic #{issue.get('number')}: {issue.get('title')}",
            "status": map_state_to_work_item_status(state.get("status")),
            "priority": "high" if state.get("status") == "blocked" else "normal",
            "url": issue.get("url") or None, "owner": state.get("owner") or author_login(issue),
            "repo_root": repo_root, "session_id": None, "metadata": json.dumps(meta),
            "created_at": ts, "updated_at": ts,
        }
        self.db.execute(
            """INSERT INTO work_items (id, source, source_id, title, status, priority, url, owner, repo_root,
                 session_id, metadata, created_at, updated_at)
               VALUES (:id, :source, :source_id, :title, :status, :priority, :url, :owner, :repo_root,
                 :session_id, :metadata, :created_at, :updated_at)
               ON CONFLICT(id) DO UPDATE SET source=excluded.source, source_id=excluded.source_id,
                 title=excluded.title, status=excluded.status, priority=excluded.priority, url=excluded.url,
                 owner=excluded.owner, repo_root=excluded.repo_root, session_id=excluded.session_id,
                 metadata=excluded.metadata, updated_at=excluded.updated_at""", row)
        self.db.commit()
        return {"id": row["id"], "status": row["status"], "updatedAt": ts}

    def close(self):
        self.db.close()


# ---------------------------------------------------------------- output

def format_summary(p):
    lines = [
        f"{p.get('action') or 'sync'} epic #{p.get('issueNumber')}: {p.get('issueTitle')}",
        f"Repo: {p.get('repo')}",
        f"Status: {p.get('status')}",
        f"Owner: {p.get('owner') or '(unassigned)'}",
        f"Branch: {p.get('branch') or '(none)'}",
        f"Validation: {p.get('validation') or 'pending'}",
        f"Review: {p.get('review') or 'not-requested'}",
    ]
    if p.get("tasks"):
        lines.append(f"Tasks: {len(p['tasks'])}")
    if p.get("dependencies"):
        lines.append("Dependencies: " + ", ".join(str(n) for n in p["dependencies"]))
    return "\n".join(lines) + "\n"


def format_collection(p):
    lines = [f"Repo: {p.get('repo')}", f"Items: {p.get('count')}"]
    for item in p.get("items") or []:
        lines.append(f"- #{item.get('issueNumber')} {item.get('status')}: {item.get('issueTitle')}")
    return "\n".join(lines) + "\n"


def format_plan(plan, mode):
    n = len(plan.writes)
    head = {"dry-run": "Dry run", "pending": "Confirmation required", "applied": "Applied"}[mode]
    lines = [f"{head}: {n} GitHub write(s) to {plan.repo}, plan id {plan.plan_id()}"]
    for i, w in enumerate(plan.describe(), 1):
        if w["kind"] == "edit":
            parts = []
            if "body" in w:
                parts.append(w["body"])
            if w.get("addLabels"):
                parts.append("add labels " + ", ".join(w["addLabels"]))
            if w.get("removeLabels"):
                parts.append("remove labels " + ", ".join(w["removeLabels"]))
            lines.append(f"  {i}. edit #{w['issue']}: " + "; ".join(parts))
        else:
            lines.append(f"  {i}. comment on #{w['issue']}:")
            lines += ["       " + x for x in w["body"].split("\n")]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- cli

COMMANDS = ("claim", "sync", "validate", "publish", "review", "unblock", "decompose")
NEEDS_ISSUE = ("claim", "validate", "publish", "review", "decompose")


def build_parser():
    p = argparse.ArgumentParser(
        prog="github_coordination.py",
        description="GitHub-native epic coordination. Every GitHub write needs --yes or an interactive yes.",
    )
    p.add_argument("command", nargs="?", default="sync", choices=COMMANDS)
    p.add_argument("issue", nargs="?")
    p.add_argument("--repo", help="owner/repo")
    p.add_argument("--issue", dest="issue_flag")
    p.add_argument("--actor", help="claim owner (GitHub login)")
    p.add_argument("--branch")
    p.add_argument("--validation")
    p.add_argument("--review")
    p.add_argument("--status")
    p.add_argument("--project-state", dest="project_state")
    p.add_argument("--config", help="coordination policy JSON (default config/github-native-coordination.json)")
    p.add_argument("--db", help="SQLite cache path")
    p.add_argument("--no-db", action="store_true", help="skip the local cache")
    p.add_argument("--home", help="home directory for the default cache path")
    p.add_argument("--limit", default="100")
    p.add_argument("--dry-run", action="store_true", help="preview only, never writes")
    p.add_argument("--yes", action="store_true", help="apply the GitHub writes (human confirmed)")
    p.add_argument("--plan-id", dest="plan_id", help="with --yes: refuse if the plan changed")
    p.add_argument("--json", action="store_true")
    return p


def confirm_interactive(plan):
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return False
    sys.stderr.write(format_plan(plan, "pending"))
    sys.stderr.write(f"Apply these {len(plan.writes)} write(s) to {plan.repo}? Type yes to apply: ")
    sys.stderr.flush()
    try:
        answer = sys.stdin.readline().strip().lower()
    except (OSError, KeyboardInterrupt):
        return False
    return answer == "yes"


def run(argv=None):
    args = build_parser().parse_intermixed_args(argv)
    if not args.repo:
        raise CoordinationError("--repo: missing. Pass --repo owner/repo.")
    repo = normalize_repo(args.repo)
    raw_issue = args.issue_flag or args.issue
    number = normalize_issue_number(raw_issue, "issue number") if raw_issue else None
    if args.command in NEEDS_ISSUE and number is None:
        raise CoordinationError(f"{args.command}: missing issue number. Example: {args.command} 42 --repo owner/repo.")
    args.limit = normalize_issue_number(args.limit, "--limit")
    if args.plan_id and not args.yes:
        raise CoordinationError("--plan-id only applies with --yes. Add --yes after the human confirmed the plan.")
    if args.dry_run and args.yes:
        raise CoordinationError("--dry-run and --yes conflict. Drop one.")

    policy = load_policy(os.getcwd(), args.config)
    plan = Plan(repo)
    cmd = args.command
    if cmd == "claim":
        payload = action_claim(repo, number, args, policy, plan)
    elif cmd == "sync":
        payload = action_sync(repo, args, policy, plan)
    elif cmd == "validate":
        payload = action_validate(repo, number, args, policy, plan)
    elif cmd == "publish":
        payload = action_publish(repo, number, args, policy, plan)
    elif cmd == "review":
        payload = action_review(repo, number, args, policy, plan)
    elif cmd == "unblock":
        payload = action_unblock(repo, args, policy, plan)
    else:
        payload = action_decompose(repo, number, args, policy, plan)

    pid = plan.plan_id()
    if args.dry_run:
        mode = "dry-run"
    elif not plan.writes:
        mode = "applied"
    elif args.yes:
        if args.plan_id and args.plan_id != pid:
            payload["writes"] = {"mode": "plan-changed", "planId": pid, "expectedPlanId": args.plan_id,
                                 "planned": plan.describe(), "applied": 0}
            emit(payload, args, plan, None)
            sys.stderr.write(f"Plan changed since it was confirmed (expected {args.plan_id}, now {pid}). "
                             f"Nothing was written. Re-run without --yes, show the new plan, and ask again.\n")
            return EXIT_PLAN_CHANGED
        mode = "applied"
    elif confirm_interactive(plan):
        mode = "applied"
    else:
        mode = "pending"

    applied = 0
    snapshots = []
    if mode == "applied":
        applied = plan.apply()
        if not args.no_db and plan.store_ops:
            store = Store(args.db or default_db_path(args.home))
            try:
                for issue, state, action in plan.store_ops:
                    snapshots.append(store.upsert(repo, issue, state, action, policy, os.getcwd()))
            finally:
                store.close()
    payload["writes"] = {"mode": mode, "planId": pid, "planned": plan.describe(), "applied": applied}
    if snapshots:
        payload["snapshots"] = snapshots
    emit(payload, args, plan, mode)
    if mode == "pending":
        sys.stderr.write(f"Nothing was written. Show this plan to the human; only after an explicit yes re-run the "
                         f"same command with --yes --plan-id {pid}\n")
        return EXIT_CONFIRM
    return 0


def emit(payload, args, plan, mode):
    if args.json:
        sys.stdout.write(dumps(payload) + "\n")
        return
    if args.command in ("sync", "unblock"):
        sys.stdout.write(format_collection(payload))
    else:
        sys.stdout.write(format_summary(payload))
    if mode and plan.writes:
        sys.stdout.write("\n" + format_plan(plan, mode))
    elif mode:
        sys.stdout.write("\nNo GitHub writes needed.\n")


def main(argv=None):
    try:
        return run(argv)
    except CoordinationError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
