import { useEffect, useState } from "react";
import {
  applyOverride,
  fetchWorkMode,
  overrideEndsLabel,
  summariseState,
} from "../lib/workMode";

/**
 * Compact pill that surfaces work-mode state on Today and offers one-tap
 * override actions. PROJECT_STATUS D7:
 *
 *   - When ON (visible state): tap the pill to pause work mode for today.
 *   - When OFF: the "Start work mode now" surface lives on Browse → Work
 *     (this component shows the status but no action).
 *
 * Visual states:
 *
 *   schedule-on   → 💼 work mode on · M–F 9–5      [pause today]
 *   schedule-off  → 💤 work mode off · resumes Mon 9
 *   override-on   → 💼 work mode on · ends in 3h   [end early]
 *   override-off  → 💤 work mode paused · resumes 9am  [resume]
 *
 * No layout space when API errors out — silent failure beats noisy banner.
 */
export default function WorkModePill() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reload = async () => {
    try {
      const fresh = await fetchWorkMode();
      setData(fresh);
      setError("");
    } catch (e) {
      setError(e.message || "");
    }
  };

  useEffect(() => {
    reload();
    // Re-check when the tab becomes visible — the user might've been away
    // long enough for work-hours to have rolled over.
    const onVis = () => { if (!document.hidden) reload(); };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  if (!data || error) return null;

  const state = summariseState(data);
  const endsIn = overrideEndsLabel(data);

  // Click handler: maps state → override action
  const onTap = async () => {
    if (busy) return;
    setBusy(true);
    try {
      let action = null;
      if (state === "schedule-on") action = "pause-today";
      else if (state === "override-on") action = "end-early";
      else if (state === "override-off") action = "clear";
      // schedule-off has no inline action (user goes to Browse → Work)
      if (!action) return;
      await applyOverride(action);
      await reload();
    } catch (e) {
      setError(e.message || "couldn't update");
    } finally {
      setBusy(false);
    }
  };

  const { label, action, icon, on } = renderText(state, endsIn);
  if (!label) return null;

  return (
    <button
      type="button"
      className={`workmode-pill ${on ? "workmode-pill-on" : "workmode-pill-off"} ${busy ? "is-busy" : ""}`}
      onClick={onTap}
      disabled={busy}
      aria-label={`Work mode ${on ? "on" : "off"} — tap for ${action || "no action"}`}
    >
      <span className="workmode-pill-icon" aria-hidden="true">{icon}</span>
      <span className="workmode-pill-label">{label}</span>
      {action && <span className="workmode-pill-action">{action}</span>}
    </button>
  );
}

function renderText(state, endsIn) {
  switch (state) {
    case "schedule-on":
      return { label: "work mode on · M–F 9–5", action: "pause today", icon: "💼", on: true };
    case "schedule-off":
      // No inline action — Browse → Work has the "Start now" entry point
      return { label: "work mode off · M–F 9–5", action: null, icon: "💤", on: false };
    case "override-on":
      return {
        label: endsIn ? `work mode on · ends in ${endsIn}` : "work mode on · override",
        action: "end early",
        icon: "💼",
        on: true,
      };
    case "override-off":
      return {
        label: endsIn ? `work mode paused · resumes in ${endsIn}` : "work mode paused",
        action: "resume",
        icon: "💤",
        on: false,
      };
    default:
      return { label: null };
  }
}
