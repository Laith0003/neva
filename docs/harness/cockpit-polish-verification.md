# Cockpit polish verification

The recovered brief covers context accuracy, readable local timestamps, started-time
fallback, currency formatting, risk summaries and a single self-contained styled page.
Implementation is recorded in commits c3a8cc9 through 1ad5f9a on feat/cockpit-polish.
No additional implementation change was needed during this resumption.

Verification on 2026-10-15:

| Check | Result |
|---|---|
| Full cockpit suite | 137 tests run; 7 errors, all loopback socket binds denied by the sandbox |
| Formatting, ingestion and installed entry-point suites | 86 tests passed, exit 0 |
| Installed layout | Covered by test_installed, using an isolated prefix |
| Diff whitespace check | Passed |
| Release gate | NOT RELEASABLE; full verification remains blocked |

Commands:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s lib/neva_cockpit/tests -t lib
TMPDIR="$PWD/.cockpit-verification" PYTHONPATH=lib PYTHONDONTWRITEBYTECODE=1 python3 -m unittest neva_cockpit.tests.test_format neva_cockpit.tests.test_ingest neva_cockpit.tests.test_installed
git diff --check
python3 build/leak-scan.py .
```

The focused invocation initially lacked PYTHONPATH and failed to import the package;
the corrected invocation above passed. Its temporary root was inside the repository.

The original brief prohibits app UIs, browsers, pushes and writes outside the repository.
No browser or app UI was opened, and no push was attempted. Live visual verification
remains unperformed. The existing build/verify.sh hardcodes external temporary paths,
so it was inspected but not rerun after recovering that restriction. Its previous
release result cannot substitute for a successful current gate. A permitted environment
with loopback sockets and an authorized temporary directory is still required.

Resumption verification on 2026-10-15 repeated the full suite with TMPDIR confined
to the repository. All implementation requests in the recovered supervisor brief
are already present in commit 1ad5f9a; no further source change was identified.

| Check | Current result |
|---|---|
| Full cockpit suite | 137 tests, 130 passed, 7 socket-binding errors; exit 1 |
| Installed entry point | Passed as part of the full suite |
| Release status | NOT RELEASABLE |

The blocked tests are BindRestrictionTests.test_binding_127_0_0_1_is_accepted
and these TokenAuthTests: test_correct_token_but_unknown_subpath_gets_404,
test_html_page_served_at_token_root, test_page_renders_health_and_hook_errors_escaped,
test_request_with_correct_token_returns_the_snapshot,
test_request_with_wrong_token_gets_404_and_no_data, and
test_request_without_token_gets_404_and_no_data. Each raises PermissionError
at socket.bind before the HTTP assertion can run.

The temporary test directory was removed after checking its tree for symlinks.
The initial leak scan caught generated runtime caches inside that directory;
those caches are not source artifacts. The source scan was rerun after cleanup.
The requested verify.sh retry remains blocked by its hardcoded external temporary
writes, including mktemp templates and marker paths under /tmp. Setting HOME
alone does not confine these writes. No browser was opened.
