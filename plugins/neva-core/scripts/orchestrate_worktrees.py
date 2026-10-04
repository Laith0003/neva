#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Fan one plan out to parallel workers: one git worktree, one branch and one tmux pane each.
Python 3 standard library plus git and tmux.

Usage:
  python3 orchestrate_worktrees.py <plan.json>                 dry run: print the plan as JSON
  python3 orchestrate_worktrees.py <plan.json> --write-only    write task/handoff/status files only
  python3 orchestrate_worktrees.py <plan.json> --execute       create worktrees, launch tmux panes
  python3 orchestrate_worktrees.py <plan.json> --execute --replace-existing
                                                               also tear down a previous run first

Plan JSON:
  {
    "sessionName": "auth-refactor",          optional, default the repo folder name
    "repoRoot": ".",                          optional, default the current directory
    "baseRef": "HEAD",                        optional
    "worktreeRoot": "..",                     optional, default the repo's parent folder
    "coordinationRoot": ".orchestration",     optional
    "launcherCommand": "claude -p \\"$(cat {task_file_sh})\\" > {handoff_file_sh}",
    "seedPaths": ["local/untracked.env"],     optional, copied into every worktree
    "replaceExisting": false,                 needs --replace-existing on the command line too
    "workers": [{"name": "api", "task": "...", "launcherCommand": "...", "seedPaths": []}]
  }

Placeholders in launcherCommand (each also as <name>_raw and shell-quoted <name>_sh):
  {worker_name} {worker_slug} {session_name} {repo_root}
  {worktree_path} {branch_name} {task_file} {handoff_file} {status_file}

Without flags the script prints a dry-run plan only. Any failure during --execute rolls back
what this run created (tmux session, worktrees, branches, fresh coordination folder).
"""
import json
import os
import re
import shutil
import subprocess
import sys


class OrchestrationError(Exception):
    pass


def slugify(value, fallback="worker"):
    s = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return s or fallback


def shell_quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


def format_command(program, args):
    return " ".join([program] + [shell_quote(a) for a in args])


def render_template(template, variables):
    if not isinstance(template, str) or not template.strip():
        raise OrchestrationError("launcherCommand must be a non-empty string")

    def sub(m):
        key = m.group(1)
        if key not in variables:
            raise OrchestrationError(f"Unknown template variable: {key}. Valid: {', '.join(sorted(variables))}")
        return str(variables[key])

    return re.sub(r"\{([a-z_]+)\}", sub, template)


def build_template_variables(values):
    out = {}
    for key, value in values.items():
        s = str(value)
        out[key] = s
        out[f"{key}_raw"] = s
        out[f"{key}_sh"] = shell_quote(s)
    return out


def session_banner_command(session_name, coordination_dir):
    return (f"printf '%s\\n' {shell_quote('Session: ' + session_name)} "
            f"{shell_quote('Coordination: ' + coordination_dir)}")


def normalize_seed_paths(seed_paths, repo_root):
    root = os.path.abspath(repo_root)
    seen, out = set(), []
    for entry in seed_paths if isinstance(seed_paths, list) else []:
        if not isinstance(entry, str) or not entry.strip():
            continue
        absolute = os.path.abspath(os.path.join(root, entry))
        rel = os.path.relpath(absolute, root)
        if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
            raise OrchestrationError(f"seedPaths entries must stay inside repoRoot: {entry}")
        norm = rel.replace(os.sep, "/")
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def overlay_seed_paths(repo_root, seed_paths, worktree_path):
    for seed in normalize_seed_paths(seed_paths, repo_root):
        src = os.path.join(repo_root, seed)
        dst = os.path.join(worktree_path, seed)
        if not os.path.lexists(src):
            raise OrchestrationError(f"Seed path does not exist in repoRoot: {seed}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.islink(dst) or os.path.isfile(dst):
            os.remove(dst)
        elif os.path.isdir(dst):
            shutil.rmtree(dst)
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)


def worker_artifacts(w):
    seeded = (["", "## Seeded Local Overlays"] + [f"- `{p}`" for p in w["seedPaths"]]) if w["seedPaths"] else []
    task = "\n".join([
        f"# Worker Task: {w['workerName']}",
        "",
        f"- Session: `{w['sessionName']}`",
        f"- Repo root: `{w['repoRoot']}`",
        f"- Worktree: `{w['worktreePath']}`",
        f"- Branch: `{w['branchName']}`",
        f"- Launcher status file: `{w['statusFilePath']}`",
        f"- Launcher handoff file: `{w['handoffFilePath']}`",
        *seeded,
        "",
        "## Objective",
        w["task"],
        "",
        "## Completion",
        "Do not spawn subagents or external agents for this task.",
        "Report results in your final response.",
        f"The worker launcher captures your response in `{w['handoffFilePath']}` automatically.",
        f"The worker launcher updates `{w['statusFilePath']}` automatically.",
    ])
    handoff = "\n".join([
        f"# Handoff: {w['workerName']}", "", "## Summary", "- Pending", "", "## Files Changed", "- Pending",
        "", "## Tests / Verification", "- Pending", "", "## Follow-ups", "- Pending",
    ])
    status = "\n".join([
        f"# Status: {w['workerName']}", "", "- State: not started",
        f"- Worktree: `{w['worktreePath']}`", f"- Branch: `{w['branchName']}`",
    ])
    return {"dir": w["coordinationDir"], "files": [
        {"path": w["taskFilePath"], "content": task},
        {"path": w["handoffFilePath"], "content": handoff},
        {"path": w["statusFilePath"], "content": status},
    ]}


def build_orchestration_plan(config=None):
    config = config or {}
    repo_root = os.path.abspath(config.get("repoRoot") or os.getcwd())
    repo_name = os.path.basename(repo_root)
    workers = config.get("workers") if isinstance(config.get("workers"), list) else []
    global_seeds = normalize_seed_paths(config.get("seedPaths"), repo_root)
    session_name = slugify(config.get("sessionName") or repo_name, "session")
    worktree_root = os.path.abspath(config.get("worktreeRoot") or os.path.dirname(repo_root))
    coordination_root = os.path.abspath(config.get("coordinationRoot") or os.path.join(repo_root, ".orchestration"))
    coordination_dir = os.path.join(coordination_root, session_name)
    base_ref = config.get("baseRef") or "HEAD"
    default_launcher = config.get("launcherCommand") or ""

    if not workers:
        raise OrchestrationError("workers: the plan needs at least one worker with a task")

    seen, plans = set(), []
    for index, worker in enumerate(workers):
        if not isinstance(worker, dict) or not isinstance(worker.get("task"), str) or not worker["task"].strip():
            raise OrchestrationError(f"workers[{index}].task: missing. Worker {index + 1} needs a non-empty task")
        name = worker.get("name") or f"worker-{index + 1}"
        slug = slugify(name, f"worker-{index + 1}")
        if slug in seen:
            raise OrchestrationError(f"Workers must have unique slugs. Duplicate: {slug}")
        seen.add(slug)
        branch = f"orchestrator-{session_name}-{slug}"
        worktree = os.path.join(worktree_root, f"{repo_name}-{session_name}-{slug}")
        wdir = os.path.join(coordination_dir, slug)
        task_file = os.path.join(wdir, "task.md")
        handoff_file = os.path.join(wdir, "handoff.md")
        status_file = os.path.join(wdir, "status.md")
        launcher = worker.get("launcherCommand") or default_launcher
        seeds = normalize_seed_paths(global_seeds + normalize_seed_paths(worker.get("seedPaths"), repo_root), repo_root)
        variables = build_template_variables({
            "branch_name": branch, "handoff_file": handoff_file, "repo_root": repo_root,
            "session_name": session_name, "status_file": status_file, "task_file": task_file,
            "worker_name": name, "worker_slug": slug, "worktree_path": worktree,
        })
        if not launcher:
            raise OrchestrationError(f"Worker {name} is missing a launcherCommand. Set it on the worker or at the top level")
        git_args = ["worktree", "add", "-b", branch, worktree, base_ref]
        plans.append({
            "branchName": branch, "coordinationDir": wdir, "gitArgs": git_args,
            "gitCommand": format_command("git", git_args), "handoffFilePath": handoff_file,
            "launchCommand": render_template(launcher, variables), "repoRoot": repo_root,
            "sessionName": session_name, "seedPaths": seeds, "statusFilePath": status_file,
            "task": worker["task"].strip(), "taskFilePath": task_file, "workerName": name,
            "workerSlug": slug, "worktreePath": worktree,
        })

    tmux = [
        {"cmd": "tmux", "args": ["new-session", "-d", "-s", session_name, "-n", "orchestrator", "-c", repo_root],
         "description": "Create detached tmux session"},
        {"cmd": "tmux", "args": ["send-keys", "-t", session_name, session_banner_command(session_name, coordination_dir), "C-m"],
         "description": "Print orchestrator session details"},
    ]
    for w in plans:
        tmux += [
            {"cmd": "tmux", "args": ["split-window", "-d", "-t", session_name, "-c", w["worktreePath"]],
             "description": f"Create pane for {w['workerName']}"},
            {"cmd": "tmux", "args": ["select-layout", "-t", session_name, "tiled"],
             "description": "Arrange panes in tiled layout"},
            {"cmd": "tmux", "args": ["select-pane", "-t", "<pane-id>", "-T", w["workerSlug"]],
             "description": f"Label pane {w['workerSlug']}"},
            {"cmd": "tmux", "args": ["send-keys", "-t", "<pane-id>",
                                     f"cd {shell_quote(w['worktreePath'])} && {w['launchCommand']}", "C-m"],
             "description": f"Launch worker {w['workerName']}"},
        ]
    return {"baseRef": base_ref, "coordinationDir": coordination_dir,
            "replaceExisting": bool(config.get("replaceExisting")), "repoRoot": repo_root,
            "sessionName": session_name, "tmuxCommands": tmux, "workerPlans": plans}


def materialize_plan(plan):
    for w in plan["workerPlans"]:
        a = worker_artifacts(w)
        os.makedirs(a["dir"], exist_ok=True)
        for f in a["files"]:
            with open(f["path"], "w", encoding="utf-8") as fh:
                fh.write(f["content"] + "\n")


# ---------------------------------------------------------------- process helpers

def run_command(program, args, cwd=None):
    try:
        r = subprocess.run([program] + list(args), cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        hint = "Install tmux (brew install tmux, apt install tmux)." if program == "tmux" else f"Install {program}."
        raise OrchestrationError(f"{program} not found on PATH. {hint}")
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        raise OrchestrationError(f"{program} {' '.join(args)} failed" + (f": {err}" if err else ""))
    return r


def command_succeeds(program, args, cwd=None):
    try:
        return subprocess.run([program] + list(args), cwd=cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return False


def canonicalize(p):
    p = os.path.abspath(p)
    if os.path.exists(p):
        return os.path.realpath(p)
    parent = os.path.dirname(p)
    if os.path.exists(parent):
        return os.path.join(os.path.realpath(parent), os.path.basename(p))
    return p


def branch_exists(repo_root, branch):
    return command_succeeds("git", ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_root)


def list_worktrees(repo_root):
    out = run_command("git", ["worktree", "list", "--porcelain"], cwd=repo_root).stdout or ""
    rows = []
    for line in out.split("\n"):
        if line.startswith("worktree "):
            listed = line[len("worktree "):].strip()
            rows.append({"listedPath": listed, "canonicalPath": canonicalize(listed)})
    return rows


def cleanup_existing(plan, rt):
    rt["run"]("git", ["worktree", "prune", "--expire", "now"], cwd=plan["repoRoot"])
    if rt["succeeds"]("tmux", ["has-session", "-t", plan["sessionName"]]):
        rt["run"]("tmux", ["kill-session", "-t", plan["sessionName"]], cwd=plan["repoRoot"])
    for w in plan["workerPlans"]:
        expected = canonicalize(w["worktreePath"])
        hit = next((x for x in rt["list_worktrees"](plan["repoRoot"]) if x["canonicalPath"] == expected), None)
        if hit:
            rt["run"]("git", ["worktree", "remove", "--force", hit["listedPath"]], cwd=plan["repoRoot"])
        if os.path.exists(w["worktreePath"]):
            shutil.rmtree(w["worktreePath"], ignore_errors=True)
        rt["run"]("git", ["worktree", "prune", "--expire", "now"], cwd=plan["repoRoot"])
        if rt["branch_exists"](plan["repoRoot"], w["branchName"]):
            rt["run"]("git", ["branch", "-D", w["branchName"]], cwd=plan["repoRoot"])


def rollback_created(plan, created, rt):
    errors = []
    if created["sessionCreated"]:
        try:
            rt["run"]("tmux", ["kill-session", "-t", plan["sessionName"]], cwd=plan["repoRoot"])
        except OrchestrationError as e:
            errors.append(str(e))
    for w in reversed(created["workerPlans"]):
        expected = canonicalize(w["worktreePath"])
        try:
            hit = next((x for x in rt["list_worktrees"](plan["repoRoot"]) if x["canonicalPath"] == expected), None)
        except OrchestrationError as e:
            errors.append(str(e))
            hit = None
        if hit:
            try:
                rt["run"]("git", ["worktree", "remove", "--force", hit["listedPath"]], cwd=plan["repoRoot"])
            except OrchestrationError as e:
                errors.append(str(e))
        elif os.path.exists(w["worktreePath"]):
            shutil.rmtree(w["worktreePath"], ignore_errors=True)
        try:
            rt["run"]("git", ["worktree", "prune", "--expire", "now"], cwd=plan["repoRoot"])
        except OrchestrationError as e:
            errors.append(str(e))
        if rt["branch_exists"](plan["repoRoot"], w["branchName"]):
            try:
                rt["run"]("git", ["branch", "-D", w["branchName"]], cwd=plan["repoRoot"])
            except OrchestrationError as e:
                errors.append(str(e))
    if created["removeCoordinationDir"] and os.path.exists(plan["coordinationDir"]):
        shutil.rmtree(plan["coordinationDir"], ignore_errors=True)
    if errors:
        raise OrchestrationError("rollback failed: " + "; ".join(errors))


def default_runtime():
    return {"run": run_command, "succeeds": command_succeeds, "list_worktrees": list_worktrees,
            "branch_exists": branch_exists, "materialize": materialize_plan, "overlay": overlay_seed_paths}


def execute_plan(plan, runtime=None, allow_replace=False):
    rt = default_runtime()
    rt.update(runtime or {})
    created = {"workerPlans": [], "sessionCreated": False,
               "removeCoordinationDir": not os.path.exists(plan["coordinationDir"])}
    rt["run"]("git", ["rev-parse", "--is-inside-work-tree"], cwd=plan["repoRoot"])
    rt["run"]("tmux", ["-V"])

    if plan["replaceExisting"]:
        if not allow_replace:
            raise OrchestrationError(
                "replaceExisting: the plan asks to force-remove existing worktrees and delete branches "
                f"orchestrator-{plan['sessionName']}-*. Uncommitted work in them is lost. Add --replace-existing "
                "to confirm, or set replaceExisting to false.")
        cleanup_existing(plan, rt)
    elif rt["succeeds"]("tmux", ["has-session", "-t", plan["sessionName"]]):
        raise OrchestrationError(f"tmux session already exists: {plan['sessionName']}. Attach with "
                                 f"`tmux attach -t {plan['sessionName']}` or pick another sessionName")

    try:
        rt["materialize"](plan)
        for w in plan["workerPlans"]:
            rt["run"]("git", w["gitArgs"], cwd=plan["repoRoot"])
            created["workerPlans"].append(w)
            rt["overlay"](plan["repoRoot"], w["seedPaths"], w["worktreePath"])
        rt["run"]("tmux", ["new-session", "-d", "-s", plan["sessionName"], "-n", "orchestrator", "-c", plan["repoRoot"]],
                  cwd=plan["repoRoot"])
        created["sessionCreated"] = True
        rt["run"]("tmux", ["send-keys", "-t", plan["sessionName"],
                           session_banner_command(plan["sessionName"], plan["coordinationDir"]), "C-m"],
                  cwd=plan["repoRoot"])
        for w in plan["workerPlans"]:
            r = rt["run"]("tmux", ["split-window", "-d", "-P", "-F", "#{pane_id}", "-t", plan["sessionName"],
                                   "-c", w["worktreePath"]], cwd=plan["repoRoot"])
            pane = (r.stdout or "").strip()
            if not pane:
                raise OrchestrationError(f"tmux split-window did not return a pane id for {w['workerName']}")
            rt["run"]("tmux", ["select-layout", "-t", plan["sessionName"], "tiled"], cwd=plan["repoRoot"])
            rt["run"]("tmux", ["select-pane", "-t", pane, "-T", w["workerSlug"]], cwd=plan["repoRoot"])
            rt["run"]("tmux", ["send-keys", "-t", pane, f"cd {shell_quote(w['worktreePath'])} && {w['launchCommand']}",
                               "C-m"], cwd=plan["repoRoot"])
    except (OrchestrationError, OSError) as error:
        msg = str(error)
        try:
            rollback_created(plan, created, rt)
        except OrchestrationError as ce:
            msg = f"{msg}; cleanup failed: {ce}"
        raise OrchestrationError(msg)

    return {"coordinationDir": plan["coordinationDir"], "sessionName": plan["sessionName"],
            "workerCount": len(plan["workerPlans"])}


# ---------------------------------------------------------------- cli

def usage():
    return "\n".join([
        "Usage:",
        "  python3 orchestrate_worktrees.py <plan.json> [--execute] [--replace-existing]",
        "  python3 orchestrate_worktrees.py <plan.json> [--write-only]",
        "",
        "Placeholders supported in launcherCommand:",
        "  {worker_name} {worker_slug} {session_name} {repo_root}",
        "  {worktree_path} {branch_name} {task_file} {handoff_file} {status_file}",
        "  (append _sh for a shell-quoted value)",
        "",
        "Without flags the script prints a dry-run plan only.",
    ])


def load_plan_config(plan_path):
    absolute = os.path.abspath(plan_path)
    try:
        with open(absolute, encoding="utf-8") as fh:
            config = json.load(fh)
    except FileNotFoundError:
        raise OrchestrationError(f"plan file not found: {absolute}. Write the plan JSON there first")
    except ValueError as e:
        raise OrchestrationError(f"plan file {absolute} is not valid JSON: {e}")
    if not isinstance(config, dict):
        raise OrchestrationError(f"plan file {absolute} must contain a JSON object")
    config["repoRoot"] = config.get("repoRoot") or os.getcwd()
    return absolute, config


def dry_run_preview(plan, absolute):
    return {
        "planFile": absolute,
        "sessionName": plan["sessionName"],
        "repoRoot": plan["repoRoot"],
        "coordinationDir": plan["coordinationDir"],
        "workers": [{k: w[k] for k in ("workerName", "branchName", "worktreePath", "seedPaths", "taskFilePath",
                                       "handoffFilePath", "launchCommand")} for w in plan["workerPlans"]],
        "commands": [w["gitCommand"] for w in plan["workerPlans"]]
                    + [" ".join([c["cmd"]] + c["args"]) for c in plan["tmuxCommands"]],
    }


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if "--help" in args or "-h" in args:
        print(usage())
        return 0
    known = {"--execute", "--write-only", "--replace-existing"}
    unknown = [a for a in args if a.startswith("--") and a not in known]
    plan_path = next((a for a in args if not a.startswith("--")), None)
    try:
        if unknown:
            raise OrchestrationError(f"Unknown option: {unknown[0]}. Valid: --execute, --write-only, --replace-existing")
        if not plan_path:
            print(usage())
            return 1
        if "--execute" in args and "--write-only" in args:
            raise OrchestrationError("--execute and --write-only conflict. Pick one")
        absolute, config = load_plan_config(plan_path)
        plan = build_orchestration_plan(config)
        if "--write-only" in args:
            materialize_plan(plan)
            print(f"Wrote orchestration files to {plan['coordinationDir']}")
            return 0
        if "--execute" not in args:
            print(json.dumps(dry_run_preview(plan, absolute), indent=2, ensure_ascii=False))
            return 0
        result = execute_plan(plan, allow_replace="--replace-existing" in args)
        print("\n".join([
            f"Started tmux session '{result['sessionName']}' with {result['workerCount']} worker panes.",
            f"Coordination files: {result['coordinationDir']}",
            f"Attach with: tmux attach -t {result['sessionName']}",
        ]))
        return 0
    except OrchestrationError as e:
        sys.stderr.write(f"[orchestrate-worktrees] {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
