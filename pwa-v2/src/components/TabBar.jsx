import { NavLink } from "react-router-dom";

/**
 * Persistent bottom tab bar — 3 tabs (Phase 2 architecture).
 *
 * The 3-tab structure matches the new locked design:
 *
 *   - Today  · main screen, your focus + quick wins + coming up
 *   - Browse · type chooser → drills into Work / Bills / Upcoming / Projects
 *   - Review · commitment funnel: needs-a-date + AI-flagged + parked
 *
 * Wins is folded into Today (count tile) and All is killed (Browse +
 * Today's Coming-Up replace it) per PROJECT_STATUS.md §3.
 *
 * Active state uses NavLink's automatic match-against-path; route paths
 * are intentionally simple so URLs stay shareable.
 */

const TABS = [
  { path: "/",       label: "Today",  glyph: "◯", glyphActive: "●" },
  { path: "/browse", label: "Browse", glyph: "◯", glyphActive: "●" },
  { path: "/review", label: "Review", glyph: "◯", glyphActive: "●" },
];

export default function TabBar() {
  return (
    <nav className="tab-bar" role="navigation" aria-label="Primary">
      {TABS.map((tab) => (
        <NavLink
          key={tab.path}
          to={tab.path}
          end={tab.path === "/"}
          className={({ isActive }) => "tab" + (isActive ? " active" : "")}
        >
          {({ isActive }) => (
            <>
              <span className="tab-icon" aria-hidden="true">
                {isActive ? tab.glyphActive : tab.glyph}
              </span>
              {tab.label}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
