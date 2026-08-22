/* Progressive enhancement only — every page works with JS disabled. */
(function () {
  "use strict";

  var toastEl = document.getElementById("toast");
  var toastTimer = null;

  function toast(msg, ms) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.classList.remove("show");
    }, ms || 2600);
  }

  /* ── save / unsave ─────────────────────────────────────────── */
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".save");
    if (!btn) return;
    ev.preventDefault();
    var id = btn.dataset.id;
    btn.disabled = true;
    fetch("/api/save/" + id, { method: "POST" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        btn.classList.toggle("on", d.saved);
        btn.textContent = d.saved ? "★" : "☆";
        btn.title = d.saved ? "Saved" : "Save";
        toast(d.saved ? "Saved" : "Removed from saved");
      })
      .catch(function () { toast("Could not save — is the server still up?"); })
      .finally(function () { btn.disabled = false; });
  });

  /* ── manual refresh + progress polling ─────────────────────── */
  var refreshBtn = document.getElementById("refresh");
  var dot = document.getElementById("statusdot");
  var lastRun = document.getElementById("lastrun");
  var polling = false;

  function poll() {
    if (polling) return;
    polling = true;
    var tick = setInterval(function () {
      fetch("/api/status")
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.run && d.run.running) return;
          clearInterval(tick);
          polling = false;
          if (dot) dot.classList.remove("busy");
          if (lastRun) lastRun.textContent = d.stats.last_run;
          if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = "Refresh";
          }
          toast("Refresh complete — reloading", 1500);
          setTimeout(function () { location.reload(); }, 900);
        })
        .catch(function () {
          clearInterval(tick);
          polling = false;
        });
    }, 4000);
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      refreshBtn.disabled = true;
      refreshBtn.textContent = "Refreshing…";
      if (dot) dot.classList.add("busy");
      fetch("/api/refresh", { method: "POST" })
        .then(function (r) {
          if (r.status === 409) { toast("A refresh is already running"); }
          else { toast("Ingest started — this can take a few minutes"); }
          poll();
        })
        .catch(function () {
          toast("Could not reach the server");
          refreshBtn.disabled = false;
          refreshBtn.textContent = "Refresh";
        });
    });
    // A run kicked off elsewhere (CLI, systemd timer) should still update here.
    if (refreshBtn.disabled) { if (dot) dot.classList.add("busy"); poll(); }
  }

  /* ── keyboard shortcuts ────────────────────────────────────── */
  document.addEventListener("keydown", function (ev) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (typing || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    var go = { d: "/", f: "/feed", s: "/search", b: "/saved", h: "/sources", r: "/runs" };
    if (go[ev.key]) { location.href = go[ev.key]; return; }
    if (ev.key === "/") {
      ev.preventDefault();
      var box = document.querySelector('input[type=search]');
      if (box) box.focus(); else location.href = "/search";
    }
  });
})();
