import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

/**
 * Small "needs your eye" chip that surfaces in any page header when the
 * review queue has items. Polls /api/review every 60s so the count
 * stays roughly fresh without spamming Notion.
 *
 * Renders nothing while count is 0 — it's an attention hook, not a
 * permanent UI fixture.
 */
export default function ReviewBell() {
  const [count, setCount] = useState(0);
  const nav = useNavigate();

  useEffect(() => {
    let cancelled = false;
    const fetchCount = async () => {
      try {
        const r = await api("/api/review");
        if (!cancelled) setCount(r.count || 0);
      } catch {
        // Soft-fail: a transient error must not cause the chip to flash.
      }
    };
    fetchCount();
    const interval = setInterval(fetchCount, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (count === 0) return null;
  return (
    <button
      className="header-bell row-button"
      onClick={() => nav("/review")}
    >
      {count} to review
    </button>
  );
}
