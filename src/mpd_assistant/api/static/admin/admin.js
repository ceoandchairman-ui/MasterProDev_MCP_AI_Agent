/* Staff console. Talks only to this API's /v2/admin routes with the staff token (kept in sessionStorage for the tab).
   No innerHTML and no inline script: every value from the server is set as text, so nothing stored in a conversation
   can inject markup into the console. */
(function () {
  "use strict";
  var app = document.getElementById("app");
  var token = "";
  try { token = sessionStorage.getItem("mpd_admin") || ""; } catch (e) {}

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function button(label, onClick, cls) {
    var b = el("button", cls || "", label); b.type = "button";
    b.addEventListener("click", function () { onClick(b); });
    return b;
  }
  function money(cents, currency) { return (Number(cents || 0) / 100).toFixed(2) + " " + (currency || "CAD"); }
  function when(value) {
    if (!value) return "";
    var d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    return isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  }
  function safeUrl(u) { try { var p = new URL(u); return p.protocol === "https:" || p.protocol === "http:" ? p.href : null; } catch (e) { return null; } }

  function api(method, path, body) {
    var opts = { method: method, headers: { Authorization: "Bearer " + token } };
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    });
  }
  function problem(x) { return typeof x.j.detail === "string" ? x.j.detail : "Request failed (" + x.status + ")"; }

  var notice = el("div", "notice"); notice.hidden = true;
  function say(text, kind) { notice.className = "notice " + (kind || ""); notice.textContent = text; notice.hidden = !text; }

  // ---- sign in ----
  function signIn(message) {
    app.textContent = "";
    app.appendChild(el("h1", "", "Staff console"));
    var card = el("form", "card");
    if (message) card.appendChild(el("div", "notice error", message));
    var input = el("input"); input.type = "password"; input.placeholder = "Staff token"; input.autocomplete = "off"; input.required = true;
    var go = el("button", "primary", "Sign in"); go.type = "submit";
    var row = el("div", "row"); row.appendChild(input); row.appendChild(go); card.appendChild(row);
    card.addEventListener("submit", function (e) {
      e.preventDefault(); token = input.value.trim();
      api("GET", "/v2/admin/overview").then(function (x) {
        if (!x.ok) { token = ""; signIn(x.status === 401 ? "That token was not accepted." : problem(x)); return; }
        try { sessionStorage.setItem("mpd_admin", token); } catch (err) {}
        main("overview");
      }).catch(function () { signIn("Could not reach the server."); });
    });
    app.appendChild(card); input.focus();
  }
  function signOut() { token = ""; try { sessionStorage.removeItem("mpd_admin"); } catch (e) {} signIn(); }

  // ---- layout ----
  var VIEWS = [["overview", "Overview"], ["escalations", "Escalations"], ["quotes", "Quotes"], ["patterns", "Patterns"], ["undelivered", "Undelivered"], ["people", "People"]];
  var counts = {};
  function main(view) {
    app.textContent = "";
    app.appendChild(el("h1", "", "Staff console"));
    var bar = el("div", "bar");
    VIEWS.forEach(function (v) {
      var b = button(v[1], function () { main(v[0]); }, v[0] === view ? "active" : "");
      var n = counts[v[0]];
      if (n !== undefined) { b.appendChild(document.createTextNode(" ")); b.appendChild(el("span", "count" + (n ? "" : " zero"), n)); }
      bar.appendChild(b);
    });
    bar.appendChild(el("span", "grow")); bar.appendChild(button("Sign out", signOut));
    app.appendChild(bar); app.appendChild(notice); say("");
    var body = el("section"); app.appendChild(body);
    (RENDER[view] || RENDER.overview)(body);
    api("GET", "/v2/admin/overview").then(function (x) {
      if (!x.ok) return;
      counts = { escalations: x.j.open_escalations, quotes: x.j.quotes_awaiting_review, patterns: x.j.patterns_awaiting_review, undelivered: x.j.undelivered_messages };
      var tabs = bar.querySelectorAll("button");
      VIEWS.forEach(function (v, i) {
        var n = counts[v[0]];
        if (n === undefined || tabs[i].querySelector(".count")) return;
        tabs[i].appendChild(document.createTextNode(" ")); tabs[i].appendChild(el("span", "count" + (n ? "" : " zero"), n));
      });
    });
  }
  function load(body, path, render) {
    body.appendChild(el("p", "muted", "Loading..."));
    api("GET", path).then(function (x) {
      body.textContent = "";
      if (x.status === 401) { signIn("Your session ended. Sign in again."); return; }
      if (!x.ok) { body.appendChild(el("div", "notice error", problem(x))); return; }
      render(x.j);
    }).catch(function () { body.textContent = ""; body.appendChild(el("div", "notice error", "Could not reach the server.")); });
  }
  function act(btn, method, path, body, done, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    btn.disabled = true;
    api(method, path, body).then(function (x) {
      if (x.ok) { say(done, "ok"); main(currentView); } else { btn.disabled = false; say(problem(x), "error"); }
    }).catch(function () { btn.disabled = false; say("Could not reach the server.", "error"); });
  }
  var currentView = "overview";

  // ---- views ----
  var RENDER = {
    overview: function (body) {
      currentView = "overview";
      load(body, "/v2/admin/overview", function (o) {
        var card = el("div", "card");
        [["Open escalations", o.open_escalations], ["Quotes awaiting review", o.quotes_awaiting_review], ["Reply patterns awaiting review", o.patterns_awaiting_review], ["Undelivered messages", o.undelivered_messages]]
          .forEach(function (p) { var r = el("div", "row"); r.appendChild(el("span", "grow", p[0])); r.appendChild(el("strong", "", p[1] === undefined ? "n/a" : p[1])); card.appendChild(r); });
        body.appendChild(card);
        var links = o.links || {}, linkCard = el("div", "card row");
        Object.keys(links).forEach(function (k) {
          var u = safeUrl(links[k]); if (!u) return;
          var a = el("a", "", k === "grafana" ? "Open Grafana" : k === "langsmith" ? "Open LangSmith" : k); a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer"; linkCard.appendChild(a);
        });
        if (linkCard.childNodes.length) body.appendChild(linkCard);
        (o.cache_layers || []).length && body.appendChild(el("h2", "", "Caches"));
        (o.cache_layers || []).forEach(function (layer) {
          var r = el("div", "card row"); r.appendChild(el("span", "grow", "Cache layer: " + layer));
          r.appendChild(button("Purge", function (b) { act(b, "POST", "/v2/admin/cache/purge/" + encodeURIComponent(layer), null, "Purged " + layer + ".", "Purge the " + layer + " cache?"); }, "danger"));
          body.appendChild(r);
        });
      });
    },
    escalations: function (body) {
      currentView = "escalations";
      load(body, "/v2/admin/escalations", function (d) {
        var list = d.escalations || [];
        if (!list.length) body.appendChild(el("p", "muted", "No open escalations."));
        list.forEach(function (e) {
          var card = el("div", "card"), r = el("div", "row");
          r.appendChild(el("strong", "grow", e.reference + " - " + e.reason)); r.appendChild(el("span", "muted", when(e.created_at)));
          r.appendChild(button("Resolve", function (b) { act(b, "POST", "/v2/admin/escalations/" + encodeURIComponent(e.reference) + "/resolve", null, "Resolved " + e.reference + ".", "Mark " + e.reference + " as resolved? The assistant will resume for that conversation."); }, "primary"));
          card.appendChild(r); card.appendChild(el("pre", "", e.summary)); body.appendChild(card);
        });
      });
    },
    quotes: function (body) {
      currentView = "quotes";
      load(body, "/v2/admin/quotes", function (d) {
        var list = d.quotes || [];
        if (!list.length) body.appendChild(el("p", "muted", "No quotes are waiting for review."));
        list.forEach(function (q) {
          var card = el("div", "card"), r = el("div", "row");
          r.appendChild(el("strong", "grow", q.reference + " - " + money(q.total_cents, q.currency)));
          r.appendChild(button("Approve", function (b) { act(b, "POST", "/v2/admin/quotes/" + encodeURIComponent(q.reference) + "/approve", null, "Approved " + q.reference + ". The customer was notified.", "Approve quote " + q.reference + " for " + money(q.total_cents, q.currency) + "?"); }, "primary"));
          r.appendChild(button("Decline", function (b) { act(b, "POST", "/v2/admin/quotes/" + encodeURIComponent(q.reference) + "/reject", null, "Declined " + q.reference + ". The customer was notified.", "Decline quote " + q.reference + "?"); }, "danger"));
          card.appendChild(r);
          var table = el("table"), head = el("tr");
          ["Item", "Qty", "Total"].forEach(function (h) { head.appendChild(el("th", "", h)); }); table.appendChild(head);
          (q.lines || []).forEach(function (l) { var tr = el("tr"); tr.appendChild(el("td", "", l.name)); tr.appendChild(el("td", "", l.quantity)); tr.appendChild(el("td", "", money(l.total_cents, q.currency))); table.appendChild(tr); });
          card.appendChild(table); body.appendChild(card);
        });
      });
    },
    patterns: function (body) {
      currentView = "patterns";
      load(body, "/v2/admin/patterns", function (d) {
        var list = d.patterns || [];
        if (!list.length) body.appendChild(el("p", "muted", "No reply patterns are waiting for review."));
        list.forEach(function (p) {
          var card = el("div", "card");
          card.appendChild(el("div", "muted", p.intent + " / " + p.language));
          card.appendChild(el("pre", "", "Customer: " + p.user_text)); card.appendChild(el("pre", "", "Assistant: " + p.reply_text));
          var r = el("div", "row");
          r.appendChild(button("Approve as an example", function (b) { act(b, "POST", "/v2/admin/patterns/" + encodeURIComponent(p.id) + "/approve", null, "Approved.", "Approve this reply as a style example for future answers?"); }, "primary"));
          r.appendChild(button("Reject", function (b) { act(b, "POST", "/v2/admin/patterns/" + encodeURIComponent(p.id) + "/reject", null, "Rejected."); }, "danger"));
          card.appendChild(r); body.appendChild(card);
        });
      });
    },
    undelivered: function (body) {
      currentView = "undelivered";
      load(body, "/v2/admin/undelivered", function (d) {
        var list = d.messages || [];
        if (!list.length) { body.appendChild(el("p", "muted", "No messages were reported as undelivered.")); return; }
        var table = el("table"), head = el("tr");
        ["When", "Channel", "To", "Message", "Status", "Code"].forEach(function (h) { head.appendChild(el("th", "", h)); }); table.appendChild(head);
        list.forEach(function (m) {
          var tr = el("tr");
          [when(m.at), m.channel, m.to, m.template, m.status, m.code].forEach(function (v) { tr.appendChild(el("td", "", v)); });
          table.appendChild(tr);
        });
        body.appendChild(el("div", "card")).appendChild(table);
      });
    },
    people: function (body) {
      currentView = "people";
      var card = el("form", "card row");
      var email = el("input"); email.type = "email"; email.placeholder = "Email address"; email.className = "grow";
      var phone = el("input"); phone.type = "tel"; phone.placeholder = "or phone number"; phone.className = "grow";
      var find = el("button", "primary", "Look up"); find.type = "submit";
      [email, phone, find].forEach(function (n) { card.appendChild(n); });
      var result = el("div");
      card.addEventListener("submit", function (e) {
        e.preventDefault(); result.textContent = "";
        var qs = email.value.trim() ? "email=" + encodeURIComponent(email.value.trim()) : phone.value.trim() ? "phone=" + encodeURIComponent(phone.value.trim()) : "";
        if (!qs) { say("Enter an email address or a phone number.", "error"); return; }
        api("GET", "/v2/admin/people?" + qs).then(function (x) {
          if (!x.ok) { say(x.status === 404 ? "No one matches." : problem(x), "error"); return; }
          say("");
          var p = x.j, c = el("div", "card");
          [["Name", p.name], ["Email", p.email], ["Phone", p.phone], ["Role", p.role], ["Verified", p.verified ? "yes" : "no"], ["Memory", p.memory_consent ? "on" : "off"], ["Lead stage", p.lead_stage || "none"], ["Id", p.id]]
            .forEach(function (kv) { var r = el("div", "row"); r.appendChild(el("span", "muted", kv[0])); r.appendChild(el("span", "grow", kv[1])); c.appendChild(r); });
          result.appendChild(c);
        }).catch(function () { say("Could not reach the server.", "error"); });
      });
      body.appendChild(card); body.appendChild(result);
      body.appendChild(el("h2", "", "Possible duplicates (same phone number)"));
      var dupes = el("div"); body.appendChild(dupes);
      load(dupes, "/v2/admin/people/duplicates", function (d) {
        var groups = d.groups || [];
        if (!groups.length) dupes.appendChild(el("p", "muted", "None found."));
        groups.forEach(function (ids) {
          var c = el("div", "card"); c.appendChild(el("div", "muted", "Accounts sharing a phone number"));
          ids.slice(1).forEach(function (dup) {
            var r = el("div", "row"); r.appendChild(el("span", "grow", "Merge " + dup + " into " + ids[0]));
            r.appendChild(button("Merge", function (b) { act(b, "POST", "/v2/admin/people/merge", { primary_id: ids[0], duplicate_id: dup, confirm: "MERGE" }, "Merged.", "Merge account " + dup + " into " + ids[0] + "? This cannot be undone."); }, "danger"));
            c.appendChild(r);
          });
          dupes.appendChild(c);
        });
      });
    }
  };

  if (token) {
    api("GET", "/v2/admin/overview").then(function (x) { if (x.ok) main("overview"); else { token = ""; signIn(); } }).catch(function () { signIn("Could not reach the server."); });
  } else {
    signIn();
  }
})();
