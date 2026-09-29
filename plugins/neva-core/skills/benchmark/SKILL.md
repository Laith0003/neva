---
name: benchmark
description: "Use when checking page speed, responding to 'it feels slow', comparing performance before and after a PR, verifying launch budgets, or tracking trends: Core Web Vitals, bundle size, API latency percentiles, and build times against a stored baseline."
argument-hint: "[baseline|compare|trend] [url] [--quick] [--pages /,/dashboard] [--diff]"
license: MIT
metadata:
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Merged with garrytan/gstack benchmark (MIT, Garry Tan). -->

# Benchmark: Performance Baseline & Regression Detection

Performance rarely dies in one big regression. It dies by a thousand paper cuts: each PR adds 50 ms here, 20 KB there, and one day the app takes 8 seconds to load and nobody knows when it got slow. Measure, baseline, compare, alert.

## When to Use

- Before and after a PR to measure performance impact
- Setting up performance baselines for a project
- When users report "it feels slow"
- Before a launch: ensure you meet performance targets
- Comparing your stack against alternatives
- Tracking performance trends over time

## Arguments

```
/benchmark <url>                          full audit with baseline comparison
/benchmark baseline <url>                 capture baseline (run before making changes)
/benchmark compare <url>                  compare current run against the baseline
/benchmark <url> --quick                  single-pass timing check, no baseline needed
/benchmark <url> --pages /,/dashboard     specify pages
/benchmark --diff                         only pages affected by the current branch
/benchmark trend                          show trends from historical runs
```

`--diff` page discovery:

```bash
git diff $(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo main)...HEAD --name-only
```

Map changed routes, views, and components to pages. Otherwise discover pages from site navigation or use `--pages`.

## Setup

```bash
mkdir -p .neva/benchmarks/baselines
```

## Mode 1: Page Performance

Measures real browser metrics via any browser MCP (claude-in-chrome, Playwright, Puppeteer) by evaluating JavaScript in the page. The optional third-party gstack `browse` CLI (`perf`, `eval`) works too if installed; never install it from this skill.

```
1. Navigate to each target URL
2. Measure Core Web Vitals:
   - LCP (Largest Contentful Paint) - target < 2.5s
   - CLS (Cumulative Layout Shift) - target < 0.1
   - INP (Interaction to Next Paint) - target < 200ms
   - FCP (First Contentful Paint) - target < 1.8s
   - TTFB (Time to First Byte) - target < 800ms
3. Measure resource sizes:
   - Total page weight (target < 1MB)
   - JS bundle size (target < 200KB gzipped)
   - CSS size
   - Image weight
   - Third-party script weight
4. Count network requests
5. Check for render-blocking resources
```

Collect with `performance.getEntries()`, never estimates:

```js
// Navigation timing
JSON.stringify(performance.getEntriesByType('navigation')[0])
// TTFB = responseStart - requestStart
// DOM Interactive = domInteractive; DOM Complete = domComplete; Full Load = loadEventEnd
// FCP from 'paint' entries; LCP from a PerformanceObserver on 'largest-contentful-paint'

// Slowest 15 resources
JSON.stringify(performance.getEntriesByType('resource')
  .map(r => ({name: r.name.split('/').pop().split('?')[0], type: r.initiatorType, size: r.transferSize, duration: Math.round(r.duration)}))
  .sort((a,b) => b.duration - a.duration).slice(0,15))

// Bundles
JSON.stringify(performance.getEntriesByType('resource').filter(r => r.initiatorType === 'script')
  .map(r => ({name: r.name.split('/').pop().split('?')[0], size: r.transferSize})))
JSON.stringify(performance.getEntriesByType('resource').filter(r => r.initiatorType === 'css')
  .map(r => ({name: r.name.split('/').pop().split('?')[0], size: r.transferSize})))

// Network summary
(() => { const r = performance.getEntriesByType('resource'); return JSON.stringify({total_requests: r.length, total_transfer: r.reduce((s,e) => s + (e.transferSize||0), 0), by_type: Object.entries(r.reduce((a,e) => { a[e.initiatorType] = (a[e.initiatorType]||0) + 1; return a; }, {})).sort((a,b) => b[1]-a[1])})})()
```

`transferSize` is 0 for cached or cross-origin resources without `Timing-Allow-Origin`. Measure cold (cache disabled or fresh profile) and say so in the report.

## Mode 2: API Performance

Benchmarks API endpoints:

```
1. Hit each endpoint 100 times
2. Measure: p50, p95, p99 latency
3. Track: response size, status codes
4. Test under load: 10 concurrent requests
5. Compare against SLA targets
```

Only GET or idempotent endpoints, and only against local, staging, or preview unless the user explicitly opts in for production.

## Mode 3: Build Performance

Measures the development feedback loop:

```
1. Cold build time
2. Hot reload time (HMR)
3. Test suite duration
4. TypeScript check time
5. Lint time
6. Docker build time
```

## Mode 4: Baseline and Comparison

```
/benchmark baseline <url>    # saves current metrics
# ... make changes ...
/benchmark compare <url>     # compares against baseline
```

Baseline file `.neva/benchmarks/baselines/baseline.json`:

```json
{
  "url": "<url>",
  "timestamp": "<ISO>",
  "branch": "<branch>",
  "pages": {
    "/": {
      "ttfb_ms": 120, "fcp_ms": 450, "lcp_ms": 800, "cls": 0.02, "inp_ms": 90,
      "dom_interactive_ms": 600, "dom_complete_ms": 1200, "full_load_ms": 1400,
      "total_requests": 42, "total_transfer_bytes": 1250000,
      "js_bundle_bytes": 450000, "css_bundle_bytes": 85000,
      "largest_resources": [{"name": "main.js", "size": 320000, "duration": 180}]
    }
  },
  "api": { "GET /api/items": { "p50_ms": 40, "p95_ms": 120, "p99_ms": 210 } },
  "build": { "cold_build_s": 12, "test_suite_s": 30 }
}
```

**Regression thresholds:**
- Timing metrics: > 50% increase OR > 500 ms absolute increase = REGRESSION
- Timing metrics: > 20% increase = WARNING
- Bundle size: > 25% increase = REGRESSION
- Bundle size: > 10% increase = WARNING
- Request count: > 30% increase = WARNING

Output:
```
| Metric | Before | After | Delta | Verdict |
|--------|--------|-------|-------|---------|
| LCP | 1.2s | 1.4s | +200ms | WARNING |
| Bundle | 180KB | 175KB | -5KB | BETTER |
| Build | 12s | 14s | +2s | WARNING |

REGRESSIONS DETECTED: N
  [1] LCP doubled (800ms -> 1600ms): likely a large new image or blocking resource
```

Every REGRESSION line names the probable cause from the resource data.

## Slowest Resources

```
TOP 10 SLOWEST RESOURCES
#   Resource                  Type      Size      Duration
1   vendor.chunk.js           script    320KB     480ms
2   analytics.js              script    45KB      250ms    (third-party)
...

RECOMMENDATIONS:
- vendor.chunk.js: code-split, 320KB is large for initial load
- analytics.js: load async/defer, blocks rendering for 250ms
- hero-image.webp: add width/height to prevent CLS, lazy-load below the fold
```

## Performance Budget

```
Metric              Budget      Actual      Status
FCP                 < 1.8s      0.48s       PASS
LCP                 < 2.5s      1.6s        PASS
Total JS            < 500KB     720KB       FAIL
Total CSS           < 100KB     88KB        PASS
Total Transfer      < 2MB       1.8MB       WARNING (90%)
HTTP Requests       < 50        58          FAIL

Grade: B (4/6 passing)
```

Budgets are defaults. A project budget file (for example `.neva/benchmarks/budget.json`) overrides them.

## Trend Mode

Load historical runs and show the last 5:

```
Date        FCP     LCP     Bundle    Requests    Grade
2026-03-10  420ms   750ms   380KB     38          A
2026-03-18  480ms   1600ms  720KB     58          B

TREND: Performance degrading. LCP doubled in 8 days. JS bundle growing 50KB/week.
```

## Output

Baselines in `.neva/benchmarks/baselines/` as JSON; each run in `.neva/benchmarks/{date}-benchmark.md` and `.json`. Git-track the baselines so the team shares them.

## Rules

- **Measure, don't guess.** Real `performance.getEntries()` data, never estimates.
- **Baseline is essential.** Without one you can report absolute numbers but cannot detect regressions. Always offer to capture one.
- **Relative thresholds, not absolute.** 2000 ms is fine for a complex dashboard and terrible for a landing page. Compare against this project's baseline.
- **Third-party scripts are context.** Flag them; focus recommendations on first-party resources.
- **Bundle size is the leading indicator.** Load time varies with network; bundle size is deterministic. Track it every run.
- **Run each timing measurement at least 3 times and report the median**; a single sample is noise.
- **Read-only.** Produce the report. Do not modify code unless explicitly asked.

## Integration

- CI: run `/benchmark compare` on every PR
- Pair with `neva-ops:canary-watch` for post-deploy monitoring
- Pair with `neva-core:browser-qa` for the full pre-ship checklist
- For "make it faster" work, hand the baseline to `neva-core:benchmark-optimization-loop`
