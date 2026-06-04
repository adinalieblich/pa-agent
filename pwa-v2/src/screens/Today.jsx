import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { fetchWorkMode } from "../lib/workMode";
import { tap } from "../lib/tap";
import { useSwipeDone } from "../lib/useSwipeDone";
import { requestMotionPermission } from "../lib/useShakeUndo";
import ReviewBell from "../components/ReviewBell.jsx";
import TaskRow from "../components/TaskRow.jsx";
import NudgeCard from "../components/NudgeCard.jsx";
import NotificationsBanner from "../components/NotificationsBanner.jsx";
import WorkModePill from "../components/WorkModePill.jsx";
import Toast from "../components/Toast.jsx";
import {
  greetingEmoji,
  greetingPrefix,
  greetingWordPolished,
  pageDateLabel,
} from "../lib/format";

/**
 * Today screen — matches docs/pwa_full_mockup.html "Today" pane exactly.
 *
 * Sections (top → bottom):
 *   1. Page header (date / greeting / subtitle)
 *   2. Stats row (urgent / done / active)
 *   3. "Your focus" — gradient card with first-up badge + first-step hint
 *   4. "Quick wins" — task list, focus task excluded, max 5 shown
 *
 * Data source: existing FastAPI endpoints — /api/today (active rows due
 * today or earlier + undated-urgent) and /api/wins (rows marked Done
 * today, used only for the wins-today count + the "X done already"
 * subtitle).
 *
 * Focus selection (no server change needed):
 *   - The first Urgent row, OR
 *   - The most-overdue row, OR
 *   - The first row in the today list.
 */

const PRIORITY_ORDER = { Urgent: 0, Important: 1, Normal: 2, Someday: 3 };

function chooseFocus(todayRows) {
  if (!todayRows?.length) return null;
  return [...todayRows].sort((a, b) => {
    const pa = PRIORITY_ORDER[a.priority] ?? 9;
    const pb = PRIORITY_ORDER[b.priority] ?? 9;
    if (pa !== pb) return pa - pb;
    const da = a.due_date || "9999-12-31";
    const db = b.due_date || "9999-12-31";
    return da.localeCompare(db);
  })[0];
}

export default function Today() {
  const nav = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [todayRows, setTodayRows] = useState(null); // null = loading
  const [winsRows, setWinsRows] = useState(null);
  const [upcomingRows, setUpcomingRows] = useState(null);
  const [workModeActive, setWorkModeActive] = useState(true); // default-permissive
  const [error, setError] = useState("");
  const [toast, setToast] = useState(null);
  const [upcomingOpen, setUpcomingOpen] = useState(false);

  const reload = async () => {
    setError("");
    try {
      const [today, wins, upcoming, wm] = await Promise.all([
        api("/api/today"),
        api("/api/wins"),
        api("/api/upcoming?days=7"),
        fetchWorkMode().catch(() => null),
      ]);
      setTodayRows(today.items || []);
      setWinsRows(wins.items || []);
      setUpcomingRows(upcoming.items || []);
      // If we can't read work-mode state, default to "active" (show everything)
      setWorkModeActive(wm ? !!wm.active : true);
    } catch (e) {
      setError(e.message || "couldn't load");
      setTodayRows([]);
      setWinsRows([]);
      setUpcomingRows([]);
    }
  };

  // Optimistic done with undo support.
  // Pulls in shake-to-undo (asks for motion permission once on first done);
  // toast also has a tap-to-undo button as a fallback if shake is unavailable.
  const handleDone = async (row) => {
    const prev = todayRows;
    const prevWins = winsRows;
    setTodayRows((rs) => (rs || []).filter((r) => r.id !== row.id));
    setWinsRows((rs) => [row, ...(rs || [])]);

    const undo = async () => {
      setTodayRows(prev);
      setWinsRows(prevWins);
      try {
        await api(`/api/task/${row.id}/restore`, { method: "POST" });
        setToast({ message: "Restored", variant: "muted" });
      } catch (e) {
        setToast({ message: `Couldn't undo: ${e.message}`, variant: "error" });
      }
    };

    // Try to enable shake-to-undo on first done (no-op after first call).
    requestMotionPermission();

    setToast({
      message: `Done · ${row.title.slice(0, 36)}`,
      variant: "success",
      actionLabel: "undo",
      onAction: undo,
    });

    try {
      await api(`/api/task/${row.id}/done`, { method: "POST" });
    } catch (e) {
      setTodayRows(prev);
      setWinsRows(prevWins);
      setToast({ message: `Couldn't mark done: ${e.message}`, variant: "error" });
    }
  };

  useEffect(() => {
    reload();
    // Refresh whenever the tab becomes visible again (user returns to app)
    const onVis = () => { if (!document.hidden) reload(); };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // Web Push notification action handler. A tap on an action button lands
  // the user here with ?action=... and optional id/days. Run the matching
  // API call, surface a toast, then strip the params from the URL so a
  // refresh doesn't re-fire the action.
  useEffect(() => {
    const action = searchParams.get("action");
    if (!action) return;
    const id = searchParams.get("id");
    const days = Number(searchParams.get("days") || "1");
    let cancelled = false;
    (async () => {
      try {
        if (action === "done" && id) {
          await api(`/api/task/${id}/done`, { method: "POST" });
          if (!cancelled) setToast({ message: "Done", variant: "success" });
        } else if (action === "snooze" && id) {
          await api(`/api/task/${id}/snooze?days=${days}`, { method: "POST" });
          if (!cancelled) {
            setToast({ message: `Snoozed +${days}d`, variant: "success" });
          }
        } else if (action === "pause-work") {
          // From the Mon 9am "Pause today" action button.
          await api("/api/work-mode/override?action=pause-today", {
            method: "POST",
          });
          if (!cancelled) {
            setToast({ message: "Work mode paused for today", variant: "success" });
          }
        }
        if (!cancelled) await reload();
      } catch (e) {
        if (!cancelled) {
          setToast({
            message: `Couldn't apply: ${e.message}`,
            variant: "error",
          });
        }
      } finally {
        // Drop the params so a refresh doesn't replay the action
        if (!cancelled) {
          const next = new URLSearchParams(searchParams);
          next.delete("action");
          next.delete("id");
          next.delete("days");
          setSearchParams(next, { replace: true });
        }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.toString()]);

  // Work-mode filter: when work mode is OFF, hide work-context rows from
  // today + coming up. Personal rows always show. This is the visual side
  // of the work-mode contract the nag worker already enforces.
  const visibleToday = useMemo(() => {
    if (!todayRows) return null;
    if (workModeActive) return todayRows;
    return todayRows.filter((r) => r.context !== "work");
  }, [todayRows, workModeActive]);
  const visibleUpcoming = useMemo(() => {
    if (!upcomingRows) return null;
    if (workModeActive) return upcomingRows;
    return upcomingRows.filter((r) => r.context !== "work");
  }, [upcomingRows, workModeActive]);
  // How many work rows are being hidden — surface this so the user knows
  // they aren't seeing everything.
  const hiddenWorkCount = useMemo(() => {
    if (workModeActive) return 0;
    const t = (todayRows || []).filter((r) => r.context === "work").length;
    const u = (upcomingRows || []).filter((r) => r.context === "work").length;
    return t + u;
  }, [todayRows, upcomingRows, workModeActive]);

  const focus = useMemo(() => chooseFocus(visibleToday), [visibleToday]);

  // Stats — derived client-side from the (filtered) payloads.
  const stats = useMemo(() => {
    const t = visibleToday || [];
    const w = winsRows || [];
    const urgent = t.filter((r) => r.priority === "Urgent").length;
    return { urgent, done: w.length, active: t.length };
  }, [visibleToday, winsRows]);

  // Auto-expand Coming Up when there's nothing urgent today — the user
  // benefits from seeing what's next instead of just an empty Today.
  useEffect(() => {
    if (stats.urgent === 0 && (upcomingRows?.length || 0) > 0) {
      setUpcomingOpen(true);
    }
  }, [stats.urgent, upcomingRows]);

  // Quick wins = everything in `visibleToday` except the focus card. Capped at 5.
  const quickWins = useMemo(() => {
    if (!visibleToday || !focus) return visibleToday || [];
    return visibleToday.filter((r) => r.id !== focus.id).slice(0, 5);
  }, [visibleToday, focus]);

  const loading = todayRows === null;

  return (
    <>
      <header className="page-header">
        <div className="page-date">{pageDateLabel()}</div>
        <h1 className="page-title">
          {greetingPrefix()} <em>{greetingWordPolished()}</em>{" "}
          <span className="greeting-emoji" aria-hidden="true">
            {greetingEmoji()}
          </span>
        </h1>
        <ReviewBell />
      </header>

      <WorkModePill />
      <NotificationsBanner />
      <NudgeCard />

      <div className="stats">
        <div className="stat">
          <div className="stat-num ruby">{stats.urgent}</div>
          <div className="stat-label">urgent</div>
        </div>
        <div className="stat">
          <div className="stat-num emerald">{stats.done}</div>
          <div className="stat-label">done</div>
        </div>
        <div className="stat">
          <div className="stat-num">{stats.active}</div>
          <div className="stat-label">active</div>
        </div>
      </div>

      {/* Your focus */}
      <div className="section-head">
        <div className="section-title">🎯 Your focus</div>
      </div>
      {loading && <div className="skeleton" style={{ height: 86 }} />}
      {!loading && focus && (
        <FocusCard
          row={focus}
          onOpen={() => nav(`/task/${focus.id}`)}
          onDone={handleDone}
        />
      )}
      {!loading && !focus && !error && (
        <div className="empty">
          <div className="empty-art">✿</div>
          <p className="empty-msg">
            nothing to do, nothing to worry about. capture a thought with the
            action button or rest.
          </p>
        </div>
      )}

      {/* Quick wins */}
      {!loading && quickWins.length > 0 && (
        <>
          <div className="section-head" style={{ marginTop: 14 }}>
            <div className="section-title">⚡ Quick wins</div>
            <div className="section-count">
              {quickWins.length} {quickWins.length === 1 ? "thing" : "things"}
            </div>
          </div>
          {quickWins.map((row) => (
            <TaskRow
              key={row.id}
              row={row}
              onOpen={() => nav(`/task/${row.id}`)}
              onDone={handleDone}
            />
          ))}
        </>
      )}

      {/* Coming up — collapsed by default unless nothing's urgent today */}
      {!loading && (visibleUpcoming?.length || 0) > 0 && (
        <>
          <button
            type="button"
            className="section-head section-head-toggle"
            onClick={() => setUpcomingOpen((v) => !v)}
            aria-expanded={upcomingOpen}
          >
            <div className="section-title">📅 Coming up this week</div>
            <div className="section-count">
              {visibleUpcoming.length}
              <span className="section-chevron" aria-hidden="true">
                {upcomingOpen ? "˅" : "›"}
              </span>
            </div>
          </button>
          {upcomingOpen && visibleUpcoming.map((row) => (
            <TaskRow
              key={row.id}
              row={row}
              onOpen={() => nav(`/task/${row.id}`)}
              onDone={handleDone}
            />
          ))}
        </>
      )}

      {/* When work mode is OFF, surface the count of hidden work rows so
          the user knows there's more behind the curtain. Tapping takes
          them to Browse → Work where they can start work mode now. */}
      {!loading && hiddenWorkCount > 0 && (
        <button
          type="button"
          className="hidden-work-hint"
          onClick={() => nav("/browse")}
        >
          💼 {hiddenWorkCount} work {hiddenWorkCount === 1 ? "item" : "items"} hidden ·
          <span className="hidden-work-hint-link"> tap to enter work mode</span>
        </button>
      )}

      {loading && (
        <>
          <div className="section-head" style={{ marginTop: 14 }}>
            <div className="section-title">⚡ Quick wins</div>
          </div>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </>
      )}

      {error && (
        <p className="empty-msg" style={{ padding: "0 22px", marginTop: 12 }}>
          {error}
        </p>
      )}

      <Toast
        message={toast?.message}
        variant={toast?.variant}
        actionLabel={toast?.actionLabel}
        onAction={toast?.onAction}
        onDismiss={() => setToast(null)}
      />
    </>
  );
}

/* --- Sub-components --------------------------------------------------- */

/* eslint-disable react-hooks/rules-of-hooks */
function FocusCard({ row, onOpen, onDone }) {
  // Wire the focus card up to the same swipe + tap-check pattern as a
  // task row, so the user can tick it off without opening the detail screen.
  const swipe = useSwipeDone(() => onDone && onDone(row));
  const tappable = onOpen ? tap(onOpen, "focus-card") : { className: "focus-card" };

  const onCheckActivate = (e) => {
    e.stopPropagation();
    e.preventDefault();
    swipe.commit();
  };

  return (
    <div className="task-row-wrap focus-row-wrap">
      <div
        className="task-row-swipe-bg"
        style={{ opacity: swipe.swipeProgress }}
        aria-hidden="true"
      >
        <span className="task-row-swipe-icon">✓</span>
        <span className="task-row-swipe-label">done</span>
      </div>
      <div {...tappable} style={swipe.style} {...swipe.handlers}>
        <div className="focus-card-head">
          <span className="focus-badge">
            {row.context === "work" ? "💼 first up" : "first up"}
          </span>
          <span
            className="focus-check"
            aria-label="Mark done"
            role="button"
            tabIndex={0}
            onClick={onCheckActivate}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onCheckActivate(e);
            }}
          />
        </div>
        <div className="focus-title">{row.title}</div>
        {row.first_step && (
          <div className="focus-step">{row.first_step}</div>
        )}
      </div>
    </div>
  );
}
