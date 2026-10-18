export const SIGN_IN = "send the device token matching DEVICE_TOKEN";

// Access headers are untrusted until JWT validation is implemented.

// Constant-time over the characters when the lengths match, so timing does not reveal how
// many leading characters are right. A length mismatch returns early, so timing can still
// reveal the token's length; use a long random token, whose length is no secret worth keeping.
function sameToken(given, expected) {
  if (typeof given !== "string" || typeof expected !== "string") return false;
  if (given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

export function authorize(request, env) {
  const header = request.headers.get("Authorization") ?? "";
  const bearer = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (env.DEVICE_TOKEN && sameToken(bearer, env.DEVICE_TOKEN)) {
    return { ok: true, user: "device", via: "device-token" };
  }

  return { ok: false, status: 401, error: SIGN_IN };
}
