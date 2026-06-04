import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { priorityTagClass, priorityTagLabel, relativeDueLabel } from "../lib/format";
import Toast from "../components/Toast.jsx";

/**
 * Review — Phase 2 redesign: commitment funnel.
 *
 * Three sections, top → bottom:
 *
 *   📌 Needs a date (topaz)
 *      Active rows that don't have a due date AND aren't Someday priority.
 *      Quick date chips inline so a tap commits a date without leaving
 *      the screen.
 *
 *   ✦ AI flagged (magenta)
 *      Rows the agent tagged "review" because classifier/extractor
 *      confidence dipped under threshold. Save / edit / delete actions.
 *
 *   📦 Parked (closed by default)
 *      Status=Parked pile. Opens to a dedicated /parked sub-screen for
 *      revive / delete-forever flows so the Review tab stays focused.
 *
 * Data: /api/needs-date · /api/review · /api/parked (count only here)
 */

const QUICK_DATE_CHIPS = [
  { label: "today", delta: 0 },
  { label: "tomorrow", delta: 1 },
  { label: "Sat", delta: "next-saturday" },
  { label: "next wk", delta: 7 },
];

function isoForDelta(delta) {
  const d = new Date();
  if (delta === "next-saturday") {
    const dow = d.getDay();
    // Days until Saturday (6). If it IS Saturday, jump a week so we don't
    // resolve to "today".
    const add = ((6 - dow + 7) % 7) || 7;
    d.setDate(d.getDate() + add);
  } else {
    d.setDate(d.getDate() + Number(delta));
  }
  return d.toISOString().slice(0, 10);
}

export default function Review() {
  const nav = useNavigate();
  const [needsDate, setNeedsDate] = useState(null); // null = loading
  const [flagged, setFlagged] = useState(null);
  const [parkedCount, setParkedCount] = useState(null);
  const [editing, setEditing] = useState(null);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState("");

  const reload = async () => {
    setError("");
    try {
      const [needs, flag, park] = await Promise.allSettled([
        api("/api/needs-date"),
        api("/api/review"),
        api("/api/parked"),
      ]);
      setNeedsDate(needs.status === "fulfilled" ? needs.value.items || [] : []);
      setFlagged(flag.status === "fulfilled" ? flag.value.items || [] : []);
      setParkedCount(
        park.status === "fulfilled" ? park.value.count ?? 0 : 0
      );
    } catch (e) {
      setError(e.message || "couldn't load");
    }
  };

  useEffect(() => { reload(); }, []);

  // --- Needs-date actions -------------------------------------------------

  const onSetDate = async (row, isoDate) => {
    const prev = needsDate;
    setNeedsDate((rs) => (rs || []).filter((r) => r.id !== row.id));
    try {
      await api(`/api/task/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ due_date: isoDate }),
      });
      setToast({ message: `Set due ${isoDate}`, variant: "success" });
    } catch (e) {
      setNeedsDate(prev);
      setToast({ message: `Couldn't save: ${e.message}`, variant: "error" });
    }
  };

  // --- AI flagged actions -------------------------------------------------

  const onConfirm = async (row) => {
    try {
      await api(`/api/task/${row.id}/confirm-review`, { method: "POST" });
      setFlagged((rs) => (rs || []).filter((r) => r.id !== row.id));
      setToast({ message: `Confirmed: ${row.title}`, variant: "success" });
    } catch (e) {
      setToast({ message: `Couldn't save: ${e.message}`, variant: "error" });
    }
  };

  const onDelete = async (row) => {
    if (!confirm(`Delete "${row.title}"?`)) return;
    try {
      await api(`/api/task/${row.id}`, { method: "DELETE" });
      setFlagged((rs) => (rs || []).filter((r) => r.id !== row.id));
      setToast({ message: "Deleted", variant: "muted" });
    } catch (e) {
      setToast({ message: `Couldn't delete: ${e.message}`, variant: "error" });
    }
  };

  const loading = needsDate === null || flagged === null;
  const allEmpty = !loading && !needsDate.length && !flagged.length && !parkedCount;

  return (
    <>
      <header className="page-header">
        <div className="page-date">Needs your eye</div>
        <h1 className="page-title">
          to <em>review</em>
        </h1>
        {loading ? (
          <p className="page-subtitle">loading…</p>
        ) : (
          <p className="page-subtitle">
            {needsDate.length} need a date · {flagged.length} flagged
            {parkedCount ? ` · ${parkedCount} parked` : ""}
          </p>
        )}
      </header>

      {/* 📌 Needs a date */}
      {!loading && needsDate.length > 0 && (
        <>
          <div className="section-head">
            <div className="section-title">📌 Needs a date</div>
            <div className="section-count">{needsDate.length}</div>
          </div>
          {needsDate.map((row) => (
            <NeedsDateCard
              key={row.id}
              row={row}
              onSetDate={(iso) => onSetDate(row, iso)}
              onOpen={() => nav(`/task/${row.id}`)}
            />
          ))}
        </>
      )}

      {/* ✦ AI flagged */}
      {!loading && flagged.length > 0 && (
        <>
          <div className="section-head" style={{ marginTop: 14 }}>
            <div className="section-title">✦ AI flagged</div>
            <div className="section-count">{flagged.length}</div>
          </div>
          {flagged.map((row) => (
            <ReviewCard
              key={row.id}
              row={row}
              onOpen={() => nav(`/task/${row.id}`)}
              onSave={() => onConfirm(row)}
              onEdit={() => setEditing(row)}
              onDelete={() => onDelete(row)}
            />
          ))}
        </>
      )}

      {/* 📦 Parked — collapsed entry point */}
      {!loading && parkedCount > 0 && (
        <button
          type="button"
          className="parked-strip"
          onClick={() => nav("/parked")}
        >
          <span className="parked-strip-icon" aria-hidden="true">📦</span>
          <span className="parked-strip-label">Parked</span>
          <span className="parked-strip-count">{parkedCount}</span>
          <span className="parked-strip-chevron" aria-hidden="true">›</span>
        </button>
      )}

      {loading && (
        <>
          <div className="skeleton" style={{ height: 100 }} />
          <div className="skeleton" style={{ height: 100 }} />
        </>
      )}

      {allEmpty && (
        <div className="empty">
          <div className="empty-art">✿</div>
          <p className="empty-msg">
            review queue empty. clean slate.
          </p>
        </div>
      )}

      {error && (
        <p className="empty-msg" style={{ padding: "0 22px", marginTop: 12 }}>
          {error}
        </p>
      )}

      {editing && (
        <EditModal
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={async (msg) => {
            setEditing(null);
            setToast({ message: msg, variant: "success" });
            await reload();
          }}
          onError={(msg) => setToast({ message: msg, variant: "error" })}
        />
      )}

      <Toast
        message={toast?.message}
        variant={toast?.variant}
        onDismiss={() => setToast(null)}
      />
    </>
  );
}

/* --- Sub-components ---------------------------------------------------- */

function NeedsDateCard({ row, onSetDate, onOpen }) {
  // Inline native date picker — keeps the affordance simple and standards-y.
  // The four chips cover the 90% case; `📅` opens the system picker for the
  // long tail.
  const [picking, setPicking] = useState(false);
  return (
    <div className="needs-date-card">
      <button className="row-button needs-date-title" onClick={onOpen}>
        {row.title}
      </button>
      <div className="needs-date-chips">
        {QUICK_DATE_CHIPS.map((chip) => (
          <button
            key={chip.label}
            type="button"
            className="needs-date-chip"
            onClick={() => onSetDate(isoForDelta(chip.delta))}
          >
            {chip.label}
          </button>
        ))}
        <label className="needs-date-chip needs-date-chip-picker">
          <span aria-hidden="true">📅</span>
          <input
            type="date"
            onChange={(e) => {
              if (e.target.value) {
                onSetDate(e.target.value);
                setPicking(false);
              }
            }}
            onFocus={() => setPicking(true)}
            onBlur={() => setPicking(false)}
          />
        </label>
      </div>
    </div>
  );
}

function ReviewCard({ row, onOpen, onSave, onEdit, onDelete }) {
  const flags = [];
  if (row.type === "bill" && (row.amount == null || row.amount === 0)) {
    flags.push({ label: "no amount detected", color: "tag-time" });
  }
  if (!row.due_date && row.priority === "Urgent") {
    flags.push({ label: "urgent but no due date", color: "tag-time" });
  }
  if (!row.first_step) {
    flags.push({ label: "no first step", color: "tag-time" });
  }

  return (
    <div className="review-card">
      <button className="row-button review-original" onClick={onOpen}>
        captured from voice — open in detail
      </button>
      <div className="review-interpreted">{row.title}</div>

      <div className="review-fields">
        <span className={"tag " + (row.type === "bill" ? "amethyst" : "topaz")}>
          {row.type === "bill" ? "bill?" : "task?"}
        </span>
        {row.priority && row.priority !== "Normal" && (
          <span className={"tag " + priorityTagClass(row.priority)}>
            {priorityTagLabel(row.priority)}
          </span>
        )}
        {row.due_date && (
          <span className="tag topaz">{relativeDueLabel(row.due_date)}</span>
        )}
        {flags.map((f, i) => (
          <span key={i} className={f.color}>
            {f.label}
          </span>
        ))}
      </div>

      <div className="review-actions">
        <button className="review-btn confirm" onClick={onSave}>save</button>
        <button className="review-btn edit"    onClick={onEdit}>edit</button>
        <button className="review-btn delete"  onClick={onDelete}>delete</button>
      </div>
    </div>
  );
}

function EditModal({ row, onClose, onSaved, onError }) {
  const [title, setTitle] = useState(row.title || "");
  const [priority, setPriority] = useState(row.priority || "Normal");
  const [due, setDue] = useState(row.due_date || "");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e?.preventDefault?.();
    setBusy(true);
    try {
      const patch = {
        title: title.trim() || undefined,
        priority,
        due_date: due || undefined,
      };
      await api(`/api/task/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      await api(`/api/task/${row.id}/confirm-review`, { method: "POST" });
      onSaved("Updated & confirmed");
    } catch (e) {
      onError(`Couldn't save: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  // Portal to body so the modal escapes the .app-scroll stacking context —
  // otherwise the tab bar / FAB show through (z-index inside an
  // overflow:auto parent doesn't beat siblings in the same context).
  return createPortal(
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <form className="modal" onSubmit={submit}>
        <div className="modal-scroll">
          <h2>Edit & confirm</h2>

          <label>Title</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />

          <label>Priority</label>
          <select value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option>Urgent</option>
            <option>Important</option>
            <option>Normal</option>
            <option>Someday</option>
          </select>

          <label>Due date</label>
          <input
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
        </div>

        <div className="modal-actions">
          <button type="button" className="cancel" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="save" disabled={busy}>
            {busy ? "Saving…" : "Save & confirm"}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
