import { api } from "./api";

/**
 * Web Push enrolment helper.
 *
 * Workflow:
 *
 *   1. enablePush() asks the browser for notification permission,
 *      registers the SW (already running via vite-plugin-pwa), grabs a
 *      PushSubscription with the server's VAPID public key, and POSTs
 *      the subscription JSON to /api/push/subscribe.
 *
 *   2. disablePush() reverses the flow: unsubscribes from the browser
 *      and tells the server to drop the record.
 *
 *   3. getPushStatus() is for the UI — returns whether we're already
 *      subscribed without prompting.
 *
 * iOS Safari Web Push requires the PWA to be **installed to home
 * screen** AND on iOS 16.4+ before any of this works. We surface
 * actionable error messages so the user knows what to do.
 */

function urlBase64ToUint8Array(base64String) {
  // Push subscriptions need a Uint8Array of the VAPID public key, not the
  // base64 string. Pad and decode.
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

function isSupported() {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export async function getPushStatus() {
  if (!isSupported()) return { supported: false, subscribed: false };
  // Wait for the ACTIVE SW — `getRegistration()` can resolve with an
  // installing/waiting SW whose pushManager hasn't yet inherited the
  // subscription, causing false "not subscribed" reads after auto-update
  // SW swaps. `ready` only resolves once the SW is activated.
  let reg;
  try {
    reg = await navigator.serviceWorker.ready;
  } catch {
    return { supported: true, subscribed: false };
  }
  const sub = await reg.pushManager.getSubscription();
  return {
    supported: true,
    subscribed: !!sub,
    permission: Notification.permission,
  };
}

export async function enablePush(label) {
  if (!isSupported()) {
    throw new Error(
      "Push isn't supported here. Add the PWA to your iPhone home screen and open it from there.",
    );
  }
  // Pre-warm the SW + VAPID key BEFORE requesting permission. iOS Safari
  // is strict about user-gesture chains: doing an HTTP fetch between
  // requestPermission() and pushManager.subscribe() can cause subscribe()
  // to fail with NotAllowedError because the user-gesture token has
  // expired by the time we call it.
  const reg = await navigator.serviceWorker.ready;
  const { key } = await api("/api/push/vapid-public-key");
  if (!key) {
    throw new Error(
      "Server isn't configured for Web Push yet (no VAPID key).",
    );
  }
  // Ask permission (only does anything the first time).
  const perm = await Notification.requestPermission();
  if (perm !== "granted") {
    throw new Error(
      perm === "denied"
        ? "Notification permission was blocked. Toggle it back on in iOS Settings → PA-Agent."
        : "Notifications need permission to work.",
    );
  }
  // Subscribe — immediately after permission, no awaits in between.
  let sub;
  try {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
  } catch (e) {
    // Log the actual DOMException so we can debug from console.
    // (NotAllowedError / InvalidStateError are the iOS-typical failures.)
    // eslint-disable-next-line no-console
    console.error("[push] pushManager.subscribe failed:", e?.name, e?.message, e);
    throw new Error(
      `Couldn't subscribe (${e?.name || "error"}). Force-quit the PWA and try again.`,
    );
  }
  // POST to /api/push/subscribe
  const json = sub.toJSON();
  await api("/api/push/subscribe", {
    method: "POST",
    body: JSON.stringify({ ...json, label: label || deviceLabel() }),
  });
  return sub;
}

export async function disablePush() {
  if (!isSupported()) return false;
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return false;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return false;
  try {
    await api(
      `/api/push/subscribe?endpoint=${encodeURIComponent(sub.endpoint)}`,
      { method: "DELETE" },
    );
  } catch {
    // If the server side fails we still want to unsubscribe locally —
    // the next broadcast prune will clean up.
  }
  return sub.unsubscribe();
}

export async function sendTestPush() {
  return api("/api/push/test", { method: "POST" });
}

function deviceLabel() {
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad/.test(ua)) return "iPhone / iPad";
  if (/Android/.test(ua)) return "Android";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows";
  return "browser";
}
