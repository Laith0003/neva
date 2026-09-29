---
paths:
  - "**/*.css"
  - "**/*.scss"
  - "**/*.sass"
  - "**/*.less"
  - "**/*.html"
  - "**/*.blade.php"
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.vue"
  - "**/*.svelte"
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Bidirectional and render-verification checks added from Neva house practice. -->
> This file extends [common/testing.md](../common/testing.md) with web-specific testing content.

# Web Testing Rules

## Priority Order

### 1. Visual Regression

- Screenshot key breakpoints: 320, 768, 1024, 1440
- Test hero sections, scrollytelling sections, and meaningful states
- Use Playwright screenshots for visual-heavy work
- If both themes exist, test both

### 2. Accessibility

- Run automated accessibility checks
- Test keyboard navigation
- Verify reduced-motion behavior
- Verify color contrast

### 3. Performance

- Run Lighthouse or equivalent against meaningful pages
- Keep CWV targets from [performance.md](performance.md)

### 4. Cross-Browser

- Minimum: Chrome, Firefox, Safari
- Test scrolling, motion, and fallback behavior

### 5. Direction and Locale

- Screenshot every changed screen in LTR and RTL at 375 and 1440.
- Check that directional icons mirror, logical spacing flips, and LTR islands (numbers, phones, codes) do not reorder.
- Check long translations: the longest locale must wrap without overflow or truncation of meaning.

### 6. Responsive

- Test 320, 375, 768, 1024, 1440, 1920
- Verify no overflow
- Verify touch interactions

## E2E Shape

```ts
import { test, expect } from '@playwright/test';

test('landing hero loads', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toBeVisible();
});
```

- Avoid flaky timeout-based assertions
- Prefer deterministic waits

## Unit Tests

- Test utilities, data transforms, and custom hooks
- For highly visual components, visual regression often carries more signal than brittle markup assertions
- Visual regression supplements coverage targets; it does not replace them

## Done Means Seen

Never report a UI change as done from a passing build alone. Render the actual surface, take a screenshot, and look at it. If the change is deployed, screenshot the deployed surface, not only the local one.
