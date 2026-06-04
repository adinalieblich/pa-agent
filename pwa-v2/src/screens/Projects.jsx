import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { tap } from "../lib/tap";

/**
 * Projects screen — matches docs/pwa_full_mockup.html "Projects" pane.
 *
 * Each project card shows:
 *   - Fraunces title + a priority tag (Projects DB uses High/Medium/Low)
 *   - Progress bar (emerald fill on rule-soft track)
 *   - "X of Y done · Z%"
 *   - "↗ next: [first incomplete subtask title]"
 *
 * Data: /api/projects returns rows from Projects DB with subtask
 * aggregation already done server-side (total_subtasks, done_subtasks,
 * next_incomplete_title) so the client just renders.
 */

const PRIORITY_TAG = {
  High: "ruby",
  Medium: "topaz",
  Low: "sapphire",
};

export default function Projects() {
  const nav = useNavigate();
  const location = useLocation();
  const isBrowseSub = location.pathname.startsWith("/browse/");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  const reload = async () => {
    setError("");
    try {
      const data = await api("/api/projects");
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
  const active = (rows || []).filter((p) => p.status === "Active");
  const paused = (rows || []).filter((p) => p.status === "Paused");

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
        <div className="page-date">Active</div>
        <h1 className="page-title">
          your <em>projects</em>
        </h1>
        <p className="page-subtitle">
          {loading
            ? "loading…"
            : `${active.length} active${paused.length ? ` · ${paused.length} paused` : ""}`}
        </p>
      </header>

      {loading && (
        <>
          <div className="skeleton" style={{ height: 100 }} />
          <div className="skeleton" style={{ height: 100 }} />
        </>
      )}

      {!loading && active.length === 0 && !error && (
        <div className="empty">
          <div className="empty-art">✿</div>
          <p className="empty-msg">
            no active projects. say "project: ..." to start one.
          </p>
        </div>
      )}

      {!loading && active.map((project) => (
        <ProjectCard
          key={project.id}
          project={project}
          onOpen={() => nav(`/project/${project.id}`)}
        />
      ))}

      {error && (
        <p className="empty-msg" style={{ padding: "0 22px", marginTop: 12 }}>
          {error}
        </p>
      )}
    </>
  );
}

function ProjectCard({ project, onOpen }) {
  const pct = project.total_subtasks > 0
    ? Math.round((project.done_subtasks / project.total_subtasks) * 100)
    : 0;
  const tagColor = PRIORITY_TAG[project.priority] || null;
  const tappable = onOpen ? tap(onOpen, "project-card") : { className: "project-card" };

  return (
    <div {...tappable}>
      <div className="project-head">
        <div className="project-title">{project.title}</div>
        {tagColor && (
          <span className={"tag " + tagColor}>
            {project.priority.toLowerCase()}
          </span>
        )}
      </div>
      <div className="project-progress">
        <div
          className="project-progress-fill"
          style={{ width: `${pct}%` }}
          aria-label={`${pct}% complete`}
        />
      </div>
      <div className="project-meta">
        <span>
          {project.done_subtasks} of {project.total_subtasks} done
        </span>
        <span>{pct}%</span>
      </div>
      {project.next_incomplete_title && (
        <div className="project-next">{project.next_incomplete_title}</div>
      )}
    </div>
  );
}
