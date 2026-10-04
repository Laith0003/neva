<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->
# Testing Requirements

## Minimum Test Coverage: 80%

Test types (all required):
1. **Unit tests**: individual functions, utilities, components
2. **Integration tests**: API endpoints, database operations
3. **E2E tests**: critical user flows (framework chosen per language)

## Test-Driven Development

Mandatory workflow:
1. Write the test first (RED)
2. Run the test. It must FAIL, and fail for the intended reason
3. Write the minimal implementation (GREEN)
4. Run the test. It must PASS
5. Refactor (IMPROVE), tests stay green
6. Verify coverage (80%+)

### The RED Gate

A test that was written but not compiled and executed does not count as RED. Valid RED is one of:
- **Runtime RED**: the test target compiles, the new test actually executes, and it fails.
- **Compile-time RED**: the new test references the missing or buggy code path, and that compile failure is the intended signal.

The failure must come from the missing behavior or the bug, not from unrelated syntax errors, broken setup, missing dependencies, or other regressions. Do not edit production code until RED is confirmed.

### Evidence

Keep a mapping from task to test to RED evidence to GREEN evidence. If the repo uses git, checkpoint after RED (`test: add reproducer for <bug>`) and after GREEN. If checkpoints get squashed, copy the RED and GREEN summary into the PR body first.

## Test Isolation

- Tests never touch a development or production database. Point the test config at an in-memory or throwaway database, and verify it before the first run.
- Never run a destructive test command (fresh migrations, truncation) on a branch or checkout that lacks the isolation fix. Older commits may predate it.
- Tests do not share state through files, globals, or ordering.

## Prove the Check Can Fail

A test or check that has only ever been green is unproven.
- Before trusting a new check, make it fail against the real bad case, then make it pass.
- Test against the real historical state, not only a synthetic fixture.
- Match the claim, not a mention: a string check that trips on the correct output is a check that gets ignored.
- A verdict recorded by hand is bound to the output it judged. Fingerprint that output; a changed output reads as unjudged.

## Troubleshooting Test Failures

1. Use **neva-core:tdd-guide**
2. Check test isolation
3. Verify mocks are correct
4. Fix the implementation, not the tests (unless the tests are wrong)

## Agent Support

- **neva-core:tdd-guide**: use proactively for new features; enforces tests first

## Test Structure (AAA Pattern)

Prefer Arrange, Act, Assert:

```typescript
test('calculates similarity correctly', () => {
  // Arrange
  const vector1 = [1, 0, 0]
  const vector2 = [0, 1, 0]

  // Act
  const similarity = calculateCosineSimilarity(vector1, vector2)

  // Assert
  expect(similarity).toBe(0)
})
```

### Test Naming

Names describe the behavior under test:

```typescript
test('returns empty array when no markets match query', () => {})
test('throws error when API key is missing', () => {})
test('falls back to substring search when Redis is unavailable', () => {})
```
