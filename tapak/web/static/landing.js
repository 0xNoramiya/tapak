// Landing page (/): the evidence bars grow once when they come into view. Without JavaScript,
// or with reduced motion, they are simply drawn at their value (landing.css).
(function () {
  "use strict";
  if (!("IntersectionObserver" in window)) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var lists = document.querySelectorAll(".ld-bars");
  if (!lists.length) return;
  document.documentElement.classList.add("ld-animate");
  var seen = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.classList.add("is-visible");
      seen.unobserve(e.target);
    });
  }, { threshold: 0.25 });
  lists.forEach(function (el) { seen.observe(el); });
})();
