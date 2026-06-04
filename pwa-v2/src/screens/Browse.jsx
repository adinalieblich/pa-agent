import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { greetingWord, pageDateLabel } from "../lib/format";
import { applyOverride } from "../lib/workMode";
import Toast from "../components/Toast.jsx";

/**
 * Browse — the type chooser.
 *
 * Replaces the old All / Bills / Projects / Wins tabs with four large
 * navigation cards. Each card shows a one-line summary fetched from the
 * same endpoints the dedicated screens used to call, so the user can
 * pick a slice by *kind* instead of by *day*.
 *
 *   - 💼 Work     · sapphire, shows mode status (on/off + window)
 *   - 💰 Bills    · next due + total due this week
 *   - 📅 Upcoming · this week / month / later count
 *   - 📁 Projects · count of active projects
 *
 * Tapping a card navigates to a dedicated sub-route. For v1 we reuse
 * the legacy /all, /bills, /projects screens behind these cards — the
 * card layer just gives the surface a new "Browse" identity.
 */

const CARDS = [
  {
    id: "work",
    icon: "💼",
    title: "Work",
    accent: "sapphire",
    route: "/browse/work",
  },
  {
    id: "bills",
    icon: "💰",
    title: "Bills",
    accent: "amethyst",
    route: "/browse/bills",
  },
  {
    id: "upcoming",
    icon: "📅",
    title: "Upcoming",
    accent: "topaz",
    route: "/browse/upcoming",
  },
  {
    id: "projects",
    icon: "📁",
    title: "Projects",
    accent: "emerald",
    route: "/browse/projects",
  },
];

export default function Browse() {
  const nav = useNavigate();
  const [summary, setSummary] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  const load = async () => {
    try {
      const [workMode, bills, upcoming, projects] = await Promise.allSettled([
        api("/api/work-mode"),
        api("/api/bills"),
        api("/api/upcoming?days=30"),
        api("/api/projects"),
      ]);
      setSummary({
        work: workMode.status === "fulfilled" ? workMode.value : null,
        bills: bills.status === "fulfilled" ? bills.value : null,
        upcoming: upcoming.status === "fulfilled" ? upcoming.value : null,
        projects: projects.status === "fulfilled" ? projects.value : null,
      });
    } catch (e) {
      setError(e.message || "couldn't load");
    }
  };

  useEffect(() => { load(); }, []);

  // Inline action handler used by the Work card when work mode is OFF.
  // PROJECT_STATUS D7: "Start work mode now" lives here, not on Today.
  const onStartWorkNow = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await applyOverride("start-now", { hours: 4 });
      setToast({ message: "Work mode on for 4 hours", variant: "success" });
      await load();
    } catch (e) {
      setToast({ message: `Couldn't start: ${e.message}`, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-header">
        <div className="page-date">{pageDateLabel()}</div>
        <h1 className="page-title">
          good <em>{greetingWord()}</em>
        </h1>
        <p className="page-subtitle">browse by type</p>
      </header>

      <div className="browse-grid">
        {CARDS.map((c) => (
          <BrowseCard
            key={c.id}
            card={c}
            summary={summary[c.id]}
            onTap={() => nav(c.route)}
            onStartWorkNow={c.id === "work" ? onStartWorkNow : undefined}
            busy={busy && c.id === "work"}
          />
        ))}
      </div>

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

function BrowseCard({ card, summary, onTap, onStartWorkNow, busy }) {
  const detail = summarise(card.id, summary);
  // Show inline "start now" only on the Work card when mode is currently OFF.
  const showStartWork =
    card.id === "work" &&
    onStartWorkNow &&
    summary &&
    summary.active === false;
  return (
    <div className={`browse-card-wrap`}>
      <button
        type="button"
        className={`browse-card browse-card-${card.accent}`}
        onClick={onTap}
      >
        <span className="browse-card-icon" aria-hidden="true">{card.icon}</span>
        <span className="browse-card-title">{card.title}</span>
        <span className="browse-card-detail">{detail}</span>
      </button>
      {showStartWork && (
        <button
          type="button"
          className="browse-card-action"
          onClick={(e) => { e.stopPropagation(); onStartWorkNow(); }}
          disabled={busy}
        >
          {busy ? "…" : "start work mode (4h)"}
        </button>
      )}
    </div>
  );
}

function summarise(id, data) {
  if (!data) return "tap to open";
  switch (id) {
    case "work": {
      const active = !!data.active;
      const src = data.source === "override" ? " · override" : "";
      return active ? `mode on${src}` : `off · M–F 9–5`;
    }
    case "bills": {
      const n = data.count ?? 0;
      return n === 0 ? "nothing owing" : `${n} ${n === 1 ? "bill" : "bills"}`;
    }
    case "upcoming": {
      const n = data.count ?? 0;
      return n === 0 ? "clear next 30d" : `${n} in next 30 days`;
    }
    case "projects": {
      const n = data.count ?? 0;
      return n === 0 ? "no active projects" : `${n} active`;
    }
    default:
      return "";
  }
}
