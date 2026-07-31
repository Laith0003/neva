# Security: what protects you, and what does not

Self-hosted agents have a bad safety record for one reason: exposed gateways and open DM
policies. This template ships closed by default and doctor FAILS (not warns) on the two
killers.

## What is enforced here
- Gateway binds to 127.0.0.1 only. Doctor fails if it is reachable on any other interface.
- Telegram allowFrom locked to your numeric id. Doctor fails when unset.
- Tokens live in `~/.openclaw/openclaw.json` and `~/.config/lucy/identity.env` (600),
  which are never inside the repo or the vault. The agent's rules forbid pasting any
  credential into chat.
- Canon writes go through a gated tool; a raw write cannot silently corrupt your records.
- The agent refuses to state facts and figures that are not in your notes: this is also an
  injection-surface reduction, since planted text cannot become confident "knowledge".

## What this does NOT protect against
- A compromised machine. If your laptop or VPS is owned, the agent is owned.
- Prompt injection in content you feed it (web pages, emails). The grounding rules reduce
  blast radius; they do not make injection impossible. Keep the tool surface small.
- Skills or plugins you install from third parties. Read them; they run with your access.
- Yourself asking the agent to bypass its gates. The gates exist for the 2am you.

If you expose anything to the internet on purpose (tier 2 VPS setup), follow
tier2/hardening-checklist.md exactly, in order.
