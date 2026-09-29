---
paths:
  - "**/*.dart"
  - "**/pubspec.yaml"
  - "**/analysis_options.yaml"
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Dart/Flutter Hooks

> This file extends [common/hooks.md](../common/hooks.md) with Dart and Flutter-specific content.

## PostToolUse Hooks

Neva ships its hook runtime in Python (neva-core). When the Dart hooks are enabled there, they do this:

- **dart format**: format the edited `.dart` file after every Edit or Write
- **dart analyze**: analyze the edited file and surface new warnings to the model
- **flutter test**: never per edit; too slow. Run through `/flutter-test` or CI

To wire it by hand without Neva, the Claude Code hook schema takes a string `matcher` over tool names and passes the file path on stdin as JSON:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "f=$(jq -r '.tool_input.file_path // empty'); case \"$f\" in *.dart) dart format \"$f\" >/dev/null && dart analyze \"$f\" ;; esac"
          }
        ]
      }
    ]
  }
}
```

Skip generated files (`*.g.dart`, `*.freezed.dart`): they are rewritten by `build_runner`, and formatting them creates noise diffs.

## Pre-commit Checks

Run before committing Dart/Flutter changes:

```bash
dart format --set-exit-if-changed .
dart analyze --fatal-infos
flutter test
```

## Useful One-liners

```bash
# Format all Dart files
dart format .

# Analyze and report issues
dart analyze

# Run all tests with coverage
flutter test --coverage

# Regenerate code-gen files
dart run build_runner build --delete-conflicting-outputs

# Check for outdated packages
flutter pub outdated

# Upgrade packages within constraints
flutter pub upgrade
```
