/* Study Planet service worker — on-device storage for uploaded backgrounds.
 *
 * SCOPE IS DELIBERATELY TINY. This worker answers requests for /media/backgrounds/ and
 * nothing else; every other request is left alone, so the browser fetches pages, scripts and
 * API calls exactly as it would with no worker installed.
 *
 * That restraint is the whole design. server.py sends the pages with "Cache-Control:
 * no-cache" precisely because clients -- the Android WebView above all -- will otherwise
 * invent a freshness window and serve a stale copy for hours, so a deploy silently never
 * arrives. A worker that cached the app shell would reintroduce exactly that bug, in a form
 * that outlives a reload and cannot be cleared by the user. So it does not cache the shell.
 *
 * Backgrounds are the one thing here that is safely cacheable forever: the filename is a
 * random token minted at upload, so changing a background produces a NEW url rather than new
 * bytes at the old one. A cached entry can therefore never be stale -- only unused.
 *
 * Not cached: the ambient soundtracks. They are served from a third-party host and storing
 * them would need `connect-src` widened to reach it. On the web they stream; the Android app
 * already keeps its own copies through the native music service, which is what the
 * "Saved on your phone after the first play" hint refers to.
 */
var CACHE = "study-planet-bg-v1";
var PREFIX = "/media/backgrounds/";
var MAX_ENTRIES = 20;          // ~20 images; enough for the whole admin gallery, bounded

self.addEventListener("install", function (e) {
  self.skipWaiting();          // a new worker takes over on the next load, not the next close
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== CACHE) return caches.delete(k);   // drop caches from an older version
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;
  var url;
  try { url = new URL(req.url); } catch (err) { return; }
  // Same-origin backgrounds only. Returning without calling respondWith() hands the request
  // back to the browser untouched -- that is the path almost everything takes.
  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf(PREFIX) !== 0) return;
  e.respondWith(cacheFirst(req));
});

function cacheFirst(req) {
  return caches.open(CACHE).then(function (cache) {
    return cache.match(req).then(function (hit) {
      if (hit) return hit;                       // already on the device: no network at all
      return fetch(req).then(function (res) {
        // Only store a real, complete response. A 206 (range) or an error page cached here
        // would be served back forever, since these urls never change.
        if (res && res.status === 200 && res.type === "basic") {
          cache.put(req, res.clone()).then(function () { trim(cache); }).catch(function () {});
        }
        return res;
      });
    });
  });
}

/* Oldest-first eviction. Cache Storage keeps insertion order, so the front of keys() is the
   least recently added -- good enough to bound how much of someone's phone this occupies. */
function trim(cache) {
  return cache.keys().then(function (keys) {
    if (keys.length <= MAX_ENTRIES) return;
    return Promise.all(keys.slice(0, keys.length - MAX_ENTRIES).map(function (k) {
      return cache.delete(k);
    }));
  }).catch(function () {});
}
