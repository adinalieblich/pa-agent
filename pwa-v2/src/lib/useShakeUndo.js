import { useEffect, useRef } from "react";

/**
 * Shake-to-undo gesture hook.
 *
 * Listens for `devicemotion` while ``active`` is true and fires ``onShake``
 * once when a sudden acceleration burst is detected. Designed to be
 * activated for a short window (e.g. while an undo toast is visible).
 *
 * iOS 13+ requires permission via :func:`requestMotionPermission` — call
 * that from a user gesture (e.g. the tap that triggered the action) before
 * relying on this hook. If permission was denied or unsupported, the hook
 * silently does nothing and the UI falls back to the tap-button undo path.
 *
 * Tuning:
 *   - ``threshold`` is the acceleration delta (m/s²) per sample that
 *     counts as a "shake spike". 12-15 works well for a deliberate flick.
 *   - ``cooldownMs`` prevents a single shake from firing the callback
 *     multiple times in quick succession.
 */
export function useShakeUndo(active, onShake, {
  threshold = 14,
  cooldownMs = 800,
} = {}) {
  const lastFireRef = useRef(0);
  const lastAccelRef = useRef(null);

  useEffect(() => {
    if (!active) return;
    if (typeof window === "undefined") return;
    if (!("DeviceMotionEvent" in window)) return;

    const handler = (e) => {
      const a = e.accelerationIncludingGravity || e.acceleration;
      if (!a || a.x == null || a.y == null || a.z == null) return;
      const now = Date.now();
      const last = lastAccelRef.current;
      lastAccelRef.current = { x: a.x, y: a.y, z: a.z };
      if (!last) return;
      const dx = a.x - last.x;
      const dy = a.y - last.y;
      const dz = a.z - last.z;
      const delta = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (delta > threshold && now - lastFireRef.current > cooldownMs) {
        lastFireRef.current = now;
        try { onShake(); } catch {/* swallow */}
      }
    };

    window.addEventListener("devicemotion", handler, { passive: true });
    return () => window.removeEventListener("devicemotion", handler);
  }, [active, onShake, threshold, cooldownMs]);
}

const PERM_KEY = "pa.motion";

/**
 * Ask iOS for DeviceMotion permission. Must be invoked inside a user-gesture
 * event handler (click, tap). Returns true if motion is available, false
 * otherwise. Caches the result in localStorage so we never prompt twice.
 *
 * On non-iOS browsers (Android Chrome, desktop), permission is implicit
 * and we return true immediately.
 */
export async function requestMotionPermission() {
  try {
    const cached = localStorage.getItem(PERM_KEY);
    if (cached) return cached === "granted";
  } catch {/* localStorage disabled */}

  if (typeof window === "undefined" || !("DeviceMotionEvent" in window)) {
    try { localStorage.setItem(PERM_KEY, "denied"); } catch {}
    return false;
  }

  const reqFn = window.DeviceMotionEvent?.requestPermission;
  if (typeof reqFn !== "function") {
    // Older iOS / Android / desktop — no explicit grant needed.
    try { localStorage.setItem(PERM_KEY, "granted"); } catch {}
    return true;
  }

  try {
    const result = await reqFn.call(window.DeviceMotionEvent);
    try { localStorage.setItem(PERM_KEY, result); } catch {}
    return result === "granted";
  } catch {
    try { localStorage.setItem(PERM_KEY, "denied"); } catch {}
    return false;
  }
}

/** Has the user been asked for motion permission this session? */
export function motionPermissionCached() {
  try {
    return localStorage.getItem(PERM_KEY);
  } catch {
    return null;
  }
}
