const OPEN_MS = 5 * 60 * 1000;

export function capCheck(pick, opts) {
  if (pick.provider.free) return null;
  const id = pick.provider.id;
  const cap = opts.caps[id] ?? 0;
  if (cap <= 0) return `model ${pick.model.id} needs a spend cap: set NEVA_CAP_${id.toUpperCase().replace(/-/g, "_")}`;
  if ((opts.spent[id] ?? 0) >= cap) return `spend cap reached for ${id}: raise NEVA_CAP_${id.toUpperCase()} or wait for next month`;
  // Static environment spend cannot reserve concurrent charges. Paid execution remains
  // unavailable until a durable ledger can reserve and settle actual provider charges.
  return "paid provider execution is unavailable: use a free provider until durable spend accounting is configured";
}

export async function runWithFallback(picks, callFn, state, opts) {
  const failures = [];
  for (const pick of picks) {
    const id = pick.provider.id;
    const b = state.breakers.get(id) ?? { openUntil: 0, fails: 0 };
    if (b.openUntil > state.now()) { failures.push({ provider: id, model: pick.model.id, error: "circuit open, recently failing" }); continue; }
    const capMsg = capCheck(pick, opts);
    if (capMsg) {
      failures.push({ provider: id, model: pick.model.id, error: capMsg });
      if (!opts.auto) break;
      continue;
    }
    try {
      const result = await callFn(pick);
      state.breakers.set(id, { openUntil: 0, fails: 0 });
      // The failures so far ride along on a success too: a reply that only landed on the third
      // provider is not the same event as one that landed on the first, and the caller has to
      // be able to tell them apart.
      return { ok: true, pick, result, failures };
    } catch (e) {
      const fails = b.fails + 1;
      state.breakers.set(id, { fails, openUntil: fails >= 3 ? state.now() + OPEN_MS : 0 });
      failures.push({ provider: id, model: pick.model.id, error: String(e.message || e) });
    }
  }
  return { ok: false, failures };
}
