// One call to one model. fetchImpl is injected rather than taken from the global, so a test
// never has to monkey-patch global.fetch and two tests in one process cannot leak a stub into
// each other. Every failure throws with the provider's own status and body in the message:
// runWithFallback turns that into a named failure, so nothing is ever reported as an empty
// answer when it was really an error.

export async function callModel(pick, messages, env, fetchImpl) {
  if (pick.provider.kind === "workers-ai") return callWorkersAI(pick, messages, env);
  return callOpenAICompatible(pick, messages, env, fetchImpl);
}

async function callWorkersAI(pick, messages, env) {
  if (!env.AI) throw new Error("the Workers AI binding is missing: add [ai] binding = \"AI\" to wrangler.toml");
  const reply = await env.AI.run(pick.model.id, { messages });
  const text = reply?.response ?? reply?.result?.response;
  if (typeof text !== "string" || text === "") {
    throw new Error(`workers-ai returned no text for ${pick.model.id}`);
  }
  return text;
}

async function callOpenAICompatible(pick, messages, env, fetchImpl) {
  const key = env[pick.provider.keyEnv];
  if (!key) throw new Error(`no API key for ${pick.provider.id}: set ${pick.provider.keyEnv} as a worker secret`);

  const response = await fetchImpl(`${pick.provider.baseUrl}/chat/completions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: pick.model.id, messages }),
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`${pick.provider.id} returned ${response.status}: ${detail.slice(0, 200)}`);
  }

  const data = await response.json();
  const text = data?.choices?.[0]?.message?.content;
  if (typeof text !== "string" || text === "") {
    throw new Error(`${pick.provider.id} returned no text for ${pick.model.id}`);
  }
  return text;
}
