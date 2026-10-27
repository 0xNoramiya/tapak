// Landing page (/): the evidence bars grow, and each [data-reveal] block tells its part once,
// when it comes into view (landing.css). Without JavaScript, or with reduced motion, they are
// simply drawn in place.
(function () {
  "use strict";
  if (!("IntersectionObserver" in window)) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var blocks = document.querySelectorAll(".ld-bars, [data-reveal]");
  if (!blocks.length) return;
  document.documentElement.classList.add("ld-animate");
  // In view: a third of the block, or half the window for a block taller than the window
  // (which may never be a third visible on a phone).
  var seen = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.intersectionRatio < 0.3 && e.intersectionRect.height < window.innerHeight / 2) return;
      e.target.classList.add("is-visible");
      seen.unobserve(e.target);
    });
  }, { threshold: [0, 0.1, 0.2, 0.3, 0.5] });
  blocks.forEach(function (el) { seen.observe(el); });
})();
