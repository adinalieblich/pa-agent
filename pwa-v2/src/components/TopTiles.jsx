import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getDashboard } from "../lib/dashboard";
import { getWeather } from "../lib/weather";

/**
 * Top tile strip — shown above every screen's content.
 *
 *   ☀️ 18°   💰 $487   🔥 5d   ⚠ 3
 *  clear    due wk    streak  review
 *
 * Data:
 *   - Weather: Open-Meteo (free, no key), cached 15 min.
 *   - Money / streak / review: /api/dashboard, cached 60s.
 *
 * Interactions:
 *   - Tap weather → no-op for v1 (could expand to forecast later)
 *   - Tap money   → /bills
 *   - Tap streak  → /wins
 *   - Tap review  → /review
 */
export default function TopTiles() {
  const nav = useNavigate();
  const [dash, setDash] = useState(null);
  const [weather, setWeather] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getDashboard().then((d) => { if (!cancelled) setDash(d); });
    getWeather().then((w) => { if (!cancelled) setWeather(w); });
    return () => { cancelled = true; };
  }, []);

  const money = dash?.money_due_week;
  const streak = dash?.streak_days;
  const review = dash?.review_count;

  return (
    <div className="top-tiles">
      <button
        type="button"
        className="tile weather"
        aria-label="Weather"
      >
        <span className="tile-icon">{weather?.icon ?? "·"}</span>
        <span className="tile-val">
          {weather?.temp_c != null ? `${weather.temp_c}°` : "—"}
        </span>
        <span className="tile-label">{weather?.label ?? "—"}</span>
      </button>

      <button
        type="button"
        className="tile money"
        onClick={() => nav("/bills")}
        aria-label="Bills due this week"
      >
        <span className="tile-icon">💰</span>
        <span className="tile-val">
          {money != null ? `$${formatMoney(money)}` : "—"}
        </span>
        <span className="tile-label">due wk</span>
      </button>

      <button
        type="button"
        className="tile streak"
        onClick={() => nav("/wins")}
        aria-label="Current streak"
      >
        <span className="tile-icon">🔥</span>
        <span className="tile-val">{streak != null ? `${streak}d` : "—"}</span>
        <span className="tile-label">streak</span>
      </button>

      <button
        type="button"
        className="tile review"
        onClick={() => nav("/review")}
        aria-label="Review queue"
      >
        <span className="tile-icon">⚠</span>
        <span className="tile-val">{review != null ? review : "—"}</span>
        <span className="tile-label">review</span>
      </button>
    </div>
  );
}

function formatMoney(n) {
  if (n >= 10000) return Math.round(n / 1000) + "k";
  return Math.round(n).toLocaleString();
}
