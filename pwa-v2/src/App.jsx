import { useState } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import TabBar from "./components/TabBar.jsx";
import TokenGate from "./components/TokenGate.jsx";
import TopTiles from "./components/TopTiles.jsx";
import QuickCaptureFab from "./components/QuickCaptureFab.jsx";
import Today from "./screens/Today.jsx";
import Browse from "./screens/Browse.jsx";
import All from "./screens/All.jsx";
import Bills from "./screens/Bills.jsx";
import Projects from "./screens/Projects.jsx";
import Wins from "./screens/Wins.jsx";
import TaskDetail from "./screens/TaskDetail.jsx";
import ProjectDetail from "./screens/ProjectDetail.jsx";
import Review from "./screens/Review.jsx";
import Parked from "./screens/Parked.jsx";
import { getToken } from "./lib/api";

/**
 * Top-level shell.
 *
 * Phase 2 architecture: 3 tabs (Today · Browse · Review). Browse acts as
 * a type chooser that drills into Work / Bills / Upcoming / Projects.
 * Direct sub-routes are kept (e.g. /browse/bills) so deep links still work.
 *
 *   - Until a token is in localStorage, render <TokenGate /> alone.
 *   - Once authed, render the routed screen + the persistent <TabBar />.
 */
export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()));

  if (!authed) {
    return <TokenGate onAuthed={() => setAuthed(true)} />;
  }

  return <AppShell />;
}

function AppShell() {
  const location = useLocation();
  // Detail screens don't get the tiles/FAB chrome — they're full-canvas reads.
  const isDetail = location.pathname.startsWith("/task/") ||
                   location.pathname.startsWith("/project/");

  return (
    <div className="app">
      <main className="app-scroll">
        {!isDetail && <TopTiles />}
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/today" element={<Today />} />
          <Route path="/browse" element={<Browse />} />
          {/* Browse sub-routes — reuse legacy screens until they get a
              dedicated redesign. /all has no top-level tab but stays
              reachable via Browse → "Upcoming" until /browse/upcoming
              gets its own list view. */}
          <Route
            path="/browse/work"
            element={
              <All
                context="work"
                dateLabel="💼 Work"
                title={<><em>work</em> tasks</>}
                subtitlePrefix="work tasks"
              />
            }
          />
          <Route path="/browse/bills" element={<Bills />} />
          <Route path="/browse/upcoming" element={<All />} />
          <Route path="/browse/projects" element={<Projects />} />
          {/* Old paths still resolve in case anything has them bookmarked */}
          <Route path="/all" element={<All />} />
          <Route path="/bills" element={<Bills />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/wins" element={<Wins />} />
          <Route path="/review" element={<Review />} />
          <Route path="/parked" element={<Parked />} />
          <Route path="/task/:id" element={<TaskDetail />} />
          <Route path="/project/:id" element={<ProjectDetail />} />
        </Routes>
      </main>
      {!isDetail && <QuickCaptureFab />}
      {/* Paints the iOS home-indicator zone behind the tab bar so it
          never reads as a stray white strip. Defense-in-depth alongside
          the tab bar's opaque cream BG. */}
      <div className="safe-area-filler" aria-hidden="true" />
      <TabBar />
    </div>
  );
}
