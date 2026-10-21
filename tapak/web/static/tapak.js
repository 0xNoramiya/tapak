// Small behaviours on top of htmx (no framework).
document.addEventListener("DOMContentLoaded", function () {
  var body = document.body;
  // Error responses (4xx/5xx) carry an Indonesian notice; show it instead of failing silently.
  body.addEventListener("htmx:beforeSwap", function (e) {
    if (e.detail.xhr.status >= 400) {
      e.detail.shouldSwap = true;
      e.detail.isError = false;
    }
  });
  // A new request clears the previous error notice.
  body.addEventListener("htmx:beforeRequest", function () {
    var g = document.getElementById("galat-global");
    if (g) { g.innerHTML = ""; }
  });
  // Move keyboard focus to a result heading marked data-autofocus after it arrives.
  body.addEventListener("htmx:afterSwap", function (e) {
    var h = e.detail.target.querySelector("[data-autofocus]");
    if (h) { h.focus({ preventScroll: true }); }
  });
  // Network failure: say so.
  body.addEventListener("htmx:sendError", function () {
    var g = document.getElementById("galat-global");
    if (g) { g.innerHTML = '<div class="notice notice-error">Server TAPAK tidak dapat dihubungi. Periksa apakah layanan berjalan, lalu coba lagi.</div>'; }
  });
});
