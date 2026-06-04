/**
 * Dashboard + nudge fetchers — wrap the /api/dashboard and /api/nudge
 * endpoints with thin localStorage caching so changing tabs doesn't refetch.
 */

import { api } from "./api";

const D_CACHE_KEY = "pa.dashboard";
const D_CACHE_MS = 60 * 1000; // 1 minute
const N_CACHE_KEY = "pa.nudge";
const N_CACHE_HOURS = 6;       // nudge re-fetches at most every 6 hours
const N_CACHE_MS = N_CACHE_HOURS * 60 * 60 * 1000;

function readCache(key, maxAgeMs) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (!obj.fetched_at || Date.now() - obj.fetched_at > maxAgeMs) return null;
    return obj.data;
  } catch {
    return null;
  }
}

function writeCache(key, data) {
  try {
    localStorage.setItem(key, JSON.stringify({ data, fetched_at: Date.now() }));
  } catch {/* ignore quota */}
}

/** GET /api/dashboard with 1-minute cache. Returns null on failure. */
export async function getDashboard({ force = false } = {}) {
  if (!force) {
    const cached = readCache(D_CACHE_KEY, D_CACHE_MS);
    if (cached) return cached;
  }
  try {
    const data = await api("/api/dashboard");
    writeCache(D_CACHE_KEY, data);
    return data;
  } catch {
    return null;
  }
}

/** GET /api/nudge — 6-hour cache so we don't blow Anthropic tokens. */
export async function getNudge({ force = false } = {}) {
  if (!force) {
    const cached = readCache(N_CACHE_KEY, N_CACHE_MS);
    if (cached) return cached;
  }
  try {
    const data = await api("/api/nudge");
    writeCache(N_CACHE_KEY, data);
    return data;
  } catch {
    return null;
  }
}
