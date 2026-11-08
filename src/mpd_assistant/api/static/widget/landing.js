/* The hosted /widget page: shows the company's own content (company.json, built from Company_Documents/) next to the chat.
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
    var hero = document.getElementById("hero"), grid = document.getElementById("pillars"), heading = document.getElementById("pillars-title");
    if (hero) {
      hero.textContent = "";
      if (c.subtitle) hero.appendChild(el("p", "mpd-eyebrow", c.subtitle));
      hero.appendChild(el("h1", "", c.name));
      if (c.tagline) hero.appendChild(el("p", "mpd-hero-tagline", c.tagline));
      if (c.overview) hero.appendChild(el("p", "mpd-hero-text", c.overview));
      if (c.presence) hero.appendChild(el("p", "mpd-meta", c.presence));
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
        if (slot && window.innerWidth < 980) slot.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      grid.appendChild(card);
    });
  }

  fetch(BASE + "company.json").then(function (r) { return r.ok ? r.json() : null; }).then(render).catch(function () {});
})();
