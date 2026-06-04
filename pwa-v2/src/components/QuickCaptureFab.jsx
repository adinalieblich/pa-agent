import { useState, useEffect, useRef } from "react";
import { api } from "../lib/api";
import Toast from "./Toast.jsx";

/**
 * Floating "+" / mic button at the bottom-right that opens a quick-capture
 * sheet. Same backend flow as the iOS Shortcut — POSTs text to /capture
 * and shows the resulting summary as a toast.
 *
 * Sheet UI:
 *   - Auto-focused textarea
 *   - Send button (or Enter)
 *   - Cancel button (or Esc / backdrop tap)
 *
 * Persistent across all screens via App.jsx.
 */
export default function QuickCaptureFab() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      // Focus after the sheet animates in.
      const t = setTimeout(() => inputRef.current?.focus(), 80);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Close on Esc.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") closeSheet(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const closeSheet = () => {
    if (busy) return;
    setOpen(false);
    setText("");
  };

  const submit = async () => {
    const v = text.trim();
    if (!v || busy) return;
    setBusy(true);
    try {
      const r = await api("/capture", {
        method: "POST",
        body: JSON.stringify({ text: v }),
      });
      const summary = r?.summary || "Captured";
      setToast({ message: summary, variant: "success" });
      setOpen(false);
      setText("");
    } catch (e) {
      setToast({ message: `Couldn't capture: ${e.message}`, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="fab"
        onClick={() => setOpen(true)}
        aria-label="Quick capture"
      >
        +
      </button>

      {open && (
        <div
          className="fab-sheet-backdrop"
          onClick={(e) => { if (e.target === e.currentTarget) closeSheet(); }}
        >
          <div className="fab-sheet" role="dialog" aria-label="Quick capture">
            <div className="fab-sheet-head">
              <div className="fab-sheet-title">capture</div>
              <button
                type="button"
                className="fab-sheet-close"
                onClick={closeSheet}
                aria-label="Close"
              >×</button>
            </div>
            <textarea
              ref={inputRef}
              className="fab-sheet-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
              }}
              placeholder="what's on your mind?"
              rows={3}
            />
            <div className="fab-sheet-actions">
              <span className="fab-sheet-hint">⌘/Ctrl + Enter to send</span>
              <button
                type="button"
                className="fab-sheet-send"
                onClick={submit}
                disabled={busy || !text.trim()}
              >
                {busy ? "sending…" : "send"}
              </button>
            </div>
          </div>
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
