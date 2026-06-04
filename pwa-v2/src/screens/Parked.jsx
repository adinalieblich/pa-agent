import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import Toast from "../components/Toast.jsx";

/**
 * Parked — sub-screen reached from Review → 📦 Parked strip.
 *
 * Shows Status=Parked rows, oldest-first. Two actions per row:
 *
 *   - Revive: prompts for a due-date (forces a commitment), then
 *     flips the row back to Active.
 *   - Delete forever: prompts to confirm, then soft-deletes.
 *
 * The "long-parked" badge surfaces rows older than 12 months — gentle
 * cue that the row may no longer matter.
 */

const TWELVE_MONTHS_MS = 365 * 24 * 60 * 60 * 1000;

export default function Parked() {
  const nav = useNavigate();
  const [rows, setRows] = useState(null);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState("");

  const reload = async () => {
    setError("");
    try {
      const data = await api("/api/parked");
      setRows(data.items || []);
    } catch (e) {
      setError(e.message || "couldn't load");
      setRows([]);
    }
  };

  useEffect(() => { reload(); }, []);

  const onRevive = async (row) => {
    const iso = window.prompt(
      `Bring "${row.title}" back to active.\nNew due date (YYYY-MM-DD)?`,
      defaultReviveDate(),
    );
    if (!iso) return;
    try {
      await api(`/api/task/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ due_date: iso }),
      });
      // Restore endpoint flips Status → Active.
      await api(`/api/task/${row.id}/restore`, { method: "POST" });
      setRows((rs) => (rs || []).filter((r) => r.id !== row.id));
      setToast({ message: `Revived for ${iso}`, variant: "success" });
    } catch (e) {
      setToast({ message: `Couldn't revive: ${e.message}`, variant: "error" });
    }
  };

  const onDeleteForever = async (row) => {
    if (!confirm(`Delete "${row.title}" forever?`)) return;
    try {
      await api(`/api/task/${row.id}`, { method: "DELETE" });
      setRows((rs) => (rs || []).filter((r) => r.id !== row.id));
      setToast({ message: "Deleted", variant: "muted" });
    } catch (e) {
      setToast({ message: `Couldn't delete: ${e.message}`, variant: "error" });
    }
  };

  const loading = rows === null;
  const empty = !loading && rows.length === 0;

  return (
    <>
      <header className="page-header">
        <button
          type="button"
          className="row-button page-back"
          onClick={() => nav("/review")}
        >
          ‹ Review
        </button>
        <div className="page-date">📦 Parked</div>
        <h1 className="page-title">
          for <em>later</em>
        </h1>
        <p className="page-subtitle">
          {loading
            ? "loading…"
            : `${rows.length} ${rows.length === 1 ? "item" : "items"} on ice`}
        </p>
      </header>

      {loading && (
        <>
          <div className="skeleton" style={{ height: 70 }} />
          <div className="skeleton" style={{ height: 70 }} />
        </>
      )}

      {empty && (
        <div className="empty">
          <div className="empty-art">✿</div>
          <p className="empty-msg">no parked items.</p>
        </div>
      )}

      {!loading && rows.map((row) => (
        <ParkedRow
          key={row.id}
          row={row}
          onRevive={() => onRevive(row)}
          onDelete={() => onDeleteForever(row)}
        />
      ))}

      {error && (
        <p className="empty-msg" style={{ padding: "0 22px", marginTop: 12 }}>
          {error}
        </p>
      )}

      <Toast
        message={toast?.message}
        variant={toast?.variant}
        onDismiss={() => setToast(null)}
      />
    </>
  );
}

function ParkedRow({ row, onRevive, onDelete }) {
  const longParked = isLongParked(row.captured_at);
  return (
    <div className="parked-row">
      <div className="parked-row-head">
        <div className="parked-row-title">{row.title}</div>
        {longParked && (
          <span className="tag amethyst parked-row-badge">long parked</span>
        )}
      </div>
      <div className="parked-row-meta">{relativeAge(row.captured_at)}</div>
      <div className="parked-row-actions">
        <button type="button" className="review-btn confirm" onClick={onRevive}>
          revive
        </button>
        <button type="button" className="review-btn delete" onClick={onDelete}>
          delete forever
        </button>
      </div>
    </div>
  );
}

function isLongParked(capturedAt) {
  if (!capturedAt) return false;
  try {
    const t = new Date(capturedAt).getTime();
    return Date.now() - t > TWELVE_MONTHS_MS;
  } catch {
    return false;
  }
}

function relativeAge(capturedAt) {
  if (!capturedAt) return "no date";
  try {
    const ageMs = Date.now() - new Date(capturedAt).getTime();
    const days = Math.floor(ageMs / (24 * 60 * 60 * 1000));
    if (days < 7) return `parked ${days}d ago`;
    if (days < 60) return `parked ${Math.floor(days / 7)}w ago`;
    if (days < 365) return `parked ${Math.floor(days / 30)}mo ago`;
    return `parked ${Math.floor(days / 365)}y ago`;
  } catch {
    return "no date";
  }
}

function defaultReviveDate() {
  const d = new Date();
  d.setDate(d.getDate() + 7);
  return d.toISOString().slice(0, 10);
}
