# Changelog

## 0.9.0 (2026-08-01) - first public release

Not 1.0, and the reason is specific: the macOS path is proven and the Linux path has never
been executed. Everything else is ready.

### Proven
- 38-check acceptance harness. It installs from scratch in a fresh HOME with a deliberately
  stripped PATH, then asserts outcomes a user would notice rather than exit codes. Every
  check has been proven able to fail by breaking the thing it watches.
- Covered: second installs over an existing one, non-ASCII notes and queries, vault paths
  containing spaces, grounded search with ripgrep absent, BSD and GNU divergence, the
  approval queue in both directions, and doctor's exit code against a broken install.

### Fixed before release, each found by someone pretending to be a buyer
- The leak scanner did not scan itself, so a real identifier could sit in `build/` forever.
  It also stored real secrets as literal strings, which is a disclosure the moment a repo is
  public. The denylist now lives outside the repository and the tool announces when it is
  inactive rather than printing "clean" while checking nothing.
- `doctor` could print a CRITICAL failure and return success.
- The installer enabled a background job on install day and the documented way to remove it
  did not work.
- The two documented fixes for the one failure every new install shows were both broken,
  which left a new user in a loop four steps into the README.
- The installer could write into an existing agent workspace without consent.
- A notification tool logged "sent" without checking whether the send succeeded.
- Money was described as coming only from the ledger while the code also read a cached block
  that nothing ever wrote.
- A feature was documented as shipped that no code implemented.

### Known and stated rather than hidden
- Linux: never run end to end. The systemd units have never been loaded.
- Spoken voice does not exist. The word "voice" in these docs means writing style.
- The setup interview has been run by two independent testers and by nobody else.
