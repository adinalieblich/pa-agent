import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { requestMotionPermission } from "../lib/useShakeUndo";
import ReviewBell from "../components/ReviewBell.jsx";
import TaskRow from "../components/TaskRow.jsx";
import Toast from "../components/Toast.jsx";

/**
 * "All active" screen — matches docs/pwa_full_mockup.html "All" pane.
 *
 * Sections:
 *   1. Page header — date label, title, "X active · sorted by priority"
 *   2. One section per non-empty priority group: Urgent / Important /
 *      Normal / Someday. Each section header shows the count.
 *   3. Task rows — checkbox, title (with optional sub-meta below), tag
 *      column showing priority + relative due / project hint.
 *
 * Data: /api/tasks/all returns Active Type=task rows pre-sorted by
 * priority then due. We group client-side.
 *
 * Props:
 *   - context?: "work" | "personal" — when set, filters the list to
 *     rows of that context and changes the header copy. Used by
 *     /browse/work to give that route a dedicated identity.
 *   - title, dateLabel, subtitlePrefix — optional header overrides.
 */

const ORDER = ["Urgent", "Important", "Normal", "Someday"];

export default function All({
  context = null,
  title = null,
  dateLabel = null,
  subtitlePrefix = null,
}) {
  const nav = useNavigate();
  const location = useLocation();
  // Sub-screens entered via Browse → Work / Upcoming need a back affordance.
  const isBrowseSub = location.pathname.startsWith("/browse/");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState(null);

  const reload = async () => {
    setError("");
    try {
      const data = await api("/api/tasks/all");
      const all = data.items || [];
      const filtered = context ? all.filter((r) => r.context === context) : all;
      setRows(filtered);
    } catch (e) {
      setError(e.message || "couldn't load");
      setRows([]);
    }
  };

  const handleDone = async (row) => {
    const prev = rows;
    setRows((rs) => (rs || []).filter((r) => r.id !== row.id));

    const undo = async () => {
      setRows(prev);
      try {
        await api(`/api/task/${row.id}/restore`, { method: "POST" });
        setToast({ message: "Restored", variant: "muted" });
      } catch (e) {
        setToast({ message: `Couldn't undo: ${e.message}`, variant: "error" });
      }
    };

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
      setRows(prev);
      setToast({ message: `Couldn't mark done: ${e.message}`, variant: "error" });
    }
  };

  useEffect(() => {
    reload();
    const onVis = () => { if (!document.hidden) reload(); };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  const grouped = useMemo(() => {
    if (!rows) return null;
    const buckets = { Urgent: [], Important: [], Normal: [], Someday: [] };
    for (const r of rows) {
      const key = ORDER.includes(r.priority) ? r.priority : "Normal";
      buckets[key].push(r);
    }
    return buckets;
  }, [rows]);

  const loading = rows === null;
  const total = rows?.length ?? 0;

  return (
    <>
      <header className="page-header">
        {isBrowseSub && (
          <button
            type="button"
            className="row-button page-back"
            onClick={() => nav("/browse")}
          >
            ‹ Browse
          </button>
        )}
        <div className="page-date">{dateLabel || "All active"}</div>
        <h1 className="page-title">
          {title || (
            <>
              <em>everything</em> to do
            </>
          )}
        </h1>
        <p className="page-subtitle">
          {loading
            ? "loading…"
            : `${total} ${subtitlePrefix || "active"} · sorted by priority`}
        </p>
        <ReviewBell />
      </header>

      {loading && (
        <>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </>
      )}

      {!loading && total === 0 && !error && (
        <div className="empty">
          <div className="empty-art">✿</div>
          <p className="empty-msg">
            nothing active. capture a thought or take the win.
          </p>
        </div>
      )}

      {!loading && grouped &&
        ORDER.map((label) =>
          grouped[label].length === 0 ? null : (
            <PriorityGroup
              key={label}
              label={label}
              items={grouped[label]}
              first={label === ORDER.find((l) => grouped[l].length > 0)}
              onOpen={(id) => nav(`/task/${id}`)}
              onDone={handleDone}
            />
          )
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

function PriorityGroup({ label, items, first, onOpen, onDone }) {
  return (
    <>
      <div
        className="section-head"
        style={first ? undefined : { marginTop: 12 }}
      >
        <div className="section-title">{label}</div>
        <div className="section-count">{items.length}</div>
      </div>
      {items.map((row) => (
        <TaskRow
          key={row.id}
          row={row}
          onOpen={() => onOpen(row.id)}
          onDone={onDone}
        />
      ))}
    </>
  );
}
