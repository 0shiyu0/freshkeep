/* 鲜度 FreshKeep · Service Worker（阶段 9）
原则：库存与金额数据绝不离线写入，也绝不缓存 API 响应。
- /api/ 请求一律 network-only（离线时前端自己报错，不让用户误以为数据已保存）
- 页面导航 network-first，失败回退离线基础页
- 带 hash 的构建产物 cache-first；其余静态资源 stale-while-revalidate
*/
var VERSION = 'freshkeep-v2';
var SHELL = [
  '/', '/index.html', '/offline.html',
  '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(VERSION).then(function (c) {
      return Promise.all(SHELL.map(function (u) {
        return c.add(new Request(u, { cache: 'reload' })).catch(function () { return null; });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== VERSION; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('message', function (e) {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

function offlineResponse() {
  return caches.match('/offline.html').then(function (r) {
    return r || new Response('<h1>离线中</h1>', { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
  });
}

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;                       // 写操作完全不拦截
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;        // 跨域不拦截
  if (url.pathname.indexOf('/api/') === 0 || url.pathname === '/health') return; // 数据必须实时

  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(VERSION).then(function (c) { c.put('/index.html', copy); });
        return res;
      }).catch(offlineResponse)
    );
    return;
  }

  if (url.pathname.indexOf('/assets/') === 0) {
    e.respondWith(
      caches.match(req).then(function (hit) {
        return hit || fetch(req).then(function (res) {
          if (res.ok) { var copy = res.clone(); caches.open(VERSION).then(function (c) { c.put(req, copy); }); }
          return res;
        });
      })
    );
    return;
  }

  e.respondWith(
    caches.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        if (res.ok) { var copy = res.clone(); caches.open(VERSION).then(function (c) { c.put(req, copy); }); }
        return res;
      }).catch(function () { return hit || offlineResponse(); });
      return hit || net;
    })
  );
});
