---
name: seo
description: "Use when auditing or improving search visibility: crawlability, indexability, on-page, structured data, Core Web Vitals, keyword mapping, internal links and AI answer engines. Every fix is page-specific and falsifiable."
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Audit orchestration and synthesis mechanics draw on claude-seo (MIT, AgriciDaniel); AI answer engine section draws on coreyhaines31/marketingskills ai-seo (MIT) and geo-seo-claude. -->

# SEO

Improve search visibility through technical correctness, performance, and content relevance, not gimmicks.

## When to Use

Use this skill when:
- auditing crawlability, indexability, canonicals, or redirects
- improving title tags, meta descriptions, and heading structure
- adding or validating structured data
- improving Core Web Vitals
- doing keyword research and mapping keywords to URLs
- planning internal linking or sitemap / robots changes

## Depth Routing

This skill is the portable baseline. If the full `claude-seo` plugin (with its scripts and sub-agents) is installed, prefer it for full-site audits, backlink data, drift baselines and PDF reports, and use this skill's rules to judge its output. If the `geo` or `ai-seo` skills are installed, prefer them for deep AI-visibility work.

## How It Works

### Audit orchestration

1. Detect the business type from homepage signals: SaaS (pricing, docs, trial), local service (address, phone, service area, map embed), e-commerce (products, cart, product schema), publisher (articles, authors, dates), agency, other. The type changes which checks matter.
2. For a full audit, split the work and run it in parallel (sub-agents where available): technical, content quality, schema, sitemap, performance, visual and mobile, AI visibility. Add local, e-commerce or backlink passes only when the type or available data calls for them.
3. Read the actual pages and source before recommending anything.
4. Synthesize, then bucket. Critical, High, Medium and Low are the output of validation, not a substitute for it.

### Every recommendation carries

- the first-principle observation it rests on (what was seen, where)
- what it depends on and what it unblocks, so the plan can be sequenced
- a falsifiability check: how would we know this change failed?
- a leading indicator the user can watch without rerunning the audit

### Principles

1. Fix technical blockers before content optimization.
2. One page should have one clear primary search intent.
3. Prefer long-term quality signals over manipulative patterns.
4. Mobile-first assumptions matter because indexing is mobile-first.
5. Recommendations should be page-specific and implementable.

### Technical SEO checklist

#### Crawlability

- `robots.txt` should allow important pages and block low-value surfaces
- no important page should be unintentionally `noindex`
- important pages should be reachable within a shallow click depth
- avoid redirect chains longer than two hops
- canonical tags should be self-consistent and non-looping

#### Indexability

- preferred URL format should be consistent
- multilingual pages need correct hreflang if used
- sitemaps should reflect the intended public surface
- no duplicate URLs should compete without canonical control

#### Performance

- LCP < 2.5s
- INP < 200ms
- CLS < 0.1
- common fixes: preload hero assets, reduce render-blocking work, reserve layout space, trim heavy JS

#### Structured data

- homepage: organization or business schema where appropriate
- editorial pages: `Article` / `BlogPosting`
- product pages: `Product` and `Offer`
- interior pages: `BreadcrumbList`
- Q&A sections: `FAQPage` only when the content truly matches

#### AI answer engines

- AI crawlers are allowed in `robots.txt` for the surfaces the owner wants cited, and blocked only by decision, not by accident. Check the CDN or host firewall too; it can block bots the robots file allows.
- Content is server-rendered or prerendered so a crawler without JavaScript sees it.
- Passages answer one question each in the first sentences, with the claim, the number and the source together, so they can be quoted alone.
- Entity signals are consistent: organization and person schema with `sameAs` links, the same name and description across the site and profiles.
- `llms.txt` is optional and ignored by some engines; never present it as a ranking fix.

### On-page rules

#### Title tags

- aim for roughly 50-60 characters
- put the primary keyword or concept near the front
- make the title legible to humans, not stuffed for bots

#### Meta descriptions

- aim for roughly 120-160 characters
- describe the page honestly
- include the main topic naturally

#### Heading structure

- one clear `H1`
- `H2` and `H3` should reflect actual content hierarchy
- do not skip structure just for visual styling

### Keyword mapping

1. define the search intent
2. gather realistic keyword variants
3. prioritize by intent match, likely value, and competition
4. map one primary keyword/theme to one URL
5. detect and avoid cannibalization

### Internal linking

- link from strong pages to pages you want to rank
- use descriptive anchor text
- avoid generic anchors when a more specific one is possible
- backfill links from new pages to relevant existing ones

## Examples

### Title formula

```text
Primary Topic - Specific Modifier | Brand
```

### Meta description formula

```text
Action + topic + value proposition + one supporting detail
```

### JSON-LD example

```json
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "Page Title Here",
  "author": {
    "@type": "Person",
    "name": "Author Name"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Brand Name"
  }
}
```

### Audit output shape

```text
[HIGH] Duplicate title tags on product pages
Location: src/routes/products/[slug].tsx
Issue: Dynamic titles collapse to the same default string, which weakens relevance and creates duplicate signals.
Fix: Generate a unique title per product using the product name and primary category.
```

## Anti-Patterns

| Anti-pattern | Fix |
| --- | --- |
| keyword stuffing | write for users first |
| thin near-duplicate pages | consolidate or differentiate them |
| schema for content that is not actually present | match schema to reality |
| content advice without checking the actual page | read the real page first |
| generic “improve SEO” outputs | tie every recommendation to a page or asset |

## Related Skills

- `seo-specialist` (agent)
- `claude-seo`, `geo`, `ai-seo` when installed
- `frontend-patterns`
- `brand-voice`
- `market-research`
