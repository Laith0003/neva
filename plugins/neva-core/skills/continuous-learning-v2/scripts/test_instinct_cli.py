"""Tests for the Neva instinct CLI and the proposal contract.

Run either way; build/verify.sh uses the first, which needs only the standard library:
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s <this folder> -p test_instinct_cli.py
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider scripts/test_instinct_cli.py
Every test runs in a throwaway HOME, vault and XDG tree; nothing touches the real machine.
"""

import inspect
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

try:
    import pytest
except ImportError:  # stdlib-only machines run the same tests through StdlibCase below
    pytest = None

CLI = Path(__file__).resolve().parent / "instinct-cli.py"


def _make_sandbox(tmp_path):
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    (vault / "00 Inbox").mkdir(parents=True)
    home.mkdir()
    # Host NEVA_*, CLAUDE_*, ANTHROPIC_* and XDG_* vars never reach the CLI: a developer's own
    # NEVA_INBOX would otherwise move the proposal file and fail every proposal test.
    base = {k: v for k, v in os.environ.items() if not k.startswith(("NEVA_", "CLAUDE_", "ANTHROPIC_", "XDG_"))}
    env = dict(base, HOME=str(home), NEVA_VAULT=str(vault),
               XDG_DATA_HOME=str(tmp_path / "data"), XDG_STATE_HOME=str(tmp_path / "state"))
    repos = {}
    for name in ("repoA", "repoB"):
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", f"https://github.com/example/{name}.git"], cwd=repo, check=True)
        repos[name] = repo

    def run(*args, cwd="repoA", check=True):
        result = subprocess.run([sys.executable, str(CLI), *args], cwd=repos.get(cwd, cwd), env=env,
                                capture_output=True, text=True)
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    return {"run": run, "vault": vault, "home": home, "repos": repos, "env": env}


if pytest is not None:
    @pytest.fixture()
    def sandbox(tmp_path):
        return _make_sandbox(tmp_path)


def _add(run, cwd, iid, conf, domain="code-style", trigger="when handling errors in services"):
    # The action names a behaviour and comes from the id, as the unittest sandbox does: the quality
    # gate parks a candidate that restates another one, and "Do the thing." restated every other.
    action = f"Apply the {iid.replace('-', ' ')} practice in every change."
    run("add", "--id", iid, "--trigger", trigger, "--action", action, "--domain", domain,
        "--confidence", str(conf), cwd=cwd)


def _proposal(vault):
    return vault / "00 Inbox" / f"Instinct promotions {date.today().isoformat()}.md"


def _tick(path, block_id, box):
    text = path.read_text()
    start = text.index(f"block_id: {block_id}")
    idx = text.index(f"- [ ] {box}", start)
    path.write_text(text[:idx] + f"- [x] {box}" + text[idx + len(f"- [ ] {box}"):])


def test_missing_vault_names_the_fix(sandbox):
    env = dict(sandbox["env"])
    env.pop("NEVA_VAULT")
    result = subprocess.run([sys.executable, str(CLI), "status"], env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert "export NEVA_VAULT=" in result.stderr


def test_add_writes_one_markdown_note_per_instinct(sandbox):
    _add(sandbox["run"], "repoA", "prefer-explicit-errors", 9)
    notes = list((sandbox["vault"] / "06 Memory" / "instincts" / "project").glob("*/prefer-explicit-errors.md"))
    assert len(notes) == 1
    text = notes[0].read_text()
    assert "confidence: 0.9" in text and "status: active" in text and "tags: [instinct, code-style]" in text


def test_nothing_is_promoted_until_ticked(sandbox):
    run = sandbox["run"]
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    proposal = _proposal(sandbox["vault"])
    assert "block_id: promote-global:prefer-explicit-errors" in proposal.read_text()
    global_note = sandbox["vault"] / "06 Memory" / "instincts" / "global" / "prefer-explicit-errors.md"
    run("apply-promotions")
    assert not global_note.exists()
    _tick(proposal, "promote-global:prefer-explicit-errors", "approve")
    run("apply-promotions")
    assert global_note.exists()
    sources = list((sandbox["vault"] / "06 Memory" / "instincts" / "project").glob("*/prefer-explicit-errors.md"))
    assert all("status: promoted" in s.read_text() for s in sources)
    assert "Applied " in proposal.read_text()


def test_rejected_block_is_never_reproposed(sandbox):
    run = sandbox["run"]
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    proposal = _proposal(sandbox["vault"])
    _tick(proposal, "promote-global:prefer-explicit-errors", "reject")
    run("apply-promotions")
    assert "Rejected " in proposal.read_text()
    out = run("propose").stdout
    assert "No new instinct candidates" in out


def test_both_boxes_ticked_is_a_named_error(sandbox):
    run = sandbox["run"]
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    proposal = _proposal(sandbox["vault"])
    _tick(proposal, "promote-global:prefer-explicit-errors", "approve")
    _tick(proposal, "promote-global:prefer-explicit-errors", "reject")
    result = run("apply-promotions", check=False)
    assert result.returncode == 1
    assert "both approve and reject are ticked. Fix: untick one." in result.stderr


def test_apply_all_is_the_spoken_approval(sandbox):
    run = sandbox["run"]
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    run("apply-promotions", "--all")
    assert re.search(r"^status: done$", _proposal(sandbox["vault"]).read_text(), re.M)


def test_destination_outside_allowed_roots_is_refused(sandbox):
    run = sandbox["run"]
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    proposal = _proposal(sandbox["vault"])
    text = proposal.read_text()
    text = re.sub(r"(\| Proposed destination \| )`[^`]+`", r"\1`/tmp/elsewhere/x.md`", text, count=1)
    proposal.write_text(text)
    result = run("apply-promotions", "--all", check=False)
    assert "is outside the vault" in result.stderr
    assert not Path("/tmp/elsewhere/x.md").exists()


def test_decay_is_idempotent_and_feeds_retirement(sandbox):
    run = sandbox["run"]
    _add(run, "repoA", "old-habit", 0.31)
    note = next((sandbox["vault"] / "06 Memory" / "instincts" / "project").glob("*/old-habit.md"))
    ten_weeks = (date.today() - timedelta(days=70)).isoformat()
    note.write_text(re.sub(r"^last_observed: .*$", f"last_observed: {ten_weeks}", note.read_text(), flags=re.M))
    run("decay")
    run("decay")
    assert "confidence: 0.11" in note.read_text()
    run("propose")
    assert "retire:" in _proposal(sandbox["vault"]).read_text()
    run("apply-promotions", "--all")
    assert "status: archived" in note.read_text()


def test_proposals_get_a_pointer_in_the_template_inbox(sandbox):
    run = sandbox["run"]
    inbox = sandbox["vault"] / "00 Inbox" / "inbox.md"
    inbox.write_text("# Inbox\n\n## Open actions\n- [ ] call the bank\n\n## Someday\n- cello\n")
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    link = f"[[Instinct promotions {date.today().isoformat()}]]"
    text = inbox.read_text()
    section = text.split("## Open actions", 1)[1].split("## Someday", 1)[0]
    assert f"- [ ] Review instinct proposals: {link}" in section
    run("propose")
    assert inbox.read_text().count(link) == 1, "a second propose run must not duplicate the pointer"
    run("apply-promotions", "--all")
    assert f"- [x] Review instinct proposals: {link}" in inbox.read_text()


def test_root_inbox_via_neva_inbox(sandbox):
    run = sandbox["run"]
    root_inbox = sandbox["vault"] / "inbox.md"
    root_inbox.write_text("# Inbox\n\n## Open actions\n- [ ] existing\n")
    sandbox["env"]["NEVA_INBOX"] = "inbox.md"
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    proposal = sandbox["vault"] / "06 Memory" / "instincts" / "proposals" / f"Instinct promotions {date.today().isoformat()}.md"
    assert proposal.exists(), "a root inbox files proposals under 06 Memory/instincts/proposals"
    assert not _proposal(sandbox["vault"]).exists()
    assert "Review instinct proposals" in root_inbox.read_text()
    assert "Open instinct proposals: 1" in run("status").stdout


def test_proposals_dir_override(sandbox):
    run = sandbox["run"]
    sandbox["env"]["NEVA_PROPOSALS_DIR"] = "09 Reviews"
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    assert (sandbox["vault"] / "09 Reviews" / f"Instinct promotions {date.today().isoformat()}.md").exists()


def test_vault_from_identity_file(sandbox):
    env = dict(sandbox["env"])
    env.pop("NEVA_VAULT")
    cfg = sandbox["home"] / "identity.env"
    cfg.write_text(f'OWNER_NAME="x"\nVAULT_PATH="{sandbox["vault"]}"\n')
    env["NEVA_CONFIG"] = str(cfg)
    result = subprocess.run([sys.executable, str(CLI), "status"], cwd=sandbox["repos"]["repoA"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_observations_and_state_follow_neva_dirs(sandbox, tmp_path):
    env = dict(sandbox["env"], NEVA_DATA_DIR=str(tmp_path / "d"), NEVA_STATE_DIR=str(tmp_path / "s"))
    obs = tmp_path / "d" / "observations"
    result = subprocess.run([sys.executable, str(CLI), "stats"], cwd=sandbox["repos"]["repoA"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (obs / "projects.json").exists(), "the registry lives next to the hook's observations"


def test_stats_reports_the_promotion_approve_reject_rate(sandbox):
    run = sandbox["run"]
    _add(run, "repoA", "prefer-explicit-errors", 0.9)
    _add(run, "repoB", "prefer-explicit-errors", 0.85)
    run("propose")
    _tick(_proposal(sandbox["vault"]), "promote-global:prefer-explicit-errors", "approve")
    run("apply-promotions")

    _add(run, "repoA", "avoid-mocks", 0.9, trigger="when writing tests for a service layer")
    _add(run, "repoB", "avoid-mocks", 0.85, trigger="when writing tests for a service layer")
    run("propose")
    _tick(_proposal(sandbox["vault"]), "promote-global:avoid-mocks", "reject")
    run("apply-promotions")

    out = run("stats").stdout
    assert "PROMOTIONS_APPLIED: 1" in out
    assert "PROMOTIONS_REJECTED: 1" in out
    assert "PROMOTIONS_APPROVE_RATE: 0.50" in out


def test_stats_reports_no_rate_before_any_decision(sandbox):
    out = sandbox["run"]("stats").stdout
    assert "PROMOTIONS_APPLIED: 0" in out
    assert "PROMOTIONS_REJECTED: 0" in out
    assert "PROMOTIONS_APPROVE_RATE: n/a" in out


class StdlibCase(unittest.TestCase):
    """Runs every test_ function above under unittest, with the same throwaway sandbox, so the suite
    needs no third-party package and build/verify.sh can discover it."""
    __test__ = pytest is None  # under pytest the functions run directly; do not run them twice


def _bind(fn):
    params = inspect.signature(fn).parameters

    def method(self):
        tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="neva-instinct-cli-")))
        self.addCleanup(shutil.rmtree, tmp, True)
        kwargs = {}
        if "sandbox" in params:
            kwargs["sandbox"] = _make_sandbox(tmp / "sandbox")
        if "tmp_path" in params:
            (tmp / "extra").mkdir()
            kwargs["tmp_path"] = tmp / "extra"
        fn(**kwargs)
    method.__name__ = fn.__name__
    return method


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(StdlibCase, _name, _bind(_fn))
