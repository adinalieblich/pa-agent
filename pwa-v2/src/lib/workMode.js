import { api } from "./api";

/**
 * Work-mode API helpers.
 *
 *  - fetchWorkMode()       → GET /api/work-mode → current state + schedule
 *  - applyOverride(action) → POST /api/work-mode/override → flip mode
 *
 * Override actions map 1:1 to the canned helpers in src/work_mode.py:
 *  - "pause-today" : force OFF until end of day
 *  - "start-now"   : force ON for N hours (default 4)
 *  - "end-early"   : force OFF until tomorrow's work-start
 *  - "clear"       : drop any override, return to schedule
 */

export async function fetchWorkMode() {
  return api("/api/work-mode");
}

export async function applyOverride(action, opts = {}) {
  const params = new URLSearchParams({ action });
  if (opts.hours != null) params.set("hours", String(opts.hours));
  if (opts.until) params.set("until", opts.until);
  return api(`/api/work-mode/override?${params.toString()}`, { method: "POST" });
}

/**
 * Convert the raw API response into a UI-friendly state machine summary.
 * Returns one of: "schedule-on" | "schedule-off" | "override-on" | "override-off".
 */
export function summariseState(data) {
  if (!data) return null;
  const onOff = data.active ? "on" : "off";
  const src = data.source === "override" ? "override" : "schedule";
  return `${src}-${onOff}`;
}

/** Human-friendly "ends at" label for an active override. */
export function overrideEndsLabel(data) {
  if (!data || data.source !== "override" || !data.override) return null;
  try {
    const until = new Date(data.override.until);
    const now = new Date();
    const diffMin = Math.round((until - now) / 60000);
    if (diffMin <= 0) return null;
    if (diffMin < 60) return `${diffMin}m`;
    const hours = Math.floor(diffMin / 60);
    if (hours < 24) {
      const mins = diffMin % 60;
      return mins ? `${hours}h ${mins}m` : `${hours}h`;
    }
    const days = Math.floor(hours / 24);
    return `${days}d`;
  } catch {
    return null;
  }
}
