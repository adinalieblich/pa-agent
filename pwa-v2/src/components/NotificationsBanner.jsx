import { useEffect, useState } from "react";
import {
  disablePush,
  enablePush,
  getPushStatus,
  sendTestPush,
} from "../lib/push";

/**
 * Slim banner that lets the user enable Web Push notifications.
 *
 *  - When the browser is already subscribed: shows a confirmation chip
 *    plus a small "test" button.
 *  - When NOT subscribed but supported: shows a one-line CTA. Tapping it
 *    triggers the permission prompt + subscribe call.
 *  - When unsupported / denied: shows actionable copy ("Add to home
 *    screen on iOS 16.4+" or "toggle on in iOS settings").
 *
 * Local-only state — no remembering "I dismissed this" because the state
 * IS the source of truth (subscribed / not / blocked). Keeps it honest.
 */
export default function NotificationsBanner() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [hidden, setHidden] = useState(false);
  // After a successful enable, show the "just turned on · test sent" state
  // briefly so the user gets visible confirmation instead of the banner
  // vanishing silently.
  const [justEnabled, setJustEnabled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getPushStatus().then((s) => {
      if (!cancelled) setStatus(s);
    });
    return () => { cancelled = true; };
  }, []);

  if (hidden || !status) return null;
  if (!status.supported) return null; // no point nagging unsupported browsers
  // Once push is on, hide — unless we JUST enabled, in which case show the
  // success state for a few seconds so the user knows it worked.
  if (status.subscribed && !justEnabled) return null;

  const onEnable = async () => {
    setBusy(true);
    setMessage("");
    try {
      await enablePush();
      setStatus(await getPushStatus());
      setJustEnabled(true);
      setMessage("Sending a test push…");
      // Fire a test push automatically so the user gets visible confirmation
      // that the subscribe actually wired through end-to-end.
      try {
        const r = await sendTestPush();
        if (r && r.sent > 0) {
          setMessage(
            `Notifications on. Test sent to ${r.sent} device${r.sent > 1 ? "s" : ""}.`,
          );
        } else {
          setMessage(
            "Notifications on. (Test didn't deliver — toggle on in iOS Settings → PA-Agent.)",
          );
        }
      } catch {
        setMessage("Notifications on.");
      }
      // Auto-hide the success state after 6 seconds so we don't loiter.
      setTimeout(() => setJustEnabled(false), 6000);
    } catch (e) {
      setMessage(e.message || "Couldn't enable notifications.");
    } finally {
      setBusy(false);
    }
  };

  const onDisable = async () => {
    setBusy(true);
    try {
      await disablePush();
      setStatus(await getPushStatus());
      setMessage("Notifications off.");
    } catch (e) {
      setMessage(e.message || "Couldn't disable.");
    } finally {
      setBusy(false);
    }
  };

  const onTest = async () => {
    setBusy(true);
    try {
      const r = await sendTestPush();
      setMessage(`Sent · ${r.sent} delivered, ${r.expired} expired`);
    } catch (e) {
      setMessage(e.message || "Test send failed");
    } finally {
      setBusy(false);
    }
  };

  if (status.subscribed) {
    return (
      <div className="notif-banner notif-banner-on">
        <span className="notif-banner-icon" aria-hidden="true">🔔</span>
        <span className="notif-banner-text">notifications on</span>
        <button
          type="button"
          className="notif-banner-action"
          onClick={onTest}
          disabled={busy}
        >
          test
        </button>
        <button
          type="button"
          className="notif-banner-action"
          onClick={onDisable}
          disabled={busy}
        >
          off
        </button>
        {message && <span className="notif-banner-message">· {message}</span>}
      </div>
    );
  }

  if (status.permission === "denied") {
    return (
      <div className="notif-banner notif-banner-warn">
        <span className="notif-banner-icon" aria-hidden="true">🔕</span>
        <span className="notif-banner-text">
          notifications blocked — toggle on in iOS Settings → PA-Agent
        </span>
        <button
          type="button"
          className="notif-banner-action"
          onClick={() => setHidden(true)}
        >
          dismiss
        </button>
      </div>
    );
  }

  return (
    <div className="notif-banner">
      <span className="notif-banner-icon" aria-hidden="true">🔔</span>
      <span className="notif-banner-text">
        get a ping when things are due
      </span>
      <button
        type="button"
        className="notif-banner-action notif-banner-action-primary"
        onClick={onEnable}
        disabled={busy}
      >
        {busy ? "…" : "turn on"}
      </button>
      <button
        type="button"
        className="notif-banner-action"
        onClick={() => setHidden(true)}
      >
        later
      </button>
      {message && <span className="notif-banner-message">· {message}</span>}
    </div>
  );
}
