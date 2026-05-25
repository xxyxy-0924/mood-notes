const CACHE_NAME = 'mood-notes-pwa-v12';
const APP_SHELL = [
  '/',
  '/manifest.webmanifest?v=photo5',
  '/static/app-icon-192.png?v=photo5',
  '/static/app-icon-512.png?v=photo5',
  '/static/theme-polish.css?v=skin5',
  '/static/themes/milk-scene.svg?v=skin5',
  '/static/themes/night-scene.svg?v=skin5',
  '/static/themes/blue-scene.svg?v=skin5',
  '/static/themes/berry-scene.svg?v=skin5',
  '/static/splash.svg'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname === '/login') {
    return;
  }

  event.respondWith(
    fetch(request)
      .then(response => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request).then(cached => cached || caches.match('/')))
  );
});
