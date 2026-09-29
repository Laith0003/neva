---
paths:
  - "**/*.php"
  - "**/phpunit.xml"
  - "**/phpunit.xml.dist"
  - "**/composer.json"
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Database-isolation gate from Neva house practice. -->
# PHP Testing

> This file extends [common/testing.md](../common/testing.md) with PHP specific content.

## Test Database Isolation (hard rule)

- Tests run on a dedicated, disposable database: SQLite `:memory:` by default. Never the development database.
- Both layers must hold: `phpunit.xml` sets `DB_CONNECTION=sqlite` and `DB_DATABASE=:memory:` (uncommented), AND `config/database.php` reads `env('DB_DATABASE')` in the sqlite block instead of a hardcoded path.
- Verify both before running tests on any branch or commit you have not checked. Never check out an older commit to baseline a suite.
- Keep a guard test asserting the connection is `sqlite` and the database is `:memory:`.

## Framework

Use **PHPUnit** as the default test framework. If **Pest** is configured in the project, prefer Pest for new tests and avoid mixing frameworks.

## Coverage

```bash
vendor/bin/phpunit --coverage-text
# or
vendor/bin/pest --coverage
```

Prefer **pcov** or **Xdebug** in CI, and keep coverage thresholds in CI rather than as tribal knowledge.

## Test Organization

- Separate fast unit tests from framework/database integration tests.
- Use factory/builders for fixtures instead of large hand-written arrays.
- Keep HTTP/controller tests focused on transport and validation; move business rules into service-level tests.

## Inertia

If the project uses Inertia.js, prefer `assertInertia` with `AssertableInertia` to verify component names and props instead of raw JSON assertions.

## Reference

See skill: `neva-core:tdd-workflow` for the repo-wide RED -> GREEN -> REFACTOR loop.
See skill: `laravel-verification` for the pre-merge and pre-deploy loop.
See skill: `laravel-tdd` for Laravel-specific testing patterns (PHPUnit and Pest).
