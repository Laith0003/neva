# neva-omni worker

Your assistant on a URL. One Cloudflare Worker that takes a message, picks a model, keeps the
thread, and answers with the same brain pack your local sessions read.

It is free to run on Cloudflare's free tier and on the free tiers of the providers in
`src/providers.js`. A provider with no key is skipped, so it serves on whatever you have given
it and says so when you have given it nothing.

## What it is made of

| File | Does |
|------|------|
| `src/index.js` | Routes, the brain pack system turn, the breaker that survives between requests |
| `src/auth.js` | Who is let in: the required device token |
| `src/router.js` | Classifies the message and ranks the models, free first |
| `src/fallback.js` | Walks the ranked list, opens a circuit breaker, refuses paid execution |
| `src/call.js` | One call to one model, through an injected `fetchImpl` |
| `src/threads.js` | `MemoryStore`, `D1Store`, and `fitToWindow` for trimming a long thread |
| `migrations/0001_threads.sql` | The `threads` and `messages` tables |

## Routes

Every route needs auth. Without it you get `401` and the one line that tells you how to fix it.

| Route | Body | Answers |
|-------|------|---------|
| `POST /chat` | `{"thread_id": "...", "message": "...", "model": "groq:llama-3.3-70b-versatile"}` | `{thread_id, reply, model, provider, reason, failures}` |
| `GET /threads` | | `{threads: [{id, title, updated_at}]}` |
| `GET /threads/:id` | | `{id, title, updated_at, messages}` |
| `PUT /brainpack` | the pack from `neva brainpack` | `{stored, generated_at, tiers}` |

`thread_id` and `model` are optional. With no `thread_id` a new thread is opened and its id comes
back in the reply. With no `model` the router picks, and the `reason` field says why.
Unknown or unavailable pins are refused. A valid pin calls only that model. To consent to
automatic routing across providers, submit a request without `model`.

`PUT /brainpack` stores a pack only when `tiers` holds `small`, `medium` and `large`, each with a
nonempty `text` within its limit (8000, 32000, 120000 characters) and a `chars` count equal to
that text's length. Anything else is a `400` naming the field, and the stored pack is left as it
was.

The user's turn is stored before any provider is called, so a total outage leaves what you typed
on the thread rather than losing it. A failed call never becomes an empty answer: `502` carries a
`failures` array naming each provider and its error.

## Deploy it

```bash
cd omni/worker

# 1. The storage. Each command prints an id; paste it into wrangler.toml.
wrangler kv namespace create BRAIN
wrangler d1 create neva-omni
wrangler d1 migrations apply neva-omni --remote

# 2. The secrets. DEVICE_TOKEN is required on every route.
wrangler secret put DEVICE_TOKEN        # any long random string; keep it in your password manager
wrangler secret put GROQ_API_KEY
wrangler secret put GEMINI_API_KEY

# 3. Check the pinned model ids still exist, then deploy.
GROQ_API_KEY=... GEMINI_API_KEY=... node scripts/check-models.mjs
wrangler deploy --dry-run                # build only, touches nothing
wrangler deploy
```

Configure a custom hostname before deploying. The default workers.dev endpoint and preview URLs
are disabled. You can put [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/)
in front of the hostname as an additional layer. The Worker requires
`Authorization: Bearer <DEVICE_TOKEN>` even behind Access. Unsigned Access headers grant no access.

## Give it your brain

The pack holds only the files you list. Nothing is collected by default: not your rules, not
your lessons, not your memory index. Write `~/.config/neva/omni.json` (or point
`NEVA_OMNI_CONFIG` at another file) with an include list of paths or globs. Relative entries
resolve from the config file's folder.

```json
{"include": ["~/notes/assistant/rules/*.md", "~/notes/assistant/style.md"]}
```

A glob never picks up a file named `MEMORY.md`, or anything inside a file or folder whose name
contains `confidential`. List such a file by its exact path if you mean to send it.

```bash
neva brainpack                                      # prints every file and its size, then writes
NEVA_OMNI_TOKEN=... neva omni push --url https://omni.example.com
```

`neva brainpack` prints each source file with its size before it writes anything, and names
each file a glob skipped. A file holding a key-shaped string is refused by name and nothing is
written. `neva omni push` prints the same list and the providers the pack will reach before it
sends, and refuses a pack that does not list its files.

**What leaves your machine.** The worker sends the pack as the system prompt on every chat, to
every provider configured on it: Workers AI, Groq and Gemini. Put nothing in the include list
you would not hand to all three. Gemini's free tier may use prompts to improve Google's
products. Use a Gemini key from a Google Cloud project with no billing account attached: a key
from a billed project is charged, and the worker cannot tell the difference.

The pack is tiered. A model with a 128k window gets `large`, 32k gets `medium`, anything smaller
gets `small`, and `fitToWindow` trims the thread so the two together fit.

## Spend

The registered providers use free tiers, and free means the key's account: keep each key on a
project or account with no billing attached. Paid-provider execution is unavailable. There is no
supported opt-in override. Static spend caps cannot reserve concurrent charges or settle actual
costs. Paid support requires a durable accounting implementation before any paid provider can
be called. The end-to-end test proves that an attempted enable flag and a positive cap still
make no provider call.

## Test it

```bash
npm test                      # node --test, no network, no monkey-patched globals
```

`env.fetchImpl` is the only seam to the outside world, so nothing in the suite reaches a
provider, and `resetBreakers()` keeps one test's opened breaker out of the next test.
