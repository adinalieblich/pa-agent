import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import {
  priorityTagClass,
  priorityTagLabel,
  relativeDueLabel,
} from "../lib/format";
import Toast from "../components/Toast.jsx";

/**
 * Task Detail screen.
 *
 * View mode:
 *   - title, meta tags (priority/type/due/recurrence/review)
 *   - first step / amount / payee / notes / parent / captured
 *   - actions: Edit · Mark done · Snooze +1d · Delete
 *
 * Edit mode (tap Edit):
 *   - title becomes an <input>
 *   - first step becomes an <input>
 *   - notes becomes a <textarea> (auto-grow)
 *   - amount/payee become <input>s when it's a bill
 *   - actions become: Save · Cancel
 *
 * Save -> PATCH /api/task/{id} with the changed fields only.
 */

function isoToHuman(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

// Build a patch object containing only changed fields. Returns null if no diff.
function buildPatch(original, draft) {
  const patch = {};
  for (const k of ["title", "first_step", "notes", "amount", "payee"]) {
    const o = original[k] ?? "";
    const d = draft[k] ?? "";
    // For amount, coerce empty -> null (server-side ignores null via exclude_unset).
    if (k === "amount") {
      const oNum = original.amount;
      const dNum = draft.amount === "" || draft.amount == null ? null : Number(draft.amount);
      if (dNum !== oNum && !(dNum == null && oNum == null)) {
        patch.amount = dNum;
      }
      continue;
    }
    if (o !== d) {
      patch[k] = d;
    }
  }
  return Object.keys(patch).length ? patch : null;
}

function emptyDraft() {
  return { title: "", first_step: "", notes: "", amount: "", payee: "" };
}

function draftFromRow(row) {
  return {
    title: row.title ?? "",
    first_step: row.first_step ?? "",
    notes: row.notes ?? "",
    amount: row.amount == null ? "" : String(row.amount),
    payee: row.payee ?? "",
  };
}

export default function TaskDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [row, setRow] = useState(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(emptyDraft());

  const load = async () => {
    setError("");
    try {
      const data = await api(`/api/task/${id}`);
      setRow(data);
      setDraft(draftFromRow(data));
    } catch (e) {
      setError(e.message || "couldn't load");
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const goBack = () => {
    if (window.history.length > 1) nav(-1);
    else nav("/");
  };

  const markDone = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api(`/api/task/${id}/done`, { method: "POST" });
      setToast({ message: "Marked done", variant: "success" });
      setTimeout(goBack, 600);
    } catch (e) {
      setToast({ message: `Couldn't mark done: ${e.message}`, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const snooze = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await api(`/api/task/${id}/snooze`, { method: "POST" });
      setToast({
        message: r.new_due_date
          ? `Snoozed → ${relativeDueLabel(r.new_due_date)}`
          : "Snoozed",
        variant: "muted",
      });
      await load();
    } catch (e) {
      setToast({ message: `Couldn't snooze: ${e.message}`, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  // Tap the context chip in the meta row to flip personal ↔ work.
  // Useful when the classifier got it wrong on capture.
  const toggleContext = async () => {
    if (busy || !row) return;
    const next = row.context === "work" ? "personal" : "work";
    setBusy(true);
    try {
      const updated = await api(`/api/task/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ context: next }),
      });
      setRow(updated);
      setToast({
        message: `Marked as ${next}`,
        variant: "success",
      });
    } catch (e) {
      setToast({ message: `Couldn't update: ${e.message}`, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (busy) return;
    if (!confirm("Delete this row? It will be moved to Cancelled.")) return;
    setBusy(true);
    try {
      await api(`/api/task/${id}`, { method: "DELETE" });
      setToast({ message: "Deleted", variant: "muted" });
      setTimeout(goBack, 500);
    } catch (e) {
      setToast({ message: `Couldn't delete: ${e.message}`, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    if (busy || !row) return;
    setDraft(draftFromRow(row));
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    if (row) setDraft(draftFromRow(row));
  };

  const saveEdit = async () => {
    if (busy || !row) return;
    const patch = buildPatch(row, draft);
    if (!patch) {
      setEditing(false);
      setToast({ message: "Nothing changed", variant: "muted" });
      return;
    }
    setBusy(true);
    try {
      const updated = await api(`/api/task/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setRow(updated);
      setDraft(draftFromRow(updated));
      setEditing(false);
      setToast({ message: "Saved", variant: "success" });
    } catch (e) {
      setToast({ message: `Couldn't save: ${e.message}`, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const updateDraft = (k, v) => setDraft((d) => ({ ...d, [k]: v }));

  if (error) {
    return (
      <>
        <button className="detail-back row-button" onClick={goBack}>back</button>
        <p className="empty-msg" style={{ padding: "0 22px", marginTop: 12 }}>
          {error}
        </p>
      </>
    );
  }

  if (!row) {
    return (
      <>
        <button className="detail-back row-button" onClick={goBack}>back</button>
        <div className="skeleton" style={{ height: 100 }} />
      </>
    );
  }

  const isBill = row.type === "bill";
  const dueLabel = relativeDueLabel(row.due_date);

  return (
    <>
      <button className="detail-back row-button" onClick={goBack}>
        back
      </button>

      {!editing && (
        <h1 className="detail-title">{row.title}</h1>
      )}
      {editing && (
        <input
          className="detail-edit-input title"
          value={draft.title}
          onChange={(e) => updateDraft("title", e.target.value)}
          placeholder="Title"
          autoFocus
        />
      )}

      <div className="detail-meta-row">
        {row.priority && row.priority !== "Normal" && (
          <span className={"tag " + priorityTagClass(row.priority)}>
            {priorityTagLabel(row.priority)}
          </span>
        )}
        <span className={"tag " + (isBill ? "amethyst" : "topaz")}>
          {isBill ? "bill" : "task"}
        </span>
        {/* Tappable context chip — flips on tap so misclassifications are
            a one-tap fix instead of a full edit cycle. */}
        <button
          type="button"
          className={"tag tag-button " + (row.context === "work" ? "sapphire" : "neutral")}
          onClick={toggleContext}
          disabled={busy}
          aria-label={`Currently ${row.context || "personal"} — tap to flip`}
        >
          {row.context === "work" ? "💼 work" : "🏠 personal"}
        </button>
        {dueLabel && <span className="tag topaz">{dueLabel}</span>}
        {row.recurrence && row.recurrence !== "none" && (
          <span className="tag amethyst">↻ {row.recurrence}</span>
        )}
        {(row.auto_tags || []).includes("review") && (
          <span className="tag magenta">review</span>
        )}
      </div>

      {/* First step */}
      {!editing && row.first_step && (
        <div className="detail-section">
          <div className="detail-section-label">First step</div>
          <div className="detail-section-text">{row.first_step}</div>
        </div>
      )}
      {editing && (
        <div className="detail-section">
          <div className="detail-section-label">First step</div>
          <input
            className="detail-edit-input"
            value={draft.first_step}
            onChange={(e) => updateDraft("first_step", e.target.value)}
            placeholder="One concrete next action"
          />
        </div>
      )}

      {/* Amount (bills only) */}
      {!editing && isBill && row.amount != null && (
        <div className="detail-section">
          <div className="detail-section-label">Amount</div>
          <div className="detail-section-text amount">
            ${row.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </div>
        </div>
      )}
      {editing && isBill && (
        <div className="detail-section">
          <div className="detail-section-label">Amount</div>
          <input
            className="detail-edit-input"
            type="number"
            inputMode="decimal"
            value={draft.amount}
            onChange={(e) => updateDraft("amount", e.target.value)}
            placeholder="0.00"
            step="0.01"
          />
        </div>
      )}

      {/* Payee (bills only) */}
      {!editing && isBill && row.payee && (
        <div className="detail-section">
          <div className="detail-section-label">Payee</div>
          <div className="detail-section-text">{row.payee}</div>
        </div>
      )}
      {editing && isBill && (
        <div className="detail-section">
          <div className="detail-section-label">Payee</div>
          <input
            className="detail-edit-input"
            value={draft.payee}
            onChange={(e) => updateDraft("payee", e.target.value)}
            placeholder="Who you're paying"
          />
        </div>
      )}

      {/* Notes */}
      {!editing && row.notes && (
        <div className="detail-section">
          <div className="detail-section-label">Notes</div>
          <div className="detail-section-text">{row.notes}</div>
        </div>
      )}
      {editing && (
        <div className="detail-section">
          <div className="detail-section-label">Notes</div>
          <textarea
            className="detail-edit-input notes"
            value={draft.notes}
            onChange={(e) => updateDraft("notes", e.target.value)}
            placeholder="Add notes…"
            rows={4}
          />
        </div>
      )}

      {row.parent_task_id && !editing && (
        <div className="detail-section">
          <div className="detail-section-label">Part of project</div>
          <button
            className="detail-section-text"
            onClick={() => nav(`/task/${row.parent_task_id}`)}
            style={{
              color: "var(--magenta)",
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
            }}
          >
            ↗ open parent task
          </button>
        </div>
      )}

      {row.captured_at && !editing && (
        <div className="detail-section">
          <div className="detail-section-label">Captured</div>
          <div className="detail-section-text">
            {isoToHuman(row.captured_at)} via voice
          </div>
        </div>
      )}

      {/* Actions */}
      {!editing && (
        <div className="detail-actions">
          <button
            className="detail-action-btn done"
            onClick={markDone}
            disabled={busy}
          >
            Mark done
          </button>
          <button
            className="detail-action-btn snooze"
            onClick={snooze}
            disabled={busy}
          >
            Snooze +1d
          </button>
          <button
            className="detail-action-btn edit"
            onClick={startEdit}
            disabled={busy}
          >
            Edit
          </button>
          <button
            className="detail-action-btn delete"
            onClick={remove}
            disabled={busy}
          >
            Delete
          </button>
        </div>
      )}
      {editing && (
        <div className="detail-actions">
          <button
            className="detail-action-btn done"
            onClick={saveEdit}
            disabled={busy}
          >
            Save
          </button>
          <button
            className="detail-action-btn snooze"
            onClick={cancelEdit}
            disabled={busy}
          >
            Cancel
          </button>
        </div>
      )}

      <Toast
        message={toast?.message}
        variant={toast?.variant}
        onDismiss={() => setToast(null)}
      />
    </>
  );
}
