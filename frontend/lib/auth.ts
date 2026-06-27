/**
 * Stateless password-gate auth for the LLM-Quant monitoring panel.
 *
 * A single shared password (env APP_PASSWORD) gates the whole app. On success we
 * set an httpOnly, signed session cookie. The cookie is a stateless HMAC token
 * `exp.signature` so it cannot be forged without AUTH_SECRET and expires on its own.
 *
 * Uses the Web Crypto API (crypto.subtle) so the SAME code runs in Edge middleware
 * and in Node route handlers — no Node-only `crypto` import.
 */

export const SESSION_COOKIE = "ql_session";
const DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 7; // 7 days

const encoder = new TextEncoder();

function base64UrlEncode(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  // btoa is available in both Edge and Node 18+ runtimes
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function importKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

async function hmac(secret: string, payload: string): Promise<string> {
  const key = await importKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return base64UrlEncode(sig);
}

/** Constant-time string comparison to avoid timing leaks. */
export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** Verify a submitted password against APP_PASSWORD (constant-time). */
export function checkPassword(submitted: string): boolean {
  const expected = process.env.APP_PASSWORD;
  if (!expected) return false; // not configured -> deny
  return timingSafeEqual(submitted, expected);
}

/** Create a signed session token valid for `ttlSeconds`. */
export async function createSessionToken(ttlSeconds = DEFAULT_TTL_SECONDS): Promise<string> {
  const secret = process.env.AUTH_SECRET;
  if (!secret) throw new Error("AUTH_SECRET is not set");
  const exp = Date.now() + ttlSeconds * 1000;
  const payload = String(exp);
  const sig = await hmac(secret, payload);
  return `${payload}.${sig}`;
}

/** Verify a session token's signature and expiry. Returns true if valid. */
export async function verifySessionToken(token: string | undefined | null): Promise<boolean> {
  if (!token) return false;
  const secret = process.env.AUTH_SECRET;
  if (!secret) return false;
  const dot = token.indexOf(".");
  if (dot <= 0) return false;
  const payload = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const exp = Number(payload);
  if (!Number.isFinite(exp) || Date.now() > exp) return false;
  const expected = await hmac(secret, payload);
  return timingSafeEqual(expected, sig);
}

/** Whether auth is configured at all (both env vars present). */
export function authConfigured(): boolean {
  return Boolean(process.env.APP_PASSWORD && process.env.AUTH_SECRET);
}

export const SESSION_TTL_SECONDS = DEFAULT_TTL_SECONDS;
