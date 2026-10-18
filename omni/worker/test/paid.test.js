import { test } from "node:test";
import assert from "node:assert/strict";
import { handle, resetBreakers } from "../src/index.js";
import { PROVIDERS } from "../src/providers.js";
import { MemoryStore } from "../src/threads.js";

test("paid provider opt-in is off by default and static caps never authorize charges", async () => {
  const provider = PROVIDERS.find(p => p.id === "groq");
  const original = provider.free;
  provider.free = false;
  try {
    for (const enabled of [undefined, "0", "1"]) {
      resetBreakers(); let calls=0;
      const env={DEVICE_TOKEN:"test-device",GROQ_API_KEY:"test-key",NEVA_CAP_GROQ:"100",store:new MemoryStore(),
        ...(enabled === undefined ? {} : {NEVA_ENABLE_PAID:enabled}),
        fetchImpl:async () => { calls++; return {ok:true,json:async()=>({choices:[{message:{content:"mock"}}]})}; }};
      const request=new Request("https://omni.example.com/chat",{method:"POST",headers:{Authorization:"Bearer test-device","Content-Type":"application/json"},body:JSON.stringify({thread_id:"paid",message:"hello"})});
      const response=await handle(request,env);
      assert.equal(response.status,502);
      assert.match((await response.json()).failures[0].error,/paid.*(disabled|unavailable)/);
      assert.equal(calls,0);
      assert.equal((await env.store.getThread("paid")).messages.length,1);
    }
  } finally { provider.free=original; }
});
