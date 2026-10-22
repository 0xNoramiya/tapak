// Small behaviours on top of htmx (no framework).
document.addEventListener("DOMContentLoaded", function () {
  var body = document.body;
  var root = document.documentElement;
  var fieldErrors = false;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var busyCount = 0;

  // htmx passes its own scroll behaviour to scrollIntoView (show:#hasil:top), which the CSS
  // reduced-motion rule cannot override: follow the setting here.
  function syncScroll() { if (window.htmx) { htmx.config.scrollBehavior = reduceMotion.matches ? "auto" : "smooth"; } }
  syncScroll();
  if (reduceMotion.addEventListener) { reduceMotion.addEventListener("change", syncScroll); }

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

  // A new request clears the previous error notice and the requesting form's field errors (a
  // fixed field must not keep its message after a successful submit). Its submit button shows
  // a loading state. The bar at the top of the window shows only for a request that has no
  // indicator of its own (a spinner or busy bar inside the element, or loading text).
  body.addEventListener("htmx:beforeRequest", function (e) {
    if (e.detail.elt.hasAttribute("data-quiet")) { return; }  // background refresh
    var g = document.getElementById("galat-global");
    if (g) { g.innerHTML = ""; }
    var form = e.detail.elt;
    if (form && form.querySelectorAll) {
      form.querySelectorAll('[id^="err-"], [id$="-err"]').forEach(function (n) { n.innerHTML = ""; });
      markInvalid();
    }
    loadingButtons(e.detail.elt).forEach(startLoading);
    // The busy line only appears once the request runs, too late to be announced as a live
    // region of its own, and the disabled button has lost focus: say it in the page's region.
    var busy = form && form.querySelector ? form.querySelector(".busy") : null;
    if (!busy && form && form.matches && form.matches(".lacak-form")) { busy = document.querySelector(".lacak-sibuk"); }
    if (busy) { announce(shownText(busy).replace(/\s+/g, " ").trim()); }
    if (!hasOwnIndicator(e.detail.elt)) {
      e.detail.xhr.tapakBusy = true;
      busyCount += 1;
      root.classList.add("is-busy");
    }
  });
  body.addEventListener("htmx:afterRequest", function (e) {
    if (e.detail.elt.hasAttribute("data-quiet")) { return; }
    loadingButtons(e.detail.elt).forEach(stopLoading);
    if (!e.detail.xhr || !e.detail.xhr.tapakBusy) { return; }
    busyCount = Math.max(0, busyCount - 1);
    if (!busyCount) { root.classList.remove("is-busy"); }
  });
  // The text of a busy line as it will show: parts that CSS hides for the current choice (the
  // scanned-page line of Lacak) are left out. The line itself is still hidden at this point,
  // so each part is judged by its own computed display.
  function shownText(el) {
    var out = "";
    Array.prototype.forEach.call(el.childNodes, function (n) {
      if (n.nodeType === 3) { out += n.nodeValue; }
      else if (n.nodeType === 1 && getComputedStyle(n).display !== "none") { out += shownText(n); }
    });
    return out;
  }
  function hasOwnIndicator(elt) {
    if (!elt || !elt.matches) { return false; }
    return elt.matches("[data-loading-text]") || !!elt.querySelector(".htmx-indicator");
  }

  function loadingButtons(elt) {
    if (!elt || !elt.matches) { return []; }
    if (elt.matches("[data-loading-text]")) { return [elt]; }
    if (elt.tagName === "FORM") { return Array.prototype.slice.call(elt.querySelectorAll('button[type="submit"]')); }
    return [];
  }
  function startLoading(btn) {
    btn.setAttribute("data-loading", "");
    var text = btn.getAttribute("data-loading-text");
    if (text && !btn.querySelector(".idle-label")) {
      btn.setAttribute("data-idle-html", btn.innerHTML);
      btn.textContent = text;
    }
  }
  function stopLoading(btn) {
    btn.removeAttribute("data-loading");
    var idle = btn.getAttribute("data-idle-html");
    if (idle !== null) {
      btn.innerHTML = idle;
      btn.removeAttribute("data-idle-html");
    }
  }

  // Move keyboard focus to a result heading marked data-autofocus after it arrives; bring a
  // page-level notice into view, wherever the user had scrolled to. New content of a step or
  // result container fades in (not the review list, which re-renders on every decision).
  var ENTER_TARGETS = ["alur", "hasil", "merkle", "galat-global"];
  body.addEventListener("htmx:afterSwap", function (e) {
    var target = e.detail.target;
    if (ENTER_TARGETS.indexOf(target.id) !== -1 || target.hasAttribute("data-enter")) { enter(target.children); }
    if (target.id === "galat-global") { revealNotice(); return; }
    var h = target.querySelector("[data-autofocus]");
    if (h) {
      h.focus({ preventScroll: true });
      // A heading the swap left above or below the window is brought into view (below the
      // sticky banner, through scroll-padding-top), so the focus ring is seen.
      var r = h.getBoundingClientRect();
      if (r.top < parseFloat(getComputedStyle(root).scrollPaddingTop) || r.bottom > window.innerHeight) {
        h.scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
      }
    }
  });
  function enter(nodes) {
    if (reduceMotion.matches || !Element.prototype.animate) { return; }
    Array.prototype.forEach.call(nodes, function (el, i) {
      el.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }],
                 { duration: 180, delay: Math.min(i, 4) * 40, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" });
    });
  }

  // Mark fields with an error message as invalid (also after out-of-band error updates, which
  // do not settle a target) and move focus to the first one, so its message is read out.
  // A newly reported error is never left in a closed disclosure (it would be found only after
  // the visible ones are fixed); each out-of-band slot arrives separately, so this is done per
  // field as it turns invalid, and again for all of them when focus moves.
  function markInvalid() {
    var first = null;
    document.querySelectorAll("[aria-describedby]").forEach(function (el) {
      var ids = el.getAttribute("aria-describedby").split(/\s+/).filter(function (id) { return id.indexOf("err") !== -1; });
      if (!ids.length) { return; }
      var bad = ids.some(function (id) { var n = document.getElementById(id); return n && n.textContent.trim() !== ""; });
      if (bad) {
        if (el.getAttribute("aria-invalid") !== "true") { openDisclosure(el); }
        el.setAttribute("aria-invalid", "true");
        first = first || el;
      } else {
        el.removeAttribute("aria-invalid");
      }
    });
    if (first && fieldErrors) {
      fieldErrors = false;
      document.querySelectorAll('[aria-invalid="true"]').forEach(openDisclosure);
      first.focus();
    }
  }
  function openDisclosure(el) {
    var d = el.closest("details");
    if (d) { d.open = true; }
  }
  body.addEventListener("htmx:afterSettle", markInvalid);
  body.addEventListener("htmx:oobAfterSwap", markInvalid);

  // A request's button is disabled while it runs, which sends focus to <body>; when the swap
  // brings no heading to focus, put it back on the button (if it survived the swap) or on the
  // target's [data-focus-fallback], so the next Tab continues from there, not from the top.
  body.addEventListener("htmx:afterSettle", function (e) {
    if (document.activeElement && document.activeElement !== body) { return; }
    var src = e.detail.requestConfig && e.detail.requestConfig.elt;
    if (!src || src.hasAttribute("data-quiet") || e.detail.target.id === "galat-global") { return; }
    var btn = src.tagName === "FORM" ? src.querySelector('button[type="submit"]') : src;
    if (btn && btn.isConnected && !btn.disabled) { btn.focus(); return; }
    var f = e.detail.target.querySelector("[data-focus-fallback]");
    if (f) { f.focus(); }
  });

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
    enter(g.children);
    revealNotice();
  }
  function revealNotice() {
    var g = document.getElementById("galat-global");
    if (!g || !g.textContent.trim()) { return; }
    g.scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
    g.focus({ preventScroll: true });
  }
  function announce(text) {
    var s = document.getElementById("status-global");
    if (!s) { return; }
    s.textContent = "";
    window.setTimeout(function () { s.textContent = text; }, 50);
  }

  // Drop zones: <label class="dropzone" data-dropzone> around a real file input. The input
  // covers the zone, so clicking, the keyboard and dropping work natively; this adds the
  // drag-over state and lists the chosen files with their sizes.
  function zoneOf(node) { return node && node.closest ? node.closest("[data-dropzone]") : null; }
  function formatSize(bytes) {
    var units = ["B", "kB", "MB", "GB"];
    var i = 0;
    var n = bytes;
    while (n >= 1000 && i < units.length - 1) { n /= 1000; i += 1; }
    var digits = i === 0 || n >= 100 ? 0 : 1;
    return n.toFixed(digits).replace(".", ",") + " " + units[i];
  }
  function renderFiles(zone) {
    var input = zone.querySelector('input[type="file"]');
    if (!input) { return; }
    var list = zone.querySelector("[data-dropzone-files]");
    if (!list) {
      list = document.createElement("ul");
      list.className = "dropzone-files";
      list.setAttribute("data-dropzone-files", "");
      zone.appendChild(list);
    }
    list.innerHTML = "";
    Array.prototype.forEach.call(input.files || [], function (f) {
      var li = document.createElement("li");
      var name = document.createElement("span");
      name.className = "file-name";
      name.textContent = f.name;
      name.title = f.name;
      var size = document.createElement("span");
      size.className = "file-size";
      size.textContent = formatSize(f.size);
      li.appendChild(name);
      li.appendChild(size);
      list.appendChild(li);
    });
    zone.classList.toggle("has-files", !!(input.files && input.files.length));
  }
  function initZones(scope) {
    (scope || document).querySelectorAll("[data-dropzone]").forEach(renderFiles);
  }
  document.addEventListener("change", function (e) {
    var zone = zoneOf(e.target);
    if (zone && e.target.type === "file") {
      renderFiles(zone);
      var slot = errorSlot(e.target);  // a new choice replaces the drop message
      if (slot && slot.querySelector("[data-drop-error]")) { slot.innerHTML = ""; markInvalid(); }
    }
    var img = e.target.id ? document.querySelectorAll('[data-preview-from="#' + e.target.id + '"]') : [];
    Array.prototype.forEach.call(img, updatePreview);
  });
  var dragDepth = new WeakMap();
  document.addEventListener("dragenter", function (e) {
    var zone = zoneOf(e.target);
    if (!zone) { return; }
    dragDepth.set(zone, (dragDepth.get(zone) || 0) + 1);
    zone.classList.add("is-dragover");
  });
  document.addEventListener("dragleave", function (e) {
    var zone = zoneOf(e.target);
    if (!zone) { return; }
    var depth = (dragDepth.get(zone) || 1) - 1;
    dragDepth.set(zone, depth);
    if (depth <= 0) { zone.classList.remove("is-dragover"); }
  });
  // A file dropped beside a zone must not replace the page (and the form) with the file.
  function draggingFiles(e) {
    return !!(e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") !== -1);
  }
  document.addEventListener("dragover", function (e) {
    if (!zoneOf(e.target) && draggingFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "none"; }
  });
  document.addEventListener("drop", function (e) {
    var zone = zoneOf(e.target);
    if (!zone) { if (draggingFiles(e)) { e.preventDefault(); } return; }
    dragDepth.set(zone, 0);
    zone.classList.remove("is-dragover");
    // The native drop onto the covering input fills it and fires "change". A drop on the
    // zone's border (outside the input box) is copied over here.
    var input = zone.querySelector('input[type="file"]');
    if (!input || !e.dataTransfer || !e.dataTransfer.files.length) { return; }
    // Several files on a zone that takes one: keep the current choice and say why.
    if (!input.multiple && e.dataTransfer.files.length > 1) {
      e.preventDefault();
      dropError(input, "Pilih satu berkas.");
      return;
    }
    if (e.target !== input) {
      e.preventDefault();
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
  // The error slot of a file input is the "err" id in its aria-describedby.
  function errorSlot(input) {
    var ids = (input.getAttribute("aria-describedby") || "").split(/\s+/);
    for (var i = 0; i < ids.length; i += 1) {
      if (ids[i].indexOf("err") !== -1 && document.getElementById(ids[i])) { return document.getElementById(ids[i]); }
    }
    return null;
  }
  function dropError(input, text) {
    var slot = errorSlot(input);
    if (!slot) { announce(text); return; }
    var msg = document.createElement("span");
    msg.className = "field-error";
    msg.setAttribute("data-drop-error", "");
    msg.textContent = text;
    slot.innerHTML = "";
    slot.appendChild(msg);
    markInvalid();
    announce(text);
  }

  // Copy buttons: data-copy="text" or data-copy-target="#id" (copies the element's text).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-copy], [data-copy-target]") : null;
    if (!btn) { return; }
    var text = btn.getAttribute("data-copy");
    if (text === null) {
      var src = document.querySelector(btn.getAttribute("data-copy-target"));
      text = src ? src.textContent.trim() : "";
    }
    copyText(text).then(function () {
      var label = btn.querySelector(".copy-label");
      if (label && !btn.hasAttribute("data-copied")) { btn.setAttribute("data-label", label.textContent); }
      btn.setAttribute("data-copied", "");
      if (label) { label.textContent = "Tersalin"; }
      announce("Disalin ke papan klip.");
      window.clearTimeout(btn._copyTimer);
      btn._copyTimer = window.setTimeout(function () {
        btn.removeAttribute("data-copied");
        if (label) { label.textContent = btn.getAttribute("data-label") || "Salin"; }
      }, 1500);
    }, function () {
      announce("Gagal menyalin. Pilih teksnya lalu salin manual.");
    });
  });
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) { return navigator.clipboard.writeText(text); }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      document.body.removeChild(ta);
      if (ok) { resolve(); } else { reject(); }
    });
  }

  // <img data-preview-from="#dokumen" data-preview-src="/dokumen/{}/pratinjau.png">: the
  // thumbnail follows the selected document.
  function updatePreview(img) {
    var sel = document.querySelector(img.getAttribute("data-preview-from"));
    if (!sel || !sel.value) { return; }
    // An option's data-pratinjau names its thumbnail URL; empty means none (a DOCX master),
    // so no request is made. Without it, data-preview-src is a pattern for the value.
    var opt = sel.options ? sel.options[sel.selectedIndex] : null;
    var src;
    if (opt && opt.hasAttribute("data-pratinjau")) {
      src = opt.getAttribute("data-pratinjau");
    } else {
      var pattern = img.getAttribute("data-preview-src");
      if (!pattern) { return; }
      src = pattern.replace("{}", encodeURIComponent(sel.value));
    }
    if (!src) { img.removeAttribute("src"); return; }
    // A thumbnail that fails to load shows blank paper instead of a broken image.
    img.onerror = function () { img.style.visibility = "hidden"; };
    img.onload = function () { img.style.visibility = ""; };
    if (img.getAttribute("src") !== src) { img.setAttribute("src", src); }
  }

  function initPreviews(scope) {
    (scope || document).querySelectorAll("[data-preview-from]").forEach(updatePreview);
  }

  initZones(document);
  initPreviews(document);
  body.addEventListener("htmx:afterSettle", function (e) {
    initZones(e.detail.target);
    initPreviews(e.detail.target);
  });
});
