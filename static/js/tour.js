// First-visit tours built on Driver.js (loaded from the CDN by the page).
//
// startTour(steps, options) dims the page and walks through `steps`, each
// {element: CSS selector or null for a centered message, title, text}.
// Steps whose element isn't on the page (or is hidden) are skipped, so one
// list works for every state of the page. When the tour is closed or
// finished, options.seenUrl is POSTed so it doesn't start again on its own.
(function () {
    function isShown(selector) {
        var el = document.querySelector(selector);
        return el && el.getClientRects().length > 0;
    }

    window.startTour = function (steps, options) {
        options = options || {};
        if (!window.driver || !window.driver.js) return;
        var available = steps.filter(function (s) { return !s.element || isShown(s.element); });
        if (!available.length) return;

        var tour = window.driver.js.driver({
            showProgress: available.length > 1,
            progressText: '{{current}} of {{total}}',
            nextBtnText: 'Next',
            prevBtnText: 'Back',
            doneBtnText: 'Got it',
            stagePadding: 6,
            stageRadius: 8,
            popoverClass: 'app-tour',
            steps: available.map(function (s) {
                return { element: s.element || undefined, popover: { title: s.title, description: s.text } };
            }),
            onDestroyed: function () {
                if (options.seenUrl) {
                    fetch(options.seenUrl, { method: 'POST', credentials: 'same-origin' }).catch(function () {});
                }
            }
        });
        tour.drive();
    };

    // <a data-tour-replay> links restart the page's tour
    document.addEventListener('click', function (e) {
        var link = e.target.closest('[data-tour-replay]');
        if (link && window.pageTour) {
            e.preventDefault();
            window.pageTour(false);
        }
    });
})();
