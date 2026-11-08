/* The hosted /widget page: shows the company's own content (company.json, built from Company_Documents/) around the chat.
   Everything is inserted as text nodes, never as markup. Clicking a service pillar asks the assistant about it. */
(function () {
  "use strict";
  var script = document.currentScript;
  var BASE = script && script.src ? script.src.replace(/[^/]*$/, "") : "";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function render(c) {
    if (!c || !c.name) return;
    var brand = document.getElementById("brand"), grid = document.getElementById("pillars");
    var heading = document.getElementById("pillars-title"), about = document.getElementById("about");
    if (brand) {
      brand.textContent = "";
      brand.appendChild(el("span", "mpd-brand-mark", c.name.charAt(0)));
      var names = el("span", "mpd-brand-text");
      names.appendChild(el("span", "mpd-brand-name", c.name));
      if (c.subtitle) names.appendChild(el("span", "mpd-brand-sub", c.subtitle));
      brand.appendChild(names);
    }
    if (about) {
      about.textContent = "";
      if (c.overview) about.appendChild(el("p", "mpd-hero-text", c.overview));
      if (c.presence) about.appendChild(el("p", "mpd-meta", c.presence));
    }
    if (heading) heading.textContent = "Pillars of Service";
    if (!grid) return;
    grid.textContent = "";
    (c.pillars || []).forEach(function (p) {
      var card = el("button", "mpd-pillar"); card.type = "button";
      card.appendChild(el("span", "mpd-pillar-num", String(p.number)));
      card.appendChild(el("span", "mpd-pillar-name", p.name));
      if (p.summary) card.appendChild(el("span", "mpd-pillar-sum", p.summary));
      card.addEventListener("click", function () {
        if (window.MPDWidget) window.MPDWidget.ask("Tell me about " + p.name, p.name);
        var slot = document.getElementById("chat-slot");
        if (slot) slot.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      grid.appendChild(card);
    });
  }

  fetch(BASE + "company.json").then(function (r) { return r.ok ? r.json() : null; }).then(render).catch(function () {});
})();
