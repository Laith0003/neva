# Money tracking: hledger and the ledger

Your money is tracked in a plain-text ledger using hledger format. Every transaction is a
single entry; the agent appends new transactions and reports balances and summaries with
hledger commands. If a figure is not in the ledger, the agent says so.

## The ledger file

Location: `05 Money/<year>.journal` (default: `~/Vault/05 Money/2026.journal`)

Format: hledger double-entry accounting. Example:
```
2026-01-05 * Example Client | invoice 001 paid
  Assets:Cash        +1000.00 JOD
  Income:Clients    -1000.00 JOD

2026-01-10 * Equipment
  Expenses:Supplies  100.00 JOD
  Assets:Cash        -100.00 JOD
```

Read more: https://hledger.org/1.32/hledger.html (official hledger docs)

## How the agent uses it

When you ask "How much do I owe Alice?" the agent:
1. Reads the current ledger file
2. Runs `hledger` commands to find transactions matching "Alice"
3. Reports the exact balance or amounts, with the command used
4. If no match exists, says so plainly

The agent will never invent a money figure. If you ask "Did I invoice Acme?" and there is no
transaction with "Acme", the agent says "I don't have that in the ledger."

## Money is gated, always

Adding or editing money notes in `05 Money/` always requires your approval. The agent cannot
silently change a transaction; canon-propose prevents it. This is the scar from early
development when an agent added a malformed transaction and it went unnoticed for days.

## Derived figures: TOOLS.md money anchor

At install time and during certain operations, a MONEY-ANCHOR is generated from the ledger
and cached in the workspace TOOLS.md file. This cached version is used to speed up common
queries and is regenerated daily. You do not need to edit it; it is automatic.

If you see a figure from the agent that you cannot find in the ledger file itself, it came
from this cache. The cache is derived from the ledger and updated daily, so it is always
accurate as of the last update run.

## Optional: supporting notes

You can add markdown notes in `05 Money/` to explain specific transactions:
- "Invoice 001 - Acme contract details"
- "Quarterly budget planning and notes"
- "Tax documentation links"

These notes are not transactions. They are supporting documents. The ledger stays clean
(transaction-only); notes explain context.

## Viewing your money

To see your current balance:
```bash
hledger -f ~/Vault/05\ Money/2026.journal balance
```

To see monthly summaries:
```bash
hledger -f ~/Vault/05\ Money/2026.journal incomestatement -M
```

To search for a specific person or project:
```bash
hledger -f ~/Vault/05\ Money/2026.journal register Alice
```

Install hledger: `brew install hledger` (macOS) or `sudo apt install hledger` (Linux).

The agent can run these commands for you; ask "show me my balance" or "what have I earned
from Acme."

---

See [docs/05-vault-structure.md](05-vault-structure.md) for where money notes live and
[docs/04-vault-and-canon.md](04-vault-and-canon.md) for how facts are grounded.
