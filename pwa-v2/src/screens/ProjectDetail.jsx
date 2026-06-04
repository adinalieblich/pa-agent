import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { tap } from "../lib/tap";
import { relativeDueLabel } from "../lib/format";
import Toast from "../components/Toast.jsx";

/**
 * Project Detail — Screen 7 of the PWA spec.
 *
 * Layout:
 *   - Back link → previous screen
 *   - Title (Fraunces)
 *   - Meta tag row: priority + completion %
 *   - Next-action callout (if set on the project, or first incomplete
 *     subtask as fallback)
 *   - Subtasks list with checkbox + title + sub-meta. Tap checkbox =
 *     mark done; tap title = navigate to that task's detail.
 *
 * Mutations use existing /api endpoints. Parent auto-completion happens
 * server-side via NotionClient.auto_complete_parent_if_all_subtasks_done
 * (helper exists but not yet called from this flow — Phase 3 nag worker
 * runs it on schedule). For now the parent stays Active until the next
 * worker tick.
 */

const PRIORITY_TAG = {
  High: "ruby",
  Medium: "topaz",
  Low: "sapphire",
};

export default function ProjectDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = async () => {
    setError("");
    try {
      const d = await api(`/api/project/${id}`);
      setData(d);
    } catch (e) {
      setError(e.message || "couldn't load");
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const goBack = () => {
    if (window.history.length > 1) nav(-1);
    else nav("/projects");
  };

  const toggleSubtask = async (subtask) => {
    if (busyId) return;
    if (subtask.status === "Done") return;
    setBusyId(subtask.id);
    try {
      await api(`/api/task/${subtask.id}/done`, { method: "POST" });
      setToast({ message: `✓ ${subtask.title}`, variant: "success" });
      await load();
    } catch (e) {
      setToast({ message: `Couldn't mark done: ${e.message}`, variant: "error" });
    } finally {
      setBusyId(null);
    }
  };

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

  if (!data) {
    return (
      <>
        <button className="detail-back row-button" onClick={goBack}>back</button>
        <div className="skeleton" style={{ height: 100 }} />
      </>
    );
  }

  const { project, subtasks } = data;
  const pct = project.total_subtasks > 0
    ? Math.round((project.done_subtasks / project.total_subtasks) * 100)
    : 0;
  const tagColor = PRIORITY_TAG[project.priority] || null;
  const nextLabel =
    project.next_action ||
    project.next_incomplete_title ||
    null;

  return (
    <>
      <button className="detail-back row-button" onClick={goBack}>back</button>
      <h1 className="detail-title">{project.title}</h1>

      <div className="detail-meta-row">
        {tagColor && (
          <span className={"tag " + tagColor}>
            {project.priority.toLowerCase()}
          </span>
        )}
        <span className="tag emerald">{pct}%</span>
        <span className="tag-time">
          {project.done_subtasks} of {project.total_subtasks} done
        </span>
      </div>

      <div className="project-progress" style={{ margin: "0 16px 14px" }}>
        <div
          className="project-progress-fill"
          style={{ width: `${pct}%` }}
          aria-label={`${pct}% complete`}
        />
      </div>

      {nextLabel && (
        <div className="detail-section">
          <div className="detail-section-label">Next action</div>
          <div className="detail-section-text next">{nextLabel}</div>
        </div>
      )}

      <div className="detail-section" style={{ padding: "12px 0 0" }}>
        <div
          className="detail-section-label"
          style={{ padding: "0 22px", marginBottom: 0 }}
        >
          Subtasks · {project.done_subtasks} of {project.total_subtasks}
        </div>
      </div>

      {subtasks.length === 0 && (
        <div className="empty" style={{ paddingTop: 28 }}>
          <p className="empty-msg">no subtasks yet.</p>
        </div>
      )}

      {subtasks.map((s) => {
        const done = s.status === "Done";
        const due = relativeDueLabel(s.due_date);
        // The check is a real <button> (no nested flow content). The title is
        // a tappable <div> using role=button so that nested <div.meta> stays
        // valid HTML and Mobile Safari handles the tap target correctly.
        return (
          <div
            key={s.id}
            className={"subtask" + (done ? " checked" : "")}
            role="group"
          >
            <button
              className="check"
              aria-label={done ? "completed" : "mark done"}
              onClick={() => toggleSubtask(s)}
              disabled={busyId === s.id || done}
              style={{ padding: 0 }}
            />
            <div
              {...tap(() => nav(`/task/${s.id}`), "subtask-text")}
            >
              {s.title}
              {due && <div className="meta">{due}</div>}
            </div>
          </div>
        );
      })}

      <Toast
        message={toast?.message}
        variant={toast?.variant}
        onDismiss={() => setToast(null)}
      />
    </>
  );
}
