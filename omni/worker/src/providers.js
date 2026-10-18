// Model ids are verified against each provider's /models list in Task 7 before deploy.
export const PROVIDERS = [
  { id: "workers-ai", kind: "workers-ai", free: true,
    models: [{ id: "@cf/meta/llama-3.3-70b-instruct-fp8-fast", window: 24000, strengths: ["lookup", "writing"] }] },
  { id: "groq", kind: "openai", baseUrl: "https://api.groq.com/openai/v1", keyEnv: "GROQ_API_KEY", free: true,
    models: [{ id: "llama-3.3-70b-versatile", window: 128000, strengths: ["lookup", "writing", "judgment"] }] },
  { id: "gemini", kind: "openai", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai", keyEnv: "GEMINI_API_KEY", free: true,
    models: [{ id: "gemini-2.5-flash", window: 1000000, strengths: ["judgment", "writing", "arabic", "lookup"] }] },
];
