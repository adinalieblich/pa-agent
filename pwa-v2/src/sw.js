/// <reference lib="webworker" />

/**
 * Custom service worker — extends the workbox precache/runtime caching with
 * Web Push handlers.
 *
 * Two handlers added on top of the default vite-plugin-pwa scaffold:
 *
 *   - `push`            → render the notification (title/body/actions/url)
 *   - `notificationclick` → route the click (action button or body) into
 *                           the PWA at a deep link. The PWA handles the
 *                           actual API call so the SW doesn't need the
 *                           X-PA-Token (which lives in localStorage and
 *                           isn't readable here).
 *
 * Payload contract (what the backend sends as JSON in the push body):
 *
 *   {
 *     "title":   "▶ Pay rent",
 *     "body":    "due today · £2,400",
 *     "url":     "/today",          // tapping the body opens this
 *     "tag":     "rent-2026-06-03", // optional dedup tag
 *     "actions": [
 *       { "action": "done",     "title": "Done",   "url": "/today?action=done&id=ABC" },
 *       { "action": "snooze-1", "title": "+1 day", "url": "/today?action=snooze&id=ABC" }
 *     ]
 *   }
 */

import { precacheAndRoute, cleanupOutdatedCaches } from "workbox-precaching";
import { registerRoute } from "workbox-routing";
import { NetworkFirst, CacheFirst } from "workbox-strategies";
import { ExpirationPlugin } from "workbox-expiration";
import { clientsClaim } from "workbox-core";

/* eslint-disable no-restricted-globals */

// --- Precache everything Vite emits ----------------------------------------
self.skipWaiting();
clientsClaim();
precacheAndRoute(self.__WB_MANIFEST || []);
cleanupOutdatedCaches();

// --- Runtime caching: /api/* and Google fonts (matches the old generateSW) -
registerRoute(
  ({ url }) => url.pathname.startsWith("/api/"),
  new NetworkFirst({
    cacheName: "api-cache",
    networkTimeoutSeconds: 4,
    plugins: [
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 }),
    ],
  }),
);

registerRoute(
  ({ url }) =>
    url.origin === "https://fonts.googleapis.com" ||
    url.origin === "https://fonts.gstatic.com",
  new CacheFirst({
    cacheName: "google-fonts",
    plugins: [
      new ExpirationPlugin({ maxEntries: 30, maxAgeSeconds: 60 * 60 * 24 * 365 }),
    ],
  }),
);

// --- Web Push handlers -----------------------------------------------------

self.addEventListener("push", (event) => {
  // No data on the event? Show a generic fallback so the user still sees
  // *something* — silent pushes are a bad UX surprise.
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch {
      data = { title: "PA-Agent", body: event.data.text() };
    }
  }
  const title = data.title || "PA-Agent";
  const opts = {
    body: data.body || "",
    icon: "/pwa-v2/icons/icon-192.png",
    badge: "/pwa-v2/icons/icon-192.png",
    tag: data.tag,
    renotify: !!data.tag,
    data: {
      url: data.url || "/pwa-v2/",
      actions: (data.actions || []).reduce((acc, a) => {
        if (a.action && a.url) acc[a.action] = a.url;
        return acc;
      }, {}),
    },
    actions: (data.actions || []).map((a) => ({
      action: a.action,
      title: a.title,
    })),
  };
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const map = event.notification.data?.actions || {};
  const fallback = event.notification.data?.url || "/pwa-v2/";
  // If the user clicked an action button, prefer that target URL.
  // Otherwise the click was on the body of the notification.
  const targetPath = (event.action && map[event.action]) || fallback;
  // Ensure we always navigate inside the PWA scope.
  const full = targetPath.startsWith("/pwa-v2")
    ? targetPath
    : "/pwa-v2" + (targetPath.startsWith("/") ? targetPath : "/" + targetPath);

  event.waitUntil((async () => {
    const all = await self.clients.matchAll({
      type: "window",
      includeUncontrolled: true,
    });
    // If a PWA window is already open, focus it + navigate.
    for (const client of all) {
      if (client.url.includes("/pwa-v2") && "navigate" in client) {
        await client.navigate(full).catch(() => null);
        return client.focus();
      }
    }
    // Otherwise open a fresh window.
    return self.clients.openWindow(full);
  })());
});
