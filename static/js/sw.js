// Service worker for reminder notifications (models/push.py sends them). Served at /sw.js so it
// covers the whole site. A tap opens the reminder's link, which records the tap and leads to the lobby.
self.addEventListener('push', function(event) {
    var data = {};
    try { data = event.data ? event.data.json() : {}; } catch (e) {}
    event.waitUntil(self.registration.showNotification(data.title || 'Reminder', {
        body: data.body || '',
        tag: data.tag,
        data: { url: data.url },
    }));
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    var url = event.notification.data && event.notification.data.url;
    if (url) event.waitUntil(clients.openWindow(url));
});
