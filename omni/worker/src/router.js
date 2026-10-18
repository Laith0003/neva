import { PROVIDERS } from "./providers.js";

export function classifyTask(text) {
  if (/[؀-ۿ]/.test(text)) return "arabic";
  if (/\b(should|trade-?offs?|decide|strategy|which is better|plan)\b/i.test(text)) return "judgment";
  if (text.length < 120 && /^(what|who|when|where|how many|define)\b/i.test(text.trim())) return "lookup";
  return "writing";
}

function available(p, env) {
  if (p.kind === "workers-ai") return Boolean(env.AI);
  return Boolean(env[p.keyEnv]);
}

export function pickModels(task, env, pinned) {
  const picks = [];
  for (const p of PROVIDERS) {
    if (!available(p, env)) continue;
    for (const m of p.models) {
      const score = (p.free ? 10 : 0) + (m.strengths.includes(task) ? 5 : 0) + Math.log10(m.window);
      picks.push({ provider: p, model: m, reason: `auto: ${task}${p.free ? ", free" : ""}`, score });
    }
  }
  picks.sort((a, b) => b.score - a.score);
  if (pinned) {
    const i = picks.findIndex(x => `${x.provider.id}:${x.model.id}` === pinned);
    if (i < 0) {
      const known = PROVIDERS.some(p => p.models.some(m => `${p.id}:${m.id}` === pinned));
      throw new Error(`model ${pinned} is ${known ? "unavailable: configure its provider key or binding" : "unknown: choose a registered provider:model"}`);
    }
    return [{ ...picks[i], reason: "pinned" }];
  }
  return picks;
}
