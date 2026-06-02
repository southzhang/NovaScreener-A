// V10 量化选股 — Service Worker
const CACHE_NAME = 'v10-quant-v1';
const STATIC_ASSETS = [
  '/static/icons/icon.svg',
  '/static/manifest.json',
];

// 安装：缓存静态资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// 激活：清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

// 请求拦截：网络优先，缓存备用
self.addEventListener('fetch', (event) => {
  // 只缓存GET请求
  if (event.request.method !== 'GET') return;

  // 静态资源用缓存优先
  if (event.request.url.includes('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request);
      })
    );
    return;
  }

  // 其他请求：网络优先
  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});
