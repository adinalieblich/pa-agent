/**
 * Thin fetch wrapper around the FastAPI /api/* endpoints.
 *
 * Auth: every request carries X-PA-Token from localStorage. If the server
 * returns 401, we clear the token and reload — which kicks the user back
 * to the token-entry screen.
 *
 * Same-origin: the PWA is served from the same FastAPI process that hosts
 * /api/*, so no CORS dance, no base URL config. In dev (`vite dev`), the
 * vite proxy in vite.config.js forwards /api to localhost:8000.
 */

const TOKEN_KEY = "pa.token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * @param {string} path  - server path beginning with `/`
 * @param {RequestInit} [opts]
 */
export async function api(path, opts = {}) {
  const token = getToken();
  if (!token) {
    const err = new Error("no_token");
    err.code = "NO_TOKEN";
    throw err;
  }
  const headers = {
    "X-PA-Token": token,
    "Content-Type": "application/json",
    ...(opts.headers || {}),
  };
  const resp = await fetch(path, { ...opts, headers });
  if (resp.status === 401) {
    clearToken();
    const err = new Error("token_rejected");
    err.code = "AUTH";
    throw err;
  }
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    const err = new Error(`HTTP ${resp.status}: ${body.slice(0, 120)}`);
    err.code = "HTTP";
    throw err;
  }
  return resp.json();
}

/** Verify a candidate token by hitting /api/today. Returns boolean. */
export async function verifyToken(candidate) {
  const r = await fetch("/api/today", { headers: { "X-PA-Token": candidate } });
  return r.ok;
}
