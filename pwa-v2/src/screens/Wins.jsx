import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { tap } from "../lib/tap";

/**
 * Wins screen — matches docs/pwa_full_mockup.html "Wins" pane.
 *
 * Layout:
 *   1. Page header — "Done" / "your wins" / "X this week · Y this month"
 *   2. Day-grouped lists. Each day card has an italic Fraunces label
 *      ("today" / "yesterday · Sunday" / weekday names) and bulleted win
 *      rows (small emerald dot + title).
 *
 * Data: /api/wins/recent?days=30 returns Done rows in the last 30 days
 * so both the week + month subtitle counters work without a second
 * round-trip. The visible list shows the last 7 days; the "this month"
 * count uses the full payload.
 */

const WEEKDAYS_LONG = [
  "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
];
const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function dayKey(iso) {
  // Notion's done_at is an ISO timestamp; bucket by *local* calendar day.
  const d = new Date(iso);
  d.setHours(0, 0, 0, 0);
  return d.toISOString().slice(0, 10);
}

function dayLabel(yyyyMmDd) {
  const d = new Date(yyyyMmDd + "T00:00:00");
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - d) / 86400000);
  if (diff === 0) return "today";
  if (diff === 1) return "yesterday · " + WEEKDAYS_LONG[d.getDay()].toLowerCase();
  if (diff < 7) return WEEKDAYS_LONG[d.getDay()].toLowerCase();
  return `${WEEKDAYS_LONG[d.getDay()].toLowerCase()} · ${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}

export default function Wins() {
  const nav = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  const reload = async () => {
    setError("");
    try {
      const data = await api("/api/wins/recent?days=30");
      setRows(data.items || []);
    } catch (e) {
      setError(e.message || "couldn't load");
      setRows([]);
    }
  };

  useEffect(() => {
    reload();
    const onVis = () => { if (!document.hidden) reload(); };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  const loading = rows === null;

  // Group + sort days descending.
  const days = useMemo(() => {
    if (!rows) return [];
    const buckets = new Map();
    for (const r of rows) {
      if (!r.done_at) continue;
      const k = dayKey(r.done_at);
      if (!buckets.has(k)) buckets.set(k, []);
      buckets.get(k).push(r);
    }
    return [...buckets.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([k, items]) => ({ key: k, items }));
  }, [rows]);

  // Headline counts: this-week = last 7 calendar days; this-month = 30.
  const counts = useMemo(() => {
    if (!rows) return { week: 0, month: 0 };
    const today = new Date(); today.setHours(0, 0, 0, 0);
    let week = 0;
    for (const r of rows) {
      if (!r.done_at) continue;
      const d = new Date(r.done_at);
      d.setHours(0, 0, 0, 0);
      const diffDays = Math.round((today - d) / 86400000);
      if (diffDays >= 0 && diffDays < 7) week++;
    }
    return { week, month: rows.length };
  }, [rows]);

  return (
    <>
      <header className="page-header">
        <div className="page-date">Done</div>
        <h1 className="page-title">
          your <em>wins</em>
        </h1>
        <p className="page-subtitle">
          {loading
            ? "loading…"
            : `${counts.week} this week · ${counts.month} this month`}
        </p>
      </header>

      {loading && (
        <>
          <div className="skeleton" />
          <div className="skeleton" />
        </>
      )}

      {!loading && days.length === 0 && !error && (
        <div className="empty">
          <div className="empty-art">✿</div>
          <p className="empty-msg">
            no wins logged yet. tick one off and it'll appear here.
          </p>
        </div>
      )}

      {!loading && days.map((day) => (
        <div className="wins-day" key={day.key}>
          <div className="wins-day-label">{dayLabel(day.key)}</div>
          <div className="wins-day-list">
            {day.items.map((row) => (
              <div
                key={row.id}
                {...tap(() => nav(`/task/${row.id}`), "win")}
              >
                <span className="win-dot" aria-hidden="true" />
                <span>{row.title}</span>
              </div>
            ))}
          </div>
        </div>
      ))}

      {error && (
        <p className="empty-msg" style={{ padding: "0 22px", marginTop: 12 }}>
          {error}
        </p>
      )}
    </>
  );
}
