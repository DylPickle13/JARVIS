const CACHE_VERSION = 'jarvis-dashboard-pwa-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Keep dashboard telemetry live: do not cache API/WebSocket-adjacent requests.
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
