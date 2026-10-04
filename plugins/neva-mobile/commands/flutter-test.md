---
description: Run Flutter/Dart tests, report failures, and incrementally fix test issues. Covers unit, widget, golden, and integration tests.
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Flutter Test

This command runs the Flutter test suite and reports results. When failures occur, it diagnoses and fixes issues incrementally.

## What This Command Does

1. **Run Tests**: Execute `flutter test` (or scope to changed files)
2. **Parse Failures**: Identify failing tests by type and cause
3. **Fix Incrementally**: One failure at a time where possible
4. **Verify**: Re-run after each fix
5. **Report**: Show coverage summary and remaining failures

## When to Use

Use `/flutter-test` when:
- After implementing a feature to verify nothing broke
- After running `/flutter-build` to ensure tests pass
- To check test coverage on new code
- When a specific test file is failing
- Before submitting a PR

## Commands Run

```bash
# Run all tests
flutter test 2>&1

# Run with coverage
flutter test --coverage 2>&1

# Run specific test file
flutter test test/unit/domain/usecases/get_user_test.dart 2>&1

# Run tests matching a name pattern
flutter test --name "CartBloc" 2>&1

# Run integration tests (requires device/emulator)
flutter test integration_test/ 2>&1

# Goldens only (run on the pinned golden OS; other OSes use --exclude-tags golden)
flutter test --tags golden 2>&1

# Update golden files ONLY after a human confirmed the visual change is intended
flutter test --update-goldens --tags golden 2>&1
```

## Golden Gate

Never run `--update-goldens` to make a red test green. On a golden mismatch:
1. Open the failure images under `test/goldens/failures/` (or the directory next to the test) and compare master, test, and diff.
2. If the change is unintended, fix the code. If intended, say which UI change caused it, then update.
3. Check the matrix still covers LTR and RTL, and that fonts are loaded (text rendered as boxes means the font loader did not run).
4. If goldens fail only on a developer machine but pass on CI, it is an OS rasterization difference: do not update, run with `--exclude-tags golden` locally.

## Example Session

````text
User: /flutter-test

Agent:
# Flutter Test Run

## Test Execution

```
$ flutter test
00:05 +42 -2: Some tests failed.

FAILED: test/unit/data/user_repository_test.dart
  UserRepository getById
    returns null when user not found
    Expected: null
    Actual: User(id: 'test-id', name: 'Test User')

FAILED: test/widget/cart_page_test.dart
  CartPage
    shows empty state when cart is empty
    Expected: exactly one widget with text 'Your cart is empty'
    Found: no widget with text 'Your cart is empty'
```

## Fix 1: Repository Test

File: test/unit/data/user_repository_test.dart
Failure: `getById` returns a user when it should return null for missing ID

Root cause: Test setup adds a user with ID 'test-id' but queries with 'missing-id'.
Fix: Updated test to query with 'missing-id', setup was correct, query was wrong.

```
$ flutter test test/unit/data/user_repository_test.dart
1 test passed.
```

## Fix 2: Widget Test

File: test/widget/cart_page_test.dart
Failure: Empty state text widget not found

Root cause: Empty state message was renamed from 'Your cart is empty' to 'Cart is empty' in the widget.
Fix: Updated test string to match current widget copy.

```
$ flutter test test/widget/cart_page_test.dart
1 test passed.
```

## Final Run

```
$ flutter test --coverage
All 44 tests passed.
Coverage: 84.2% (target: 80%)
```

## Summary

| Metric | Value |
|--------|-------|
| Total tests | 44 |
| Passed | 44 |
| Failed | 0 |
| Coverage | 84.2% |

Test Status: PASS
````

## Common Test Failures

| Failure | Typical Fix |
|---------|-------------|
| `Expected: <X> Actual: <Y>` | Update assertion or fix implementation |
| `Widget not found` | Fix finder selector or update test after widget rename |
| `Golden file not found` | New golden: generate on the pinned golden OS with `--update-goldens --tags golden`, review the PNG, commit it |
| `Golden mismatch` | Follow the Golden Gate above |
| Golden text renders as boxes | Font loader missing: add `test/flutter_test_config.dart` that loads bundled fonts |
| RTL test finds LTR layout | `GlobalWidgetsLocalizations` missing from delegates, or `locale` not passed to the test app |
| `MissingPluginException` | Mock platform channel in test setup |
| `LateInitializationError` | Initialize `late` fields in `setUp()` |
| `pumpAndSettle timed out` | Replace with explicit `pump(Duration)` calls |

## Related Commands

- `/flutter-build`: Fix build errors before running tests
- `/flutter-review`: Review code after tests pass
- `tdd-workflow` skill: Test-driven development workflow

## Related

- Agent: `agents/flutter-reviewer.md`
- Agent: `agents/dart-build-resolver.md`
- Skill: `skills/flutter-dart-code-review/`
- Skill: `skills/dart-flutter-patterns/references/widget-and-golden-tests.md`
- Rules: `rules/dart/testing.md`
