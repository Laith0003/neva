---
name: shopify-content
description: Use when writing or rewriting Shopify product descriptions, collection copy or meta descriptions, including Arabic-first stores. Voice first, 4-block structure, preview table, and store writes only after approval with a backup.
---
<!-- Generalized for Neva from a local skill; no ECC source. -->

# Shopify Content

Write store copy that sells, in the store's language. For an Arabic-first store, Arabic is the deliverable; internal notes can stay in English.

## Step 1: Voice (always first)

Load the brand document (`brand-system`) and voice file (`brand-voice`) if they exist and treat violations as bugs. Otherwise confirm with the user:

- tone in three adjectives (for example: terse, confident, warm)
- forbidden words and patterns (for example: no emojis, no "world-class", no exclamation spam)
- required phrases and spellings (brand name, product terms)
- language variety and register (for Arabic: formal standard, neutral dialect, or local dialect)

## Step 2: Draft per product

60 to 90 words, exactly four blocks:

1. Hook: the primary benefit in one line. The outcome, not the product name.
2. Why it works: two or three features, each tied to its benefit ("cotton blend" is a feature; "dry by noon" is why anyone cares).
3. Proof: one concrete credibility point (material spec, count, guarantee, origin).
4. CTA: one short action line matched to the store's purchase flow (cash on delivery, delivery promise).

SEO rules:

- Front-load the primary keyword in the first sentence.
- Work in exactly one long-tail variant naturally.
- Meta description is a separate output under 155 characters with the primary keyword and one reason to click. Count before presenting; over 155 is a defect.

Write natively in the target language, never translated from English. Keep numerals and sizes in the store's convention. No emojis, no em-dashes.

## Step 3: Preview, then write

State which store the writes target, then show a preview table. Never write to the store before approval.

| Product | Current description | Proposed description (4 blocks) | Meta (155 max) | Primary keyword |

On an explicit yes:

1. Back up the current `descriptionHtml` and `seo` values for every product touched, so rollback is a rewrite of the saved values.
2. Write one product at a time through the Admin API (`productUpdate` or `productSet` with `descriptionHtml` and `seo { title description }`), checking `userErrors` after each call. Stop on the first error and name the field and the fix.
3. Wrap the description in minimal HTML: one `<p>` per block, `<strong>` for the hook line, no inline styles.
4. Read each product back and confirm the stored copy matches the approved text.
