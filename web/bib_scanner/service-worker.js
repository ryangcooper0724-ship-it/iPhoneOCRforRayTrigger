"use strict";

/* オフライン運用のための完全キャッシュ。インストール時に全アセットを取得し、
   以降はキャッシュ優先で返す（現地でESP32 Wi-Fiに繋いだ後はインターネットが
   無い前提のため、CDNフェッチに頼らず同一オリジンの資産だけで完結させる）。 */
const CACHE_NAME = "bib-scanner-v2";
const ASSETS = [
  "./",
  "./index.html",
  "./app.js",
  "./manifest.json",
  "./icon-192.png",
  "./raytrigocr-ca.crt",
  "./vendor/tesseract/tesseract.min.js",
  "./vendor/tesseract/worker.min.js",
  "./vendor/tesseract/tesseract-core-simd.wasm.js",
  "./vendor/tesseract/tesseract-core-simd.wasm",
  "./vendor/tesseract/eng.traineddata.gz",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // ESP32へのPOST等、同一オリジン外（=ローカルネットワーク上の別ホスト）の
  // リクエストはキャッシュ対象外で素通しする。
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
