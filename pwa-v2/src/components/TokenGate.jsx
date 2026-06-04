import { useState } from "react";
import { setToken, verifyToken } from "../lib/api";

/**
 * First-run auth screen. Asks the user to paste WEBHOOK_SHARED_SECRET from
 * their .env (same value the iOS Shortcut uses). Verifies by hitting
 * /api/today with the candidate; on success, stores in localStorage and
 * calls onAuthed() so the parent can switch to the app shell.
 */
export default function TokenGate({ onAuthed }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e?.preventDefault?.();
    const t = value.trim();
    if (!t) {
      setError("Paste the token first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const ok = await verifyToken(t);
      if (!ok) {
        setError("Wrong token. Check the WEBHOOK_SHARED_SECRET line in .env.");
        return;
      }
      setToken(t);
      onAuthed();
    } catch (err) {
      setError(`Couldn't reach server: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="token-screen">
      <form className="token-card" onSubmit={submit}>
        <h1>
          PA<em>-Agent</em>
        </h1>
        <p>
          Paste your webhook secret to unlock. It's the value of{" "}
          <code>WEBHOOK_SHARED_SECRET</code> in your <code>.env</code> file.
        </p>
        <input
          type="password"
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck="false"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="WEBHOOK_SHARED_SECRET"
          autoFocus
        />
        <button type="submit" disabled={busy}>
          {busy ? "Checking…" : "Save & continue"}
        </button>
        {error && <p className="token-error">{error}</p>}
      </form>
    </div>
  );
}
