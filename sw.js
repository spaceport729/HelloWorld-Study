// Offline support. Pages and data are fetched fresh when online (so edits made
// in Obsidian show up right away) and served from the cache when offline.
// Bump VERSION to clear old caches.
const VERSION = 'hello-world-v4';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'data/countries.json',
  'data/world-paths.json', 'data/travel.json', 'data/advisories.json', 'data/charts.json', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png'];

self.addEventListener('install', e => {
  // cache each file on its own, so one missing data file can't stop the app from installing
  e.waitUntil(caches.open(VERSION).then(c => Promise.allSettled(SHELL.map(u => c.add(u)))).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const sameSite = url.origin === location.origin;
  const fonts = url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com';
  if (!sameSite && !fonts) return;  // Apple Music links and the like go straight to the network
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok || res.type === 'opaque') {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match(req, {ignoreSearch: true})
      .then(hit => hit || (req.mode === 'navigate' ? caches.match('index.html') : undefined)))
  );
});
