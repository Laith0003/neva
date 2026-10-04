---
paths:
  - "**/*.php"
  - "**/composer.json"
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Blade and ledger notes from Neva house practice. -->
# PHP Patterns

> This file extends [common/patterns.md](../common/patterns.md) with PHP specific content.

## Thin Controllers, Explicit Services

- Keep controllers focused on transport: auth, validation, serialization, status codes.
- Move business rules into application/domain services that are easy to test without HTTP bootstrapping.

## DTOs and Value Objects

- Replace shape-heavy associative arrays with DTOs for requests, commands, and external API payloads.
- Use value objects for money, identifiers, date ranges, and other constrained concepts.

## Dependency Injection

- Depend on interfaces or narrow service contracts, not framework globals.
- Pass collaborators through constructors so services are testable without service-locator lookups.

## Boundaries

- Isolate ORM models from domain decisions when the model layer is doing more than persistence.
- Wrap third-party SDKs behind small adapters so the rest of the codebase depends on your contract, not theirs.

## Server-Rendered Views

- Blade components are the single source for repeated UI; extend with props or slots, never fork the markup.
- Views receive data; they never query. No business logic in templates.
- Every user-facing string goes through translation keys present in every locale.

## Derived State

- Money is integer minor units plus currency.
- Balances, points, and stock derive from an append-only event ledger; reversals append an inverse event that references the original.

## Reference

See skill: `api-design` for endpoint conventions and response-shape guidance.
See skill: `laravel-patterns` for Laravel-specific architecture guidance.
