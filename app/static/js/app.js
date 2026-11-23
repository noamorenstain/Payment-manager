// Payment Manager client script. Vanilla JS, no external requests, no inline handlers (strict CSP).
"use strict";

(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = meta ? meta.getAttribute("content") : "";

  // ------------------------------------------------------------ CSRF
  window.pmFetch = function (url, options) {
    const opts = Object.assign({ credentials: "same-origin" }, options || {});
    opts.headers = Object.assign({ "X-CSRF-Token": csrfToken }, opts.headers || {});
    return fetch(url, opts);
  };

  function ensureToken(form) {
    if (!form.querySelector('input[name="csrf_token"]')) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "csrf_token";
      input.value = csrfToken;
      form.appendChild(input);
    }
  }

  // ------------------------------------------------------------ forms: confirm + no double submit
  document.addEventListener("submit", function (event) {
    const form = event.target;
    // getAttribute, not form.method: a field named "method" (payment forms) shadows that property
    if (!(form instanceof HTMLFormElement) || (form.getAttribute("method") || "").toLowerCase() !== "post") return;
    const question = form.getAttribute("data-confirm");
    if (question && !window.confirm(question)) {
      event.preventDefault();
      return;
    }
    ensureToken(form);
    if (form.dataset.submitted === "1") {   // second click while the first is still being sent
      event.preventDefault();
      return;
    }
    form.dataset.submitted = "1";
    form.querySelectorAll('button[type="submit"]').forEach(function (b) { b.disabled = true; });
  });
  // a page restored from the back/forward cache must be usable again
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-submitted]").forEach(function (f) {
      delete f.dataset.submitted;
      f.querySelectorAll('button[type="submit"]').forEach(function (b) { b.disabled = false; });
    });
  });

  // ------------------------------------------------------------ dialogs
  document.addEventListener("click", function (event) {
    const opener = event.target.closest("[data-open]");
    if (opener) {
      const dlg = document.getElementById(opener.getAttribute("data-open"));
      if (dlg && typeof dlg.showModal === "function") {
        const target = dlg.querySelector("[data-replaces-target]");
        const label = dlg.querySelector("[data-replaces-label]");
        if (target) target.value = opener.getAttribute("data-replaces") || "";
        if (label) label.textContent = opener.getAttribute("data-replaces")
          ? "· החלפת " + (opener.getAttribute("data-replaces-name") || "") : "";
        dlg.showModal();
        const first = dlg.querySelector("input:not([type=hidden]):not([disabled]), select, textarea");
        if (first) first.focus();
      }
      return;
    }
    const closer = event.target.closest("[data-close]");
    if (closer) {
      const dlg = closer.closest("dialog");
      if (dlg) dlg.close();
    }
  });

  // checkbox that enables/disables a fieldset (e.g. "record corrected payment")
  function syncToggle(box) {
    const set = document.getElementById(box.getAttribute("data-toggle"));
    if (set) set.disabled = !box.checked;
  }
  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-toggle]")) syncToggle(event.target);
  });

  // ------------------------------------------------------------ Hebrew DD/MM/YYYY date picker
  const MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"];
  const DAYS = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"]; // Sunday first

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function format(d) { return pad(d.getDate()) + "/" + pad(d.getMonth() + 1) + "/" + d.getFullYear(); }
  function parse(text) {
    const m = /^([0-9]{1,2})\/([0-9]{1,2})\/([0-9]{4})$/.exec((text || "").trim());
    if (!m) return null;
    const d = new Date(+m[3], +m[2] - 1, +m[1]);
    // reject dates JavaScript silently rolls over (31/02 → 03/03)
    return d.getDate() === +m[1] && d.getMonth() === +m[2] - 1 ? d : null;
  }

  let openPicker = null;
  function closePicker() {
    if (openPicker) { openPicker.remove(); openPicker = null; }
  }

  function showPicker(input) {
    closePicker();
    const today = new Date();
    let view = parse(input.value) || today;
    const popup = document.createElement("div");
    popup.className = "datepicker";
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-label", "בחירת תאריך");

    function render() {
      popup.textContent = "";
      const head = document.createElement("div");
      head.className = "dp-head";
      // RTL: "previous" sits on the right and points right; "next" sits on the left and points left
      const prev = button("›", "חודש קודם", function () { view = new Date(view.getFullYear(), view.getMonth() - 1, 1); render(); });
      const next = button("‹", "חודש הבא", function () { view = new Date(view.getFullYear(), view.getMonth() + 1, 1); render(); });
      const title = document.createElement("span");
      title.textContent = MONTHS[view.getMonth()] + " " + view.getFullYear();
      head.append(prev, title, next); // RTL: "previous" sits on the right
      popup.appendChild(head);

      const grid = document.createElement("div");
      grid.className = "dp-grid";
      DAYS.forEach(function (d) { const s = document.createElement("span"); s.className = "dp-dow"; s.textContent = d; grid.appendChild(s); });
      const first = new Date(view.getFullYear(), view.getMonth(), 1);
      for (let i = 0; i < first.getDay(); i++) grid.appendChild(document.createElement("span"));
      const days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
      const selected = parse(input.value);
      for (let day = 1; day <= days; day++) {
        const date = new Date(view.getFullYear(), view.getMonth(), day);
        const b = button(String(day), format(date), function () {
          input.value = format(date);
          input.dispatchEvent(new Event("change", { bubbles: true }));
          closePicker();
          input.focus();
        });
        if (selected && date.getTime() === selected.getTime()) b.classList.add("dp-selected");
        if (date.toDateString() === today.toDateString()) b.classList.add("dp-today");
        grid.appendChild(b);
      }
      popup.appendChild(grid);
      const foot = document.createElement("div");
      foot.className = "dp-foot";
      foot.appendChild(button("היום", "היום", function () { input.value = format(today); closePicker(); input.focus(); }));
      foot.appendChild(button("ניקוי", "ניקוי התאריך", function () { input.value = ""; closePicker(); input.focus(); }));
      popup.appendChild(foot);
    }

    function button(text, label, onClick) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      b.setAttribute("aria-label", label);
      b.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); onClick(); });
      return b;
    }

    render();
    input.parentElement.appendChild(popup);
    openPicker = popup;
  }

  function enhanceDateInput(input) {
    if (input.dataset.enhanced) return;
    input.dataset.enhanced = "1";
    const wrap = document.createElement("div");
    wrap.className = "date-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "date-btn";
    btn.setAttribute("aria-label", "פתיחת לוח שנה");
    btn.textContent = "📅";
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (openPicker && openPicker.parentElement === wrap) closePicker(); else showPicker(input);
    });
    wrap.appendChild(btn);
  }

  document.addEventListener("click", function (event) {
    if (openPicker && !openPicker.contains(event.target)) closePicker();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && openPicker) { closePicker(); event.stopPropagation(); }
  });

  // ------------------------------------------------------------ init
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("input.date-input").forEach(enhanceDateInput);
    document.querySelectorAll("[data-toggle]").forEach(syncToggle);
    const auto = document.querySelector("dialog[data-auto-open]");
    if (auto && typeof auto.showModal === "function") auto.showModal();
  });
})();
