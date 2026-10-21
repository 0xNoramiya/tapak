// Small behaviours on top of htmx (no framework).
document.addEventListener("DOMContentLoaded", function () {
  var body = document.body;
  var fieldErrors = false;
  // Error responses (4xx/5xx) carry an Indonesian notice; show it instead of failing silently.
  // Only TAPAK's own notices (retargeted HTML) are swapped, never a raw error body.
  body.addEventListener("htmx:beforeSwap", function (e) {
    var xhr = e.detail.xhr;
    fieldErrors = /field-error/.test(xhr.responseText || "");
    if (xhr.status >= 400) {
      var html = (xhr.getResponseHeader("Content-Type") || "").indexOf("text/html") === 0;
      if (xhr.getResponseHeader("HX-Retarget") || html) {
        e.detail.shouldSwap = true;
        e.detail.isError = false;
      } else {
        showNotice("Permintaan ditolak server (kode " + xhr.status + "). Periksa isian lalu coba lagi.");
      }
    }
  });
  // A new request clears the previous error notice.
  body.addEventListener("htmx:beforeRequest", function () {
    var g = document.getElementById("galat-global");
    if (g) { g.innerHTML = ""; }
  });
  // Move keyboard focus to a result heading marked data-autofocus after it arrives; bring a
  // page-level notice into view, wherever the user had scrolled to.
  body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target.id === "galat-global") { revealNotice(); return; }
    var h = e.detail.target.querySelector("[data-autofocus]");
    if (h) { h.focus({ preventScroll: true }); }
  });
  // Mark fields with an error message as invalid (also after out-of-band error updates, which
  // do not settle a target) and move focus to the first one, so its message is read out.
  function markInvalid() {
    var first = null;
    document.querySelectorAll("[aria-describedby]").forEach(function (el) {
      var ids = el.getAttribute("aria-describedby").split(/\s+/).filter(function (id) { return id.indexOf("err") !== -1; });
      if (!ids.length) { return; }
      var bad = ids.some(function (id) { var n = document.getElementById(id); return n && n.textContent.trim() !== ""; });
      if (bad) { el.setAttribute("aria-invalid", "true"); first = first || el; } else { el.removeAttribute("aria-invalid"); }
    });
    if (first && fieldErrors) {
      fieldErrors = false;
      var d = first.closest("details");
      if (d) { d.open = true; }
      first.focus();
    }
  }
  body.addEventListener("htmx:afterSettle", markInvalid);
  body.addEventListener("htmx:oobAfterSwap", markInvalid);
  // Network failure: say so.
  body.addEventListener("htmx:sendError", function () {
    showNotice("Server TAPAK tidak dapat dihubungi. Periksa apakah layanan berjalan, lalu coba lagi.");
  });
  function showNotice(text) {
    var g = document.getElementById("galat-global");
    if (!g) { return; }
    var d = document.createElement("div");
    d.className = "notice notice-error";
    d.textContent = text;
    g.innerHTML = "";
    g.appendChild(d);
    revealNotice();
  }
  function revealNotice() {
    var g = document.getElementById("galat-global");
    if (!g || !g.textContent.trim()) { return; }
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    g.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    g.focus({ preventScroll: true });
  }
});
