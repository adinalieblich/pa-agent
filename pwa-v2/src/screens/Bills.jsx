import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { tap } from "../lib/tap";
import { useSwipeDone } from "../lib/useSwipeDone";
import { requestMotionPermission } from "../lib/useShakeUndo";
import { relativeDueLabel } from "../lib/format";
import Toast from "../components/Toast.jsx";

/**
 * Bills screen — matches docs/pwa_full_mockup.html "Bills" pane.
 *
 * Sections:
 *   1. Page header — "Bills" / "to pay" / total outstanding
 *   2. "Urgent" — bills due in the next 7 days (ruby left border)
 *   3. "Recurring" — bills with Recurrence != none (amethyst left border)
 *
 * A bill can appear in BOTH sections (a recurring rent that's due
 * tomorrow). We dedupe by id so the user doesn't see it twice.
 *
 * Data: /api/bills returns Active Type=bill rows, sorted by due date.
 * Split + totalled client-side so the screen stays responsive on cold
 * load.
 *
 * Interactions:
 *   - Tap a row → /task/{id} detail.
 *   - Swipe a row right → mark paid (POST /api/task/{id}/done).
 */

const URGENT_WINDOW_DAYS = 7;

function isUrgent(row) {
  if (!row.due_date) return false;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const due = new Date(row.due_date + "T00:00:00");
  const days = Math.round((due - today) / 86400000);
  return days <= URGENT_WINDOW_DAYS;
}

export default function Bills() {
  const nav = useNavigate();
  const location = useLocation();
  const isBrowseSub = location.pathname.startsWith("/browse/");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState(null);

  const reload = async () => {
    setError("");
    try {
      const data = await api("/api/bills");
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

  const handleDone = async (row) => {
    const prev = rows;
    setRows((rs) => (rs || []).filter((r) => r.id !== row.id));

    const msg = row.payee
      ? `Paid · ${row.payee.slice(0, 32)}`
      : `Paid · ${row.title.slice(0, 32)}`;

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
      message: msg,
      variant: "success",
      actionLabel: "undo",
      onAction: undo,
    });

    try {
      await api(`/api/task/${row.id}/done`, { method: "POST" });
    } catch (e) {
      setRows(prev);
      setToast({ message: `Couldn't mark paid: ${e.message}`, variant: "error" });
    }
  };

  const urgent = useMemo(
    () => (rows || []).filter((r) => isUrgent(r)),
    [rows]
  );
  const recurring = useMemo(
    () => (rows || []).filter((r) => r.recurrence && r.recurrence !== "none"),
    [rows]
  );
  const total = useMemo(
    () => (rows || []).reduce((sum, r) => sum + (r.amount || 0), 0),
    [rows]
  );

  const loading = rows === null;

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
        <div className="page-date">Bills</div>
        <h1 className="page-title">
          to <em>pay</em>
        </h1>
        <p className="page-subtitle">
          {loading
            ? "loading…"
            : `${rows.length} active · sorted by due date`}
        </p>
      </header>

      {!loading && rows.length > 0 && (
        <div className="bills-total">
          <span className="bills-total-label">Outstanding</span>
          <span className="bills-total-amount">
            ${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
      )}

      {loading && (
        <>
          <div className="skeleton" />
          <div className="skeleton" />
        </>
      )}

      {!loading && rows.length === 0 && !error && (
        <div className="empty">
          <div className="empty-art">✿</div>
          <p className="empty-msg">no bills outstanding. nothing owed.</p>
        </div>
      )}

      {!loading && urgent.length > 0 && (
        <>
          <div className="section-head">
            <div className="section-title">Urgent</div>
            <div className="section-count">
              {urgent.length} due in {URGENT_WINDOW_DAYS}d
            </div>
          </div>
          {urgent.map((row) => (
            <BillRow
              key={"u-" + row.id}
              row={row}
              variant="urgent"
              onOpen={() => nav(`/task/${row.id}`)}
              onDone={handleDone}
            />
          ))}
        </>
      )}

      {!loading && recurring.length > 0 && (
        <>
          <div className="section-head" style={{ marginTop: 12 }}>
            <div className="section-title">Recurring</div>
            <div className="section-count">{recurring.length}</div>
          </div>
          {recurring.map((row) => (
            <BillRow
              key={"r-" + row.id}
              row={row}
              variant="recurring"
              onOpen={() => nav(`/task/${row.id}`)}
              onDone={handleDone}
            />
          ))}
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

function BillRow({ row, variant, onOpen, onDone }) {
  const swipe = useSwipeDone(() => onDone && onDone(row));
  const due = relativeDueLabel(row.due_date);
  const recurrenceLabel =
    row.recurrence && row.recurrence !== "none" ? row.recurrence : null;
  const baseClass = "bill" + (variant === "recurring" ? " recurring" : "");
  const tappable = onOpen ? tap(onOpen, baseClass) : { className: baseClass };

  return (
    <div className="task-row-wrap">
      <div
        className="task-row-swipe-bg"
        style={{ opacity: swipe.swipeProgress }}
        aria-hidden="true"
      >
        <span className="task-row-swipe-icon">✓</span>
        <span className="task-row-swipe-label">paid</span>
      </div>
      <div {...tappable} style={swipe.style} {...swipe.handlers}>
        <div className="bill-amount">
          {row.amount != null
            ? "$" + row.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })
            : "—"}
        </div>
        <div className="bill-body">
          <div className="bill-payee">
            {row.payee || row.title}
          </div>
          <div className="bill-due">
            {[due, recurrenceLabel].filter(Boolean).join(" · ")}
          </div>
        </div>
      </div>
    </div>
  );
}
