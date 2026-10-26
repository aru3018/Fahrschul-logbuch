// Minimaler Service Worker – nur nötig, damit der Browser "Zum
// Homescreen hinzufügen" anbietet. Kein Offline-Caching, da die App
// Live-Daten aus der DB braucht und ein Demo-Prototyp ist.
self.addEventListener("install", () => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
    // Bewusst kein Caching – immer frisch vom Server laden.
});
