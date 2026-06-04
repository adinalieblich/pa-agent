import { useEffect, useState } from "react";
import { getNudge } from "../lib/dashboard";

/**
 * "Claude's take" — a one-line nudge generated from the user's live data.
 *
 * Shown only on the Today screen, directly under the greeting.
 *
 *   ✦ CLAUDE'S TAKE
 *   3 urgent items, only 1 quick win — start with replying to the
 *   landlord, then pay the dentist before Friday.
 *
 * Cached for 6 hours via lib/dashboard.js. Tap the card to force-refresh.
 */
export default function NudgeCard() {
  const [text, setText] = useState(null);   // null = loading
  const [busy, setBusy] = useState(false);

  const load = async (force = false) => {
    setBusy(true);
    try {
      const r = await getNudge({ force });
      setText(r?.text ?? "");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(false); }, []);

  // Hide the card entirely if the endpoint failed twice and we have nothing
  // to show — better than rendering an empty box.
  if (text === "") return null;

  return (
    <button
      type="button"
      className="nudge-card"
      onClick={() => load(true)}
      disabled={busy}
      aria-label="Tap to refresh"
    >
      <div className="nudge-label">
        <span>✦</span> Claude's take
      </div>
      <div className="nudge-line">
        {text ?? "thinking…"}
      </div>
    </button>
  );
}
