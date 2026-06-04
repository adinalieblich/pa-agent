import { tap } from "../lib/tap";
import { useSwipeDone } from "../lib/useSwipeDone";
import {
  priorityTagClass,
  priorityTagLabel,
  relativeDueLabel,
} from "../lib/format";

/**
 * Shared task-row component used by Today, All, Wins, Review.
 *
 * Three interactions, in priority order:
 *   1. Tap the check-circle on the left  → mark done (optimistic).
 *   2. Swipe the row right (>120 px)     → mark done.
 *   3. Tap anywhere else on the row      → onOpen (navigate to detail).
 *
 * Props:
 *   row      — the TaskRow payload from the API.
 *   onOpen() — called when the user taps the body (not the check).
 *   onDone(row) — called after a successful mark-done animation. The parent
 *                 should optimistically remove this row from its list and
 *                 POST /api/task/{id}/done in the background.
 *   variant  — "default" shows priority chip + due; "bill" suppresses priority.
 */
export default function TaskRow({ row, onOpen, onDone, variant = "default" }) {
  const swipe = useSwipeDone(() => onDone && onDone(row));

  const due = relativeDueLabel(row.due_date);
  const showPriority =
    variant !== "bill" &&
    row.priority &&
    row.priority !== "Normal";

  const onCheckActivate = (e) => {
    e.stopPropagation();
    e.preventDefault();
    swipe.commit();
  };

  const tappable = onOpen ? tap(onOpen, "task") : { className: "task" };

  return (
    <div className="task-row-wrap">
      <div
        className="task-row-swipe-bg"
        style={{ opacity: swipe.swipeProgress }}
        aria-hidden="true"
      >
        <span className="task-row-swipe-icon">✓</span>
        <span className="task-row-swipe-label">done</span>
      </div>
      <div {...tappable} style={swipe.style} {...swipe.handlers}>
        <span
          className="check"
          aria-label="Mark done"
          role="button"
          tabIndex={0}
          onClick={onCheckActivate}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onCheckActivate(e);
          }}
        />
        <div className="task-text">
          {row.title}
          {row.first_step && <div className="meta">→ {row.first_step}</div>}
        </div>
        <div className="task-meta">
          {row.context === "work" && (
            <span className="tag sapphire" aria-label="Work task">💼</span>
          )}
          {showPriority && (
            <span className={"tag " + priorityTagClass(row.priority)}>
              {priorityTagLabel(row.priority)}
            </span>
          )}
          {due && <span className="tag-time">{due}</span>}
        </div>
      </div>
    </div>
  );
}
