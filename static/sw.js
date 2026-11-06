const CACHE_NAME = "comfort-system-v1";
const STATIC_ASSETS = [
    "/static/manifest.json",
    "/static/css/sidebar.css",
    "/static/css/readability.css",
    "/static/js/base.js",
    "/static/images/icon192.png",
    "/static/images/icon.png",
    "/static/images/icon512.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => Promise.all(
                cacheNames
                    .filter((cacheName) => cacheName.startsWith("comfort-system-")
                        && cacheName !== CACHE_NAME)
                    .map((cacheName) => caches.delete(cacheName))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);

    if (request.method !== "GET" || url.origin !== self.location.origin) {
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(
            fetch(request).catch(() => new Response(
                "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
                + "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                + "<title>Offline - Comfort System</title>"
                + "<body style=\"font:16px system-ui,sans-serif;max-width:38rem;"
                + "margin:12vh auto;padding:1.5rem;color:#243447\">"
                + "<h1>You are offline</h1><p>Reconnect to continue using Comfort System.</p>"
                + "</body></html>",
                {
                    status: 200,
                    headers: { "Content-Type": "text/html; charset=utf-8" },
                }
            ))
        );
        return;
    }

    if (url.pathname.startsWith("/api/")) {
        return;
    }

    event.respondWith(
        caches.match(request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }
            return fetch(request).catch(() => new Response("Offline", { status: 503 }));
        })
    );
});
