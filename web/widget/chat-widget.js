/* MasterProDev chat widget. No dependencies, no innerHTML: every piece of model or user text goes in as a text node,
   so nothing the assistant says can inject markup. The session id lives in sessionStorage only (no tokens, no cookies).
   Embed:  <script src="chat-widget.js" data-api="https://api.example.com" defer></script>
   Options: data-mode="full" renders full-page instead of a bubble. */
(function () {
  "use strict";
  var script = document.currentScript;
  var API = ((script && script.getAttribute("data-api")) || "").replace(/\/$/, "");
  var FULL = script && script.getAttribute("data-mode") === "full";
  var BASE = script && script.src ? script.src.replace(/[^/]*$/, "") : "";
  var LANG = (navigator.language || "en").toLowerCase().indexOf("fr") === 0 ? "fr" : "en";

  var T = {
    en: { title: "MasterProDev Assistant", placeholder: "Type your message", send: "Send", open: "Open chat", close: "Close chat",
      thinking: "Thinking...", yes: "Yes", no: "No", verify: "Verify my identity", name: "Full name", email: "Email", phone: "Mobile phone",
      sendCodes: "Send codes", emailCode: "Email code", phoneCode: "Text message code", confirm: "Confirm", attach: "Attach a file",
      mic: "Speak", stop: "Stop recording", error: "Something went wrong. Please try again.", verified: "You are verified.",
      uploaded: "File added.", codesSent: "Codes sent. Enter them below.", wrongCodes: "Those codes did not work.", cancel: "Cancel",
      account: "My account", close2: "Close", stepCode: "Security code from your email", sendStepCode: "Email me a code", codeSent: "Code sent to your email.",
      stepDone: "Security check complete for 15 minutes.", needStepUp: "Please complete the security check first.", google: "Connect Google",
      googleOff: "Disconnect Google", googleOn: "Google is connected.", googleNone: "Google is not connected.", googleOpened: "Finish connecting in the new tab.",
      memoryOn: "Remember me", memoryOff: "Stop remembering", memoryShow: "What do you remember?", memoryNone: "Nothing is remembered.", memoryForget: "Forget everything",
      memoryDone: "Done.", download: "Download my data", del: "Delete my account", delHint: 'Type DELETE to confirm', deleted: "Your account was deleted.",
      endChat: "End this conversation", ended: "Conversation ended." },
    fr: { title: "Assistant MasterProDev", placeholder: "Écrivez votre message", send: "Envoyer", open: "Ouvrir le clavardage", close: "Fermer",
      thinking: "Un instant...", yes: "Oui", no: "Non", verify: "Vérifier mon identité", name: "Nom complet", email: "Courriel", phone: "Téléphone mobile",
      sendCodes: "Envoyer les codes", emailCode: "Code reçu par courriel", phoneCode: "Code reçu par texto", confirm: "Confirmer", attach: "Joindre un fichier",
      mic: "Parler", stop: "Arrêter", error: "Une erreur est survenue. Veuillez réessayer.", verified: "Votre identité est vérifiée.",
      uploaded: "Fichier ajouté.", codesSent: "Codes envoyés. Saisissez-les ci-dessous.", wrongCodes: "Ces codes n'ont pas fonctionné.", cancel: "Annuler",
      account: "Mon compte", close2: "Fermer", stepCode: "Code de sécurité reçu par courriel", sendStepCode: "M'envoyer un code", codeSent: "Code envoyé par courriel.",
      stepDone: "Vérification de sécurité faite pour 15 minutes.", needStepUp: "Veuillez d'abord effectuer la vérification de sécurité.", google: "Connecter Google",
      googleOff: "Déconnecter Google", googleOn: "Google est connecté.", googleNone: "Google n'est pas connecté.", googleOpened: "Terminez la connexion dans le nouvel onglet.",
      memoryOn: "Se souvenir de moi", memoryOff: "Arrêter de se souvenir", memoryShow: "De quoi vous souvenez-vous ?", memoryNone: "Rien n'est mémorisé.", memoryForget: "Tout oublier",
      memoryDone: "C'est fait.", download: "Télécharger mes données", del: "Supprimer mon compte", delHint: "Tapez DELETE pour confirmer", deleted: "Votre compte a été supprimé.",
      endChat: "Terminer cette conversation", ended: "Conversation terminée." }
  }[LANG];

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // --- safe rendering: **bold**, [label](https://url) and bare https URLs; everything else is plain text ---
  var INLINE = /(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?:\/\/[^\s)]+\))|(https?:\/\/[^\s<>"')]+)/g;
  function safeUrl(u) { try { var p = new URL(u); return p.protocol === "https:" || p.protocol === "http:" ? p.href : null; } catch (e) { return null; } }
  function link(label, href) {
    var url = safeUrl(href);
    if (!url) return document.createTextNode(label);
    var a = el("a", "mpd-link", label);
    a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  }
  function renderInto(node, text) {
    String(text).split(/\n+/).forEach(function (line) {
      if (!line.trim()) return;
      var p = el("p", "mpd-p"), last = 0, m;
      INLINE.lastIndex = 0;
      while ((m = INLINE.exec(line))) {
        if (m.index > last) p.appendChild(document.createTextNode(line.slice(last, m.index)));
        if (m[1]) p.appendChild(el("strong", "", m[1].slice(2, -2)));
        else if (m[2]) { var parts = /^\[([^\]]+)\]\((.+)\)$/.exec(m[2]); p.appendChild(link(parts[1], parts[2])); }
        else p.appendChild(link(m[3], m[3]));
        last = m.index + m[0].length;
      }
      if (last < line.length) p.appendChild(document.createTextNode(line.slice(last)));
      node.appendChild(p);
    });
  }

  // --- state ---
  var sessionId = null;
  try { sessionId = sessionStorage.getItem("mpd_session"); } catch (e) {}
  function setSession(id) { sessionId = id; try { sessionStorage.setItem("mpd_session", id); } catch (e) {} }

  function post(path, body, isForm) {
    return fetch(API + path, { method: "POST", headers: isForm ? undefined : { "Content-Type": "application/json" }, body: isForm ? body : JSON.stringify(body) });
  }
  function ensureSession() {
    if (sessionId) return Promise.resolve(sessionId);
    return post("/v2/session", {}).then(function (r) { return r.json(); }).then(function (j) { setSession(j.session_id); return j.session_id; });
  }

  // --- UI ---
  var css = document.createElement("link");
  css.rel = "stylesheet"; css.href = BASE + "chat-widget.css";
  document.head.appendChild(css);

  var root = el("div", "mpd-root" + (FULL ? " mpd-full" : ""));
  var panel = el("section", "mpd-panel");
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", T.title);
  var header = el("header", "mpd-header");
  header.appendChild(el("span", "mpd-title", T.title));
  var verifyBtn = el("button", "mpd-link-btn", T.verify); verifyBtn.type = "button";
  var closeBtn = el("button", "mpd-icon-btn", "×"); closeBtn.type = "button"; closeBtn.setAttribute("aria-label", T.close);
  var acctBtn = el("button", "mpd-link-btn", T.account); acctBtn.type = "button"; acctBtn.hidden = true;
  header.appendChild(verifyBtn); header.appendChild(acctBtn); if (!FULL) header.appendChild(closeBtn);

  var log = el("div", "mpd-log"); log.setAttribute("role", "log"); log.setAttribute("aria-live", "polite");
  var quick = el("div", "mpd-quick");
  var idPanel = el("form", "mpd-identity"); idPanel.hidden = true;
  var acctPanel = el("div", "mpd-identity mpd-account"); acctPanel.hidden = true;

  var form = el("form", "mpd-form");
  var input = el("input", "mpd-input"); input.type = "text"; input.maxLength = 4000; input.placeholder = T.placeholder; input.setAttribute("aria-label", T.placeholder); input.autocomplete = "off";
  var attach = el("button", "mpd-icon-btn", "\u{1F4CE}"); attach.type = "button"; attach.setAttribute("aria-label", T.attach);
  var fileInput = el("input"); fileInput.type = "file"; fileInput.hidden = true; fileInput.accept = ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp";
  var mic = el("button", "mpd-icon-btn", "\u{1F3A4}"); mic.type = "button"; mic.setAttribute("aria-label", T.mic);
  var send = el("button", "mpd-send", T.send); send.type = "submit";
  [attach, input, mic, send, fileInput].forEach(function (n) { form.appendChild(n); });
  [header, log, quick, idPanel, acctPanel, form].forEach(function (n) { panel.appendChild(n); });

  var bubble = el("button", "mpd-bubble", "\u{1F4AC}"); bubble.type = "button"; bubble.setAttribute("aria-label", T.open);
  root.appendChild(panel); if (!FULL) root.appendChild(bubble);
  document.body.appendChild(root);
  if (!FULL) panel.hidden = true;

  function scroll() { log.scrollTop = log.scrollHeight; }
  function bubbleMsg(kind, text) {
    var m = el("div", "mpd-msg mpd-" + kind);
    renderInto(m, text);
    log.appendChild(m); scroll();
    return m;
  }
  function status(text) { var s = el("div", "mpd-status", text); log.appendChild(s); scroll(); return s; }

  function showQuickReplies(text) {
    quick.textContent = "";
    if (!/\((yes\/no|oui\/non)\)\s*$|reply yes|répondez oui/i.test(text || "")) return;
    [[T.yes, "yes"], [T.no, "no"]].forEach(function (pair) {
      var b = el("button", "mpd-chip", pair[0]); b.type = "button";
      b.addEventListener("click", function () { quick.textContent = ""; ask(pair[1], pair[0]); });
      quick.appendChild(b);
    });
  }

  // --- chat over SSE (fetch stream, since EventSource cannot POST) ---
  var busy = false;
  function ask(message, shown) {
    if (busy || !message.trim()) return;
    busy = true; send.disabled = true; quick.textContent = "";
    bubbleMsg("user", shown || message);
    var thinking = status(T.thinking), reply = null, full = "";
    ensureSession().then(function (sid) {
      return post("/v2/chat/stream", { message: message, session_id: sid });
    }).then(function (res) {
      if (!res.ok || !res.body) throw new Error("http");
      var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) return;
          buf += dec.decode(r.value, { stream: true });
          var events = buf.split("\n\n"); buf = events.pop();
          events.forEach(function (raw) {
            if (raw.charAt(0) === ":") return;
            var line = raw.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; })[0];
            if (!line) return;
            var ev; try { ev = JSON.parse(line.slice(6)); } catch (e) { return; }
            if (ev.type === "chunk") {
              if (thinking) { thinking.remove(); thinking = null; }
              full += (full ? " " : "") + ev.text;
              if (!reply) reply = el("div", "mpd-msg mpd-bot"); else reply.textContent = "";
              renderInto(reply, full);
              if (!reply.parentNode) log.appendChild(reply);
              scroll();
            } else if (ev.type === "done") {
              if (ev.session_id) setSession(ev.session_id);
            } else if (ev.type === "error") {
              full = ev.text || T.error;
            }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function () {
      if (!full) full = T.error;
      if (thinking) { thinking.remove(); thinking = null; }
      if (!reply) bubbleMsg("bot", full);
    }).then(function () {
      busy = false; send.disabled = false; showQuickReplies(full); input.focus();
    });
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); var v = input.value; input.value = ""; ask(v); });
  bubble.addEventListener("click", function () { panel.hidden = false; bubble.hidden = true; input.focus(); });
  closeBtn.addEventListener("click", function () { panel.hidden = true; bubble.hidden = false; });

  // --- file upload ---
  attach.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    var f = fileInput.files && fileInput.files[0]; fileInput.value = "";
    if (!f) return;
    ensureSession().then(function (sid) {
      var fd = new FormData(); fd.append("session_id", sid); fd.append("file", f);
      return post("/v2/upload", fd, true);
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) { status(x.ok ? T.uploaded + " (" + f.name + ")" : (typeof x.j.detail === "string" ? x.j.detail : T.error)); })
      .catch(function () { status(T.error); });
  });

  // --- voice: record, send, show transcript and reply ---
  var recorder = null, chunks = [];
  mic.addEventListener("click", function () {
    if (recorder) { recorder.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { status(T.error); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      chunks = []; recorder = new MediaRecorder(stream);
      recorder.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        var blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" }); recorder = null;
        mic.textContent = "\u{1F3A4}"; mic.setAttribute("aria-label", T.mic);
        ensureSession().then(function (sid) {
          var fd = new FormData(); fd.append("session_id", sid); fd.append("audio", blob, "speech.webm");
          return post("/v2/voice", fd, true);
        }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (x) {
            if (!x.ok) { status(typeof x.j.detail === "string" ? x.j.detail : T.error); return; }
            setSession(x.j.session_id); bubbleMsg("user", x.j.transcript); bubbleMsg("bot", x.j.reply); showQuickReplies(x.j.reply);
          }).catch(function () { status(T.error); });
      };
      recorder.start(); mic.textContent = "⏹"; mic.setAttribute("aria-label", T.stop);
    }).catch(function () { status(T.error); });
  });

  // --- identity: details -> two codes -> verified ---
  function field(labelText, type, name, autocomplete) {
    var wrap = el("label", "mpd-field"); wrap.appendChild(el("span", "", labelText));
    var i = el("input", "mpd-input"); i.type = type; i.name = name; i.required = true; i.autocomplete = autocomplete || "off"; wrap.appendChild(i);
    return { wrap: wrap, input: i };
  }
  var stage = "details";
  function buildIdentity() {
    idPanel.textContent = "";
    if (stage === "details") {
      var n = field(T.name, "text", "name", "name"), em = field(T.email, "email", "email", "email"), ph = field(T.phone, "tel", "phone", "tel");
      [n, em, ph].forEach(function (f) { idPanel.appendChild(f.wrap); });
      var go = el("button", "mpd-send", T.sendCodes); go.type = "submit"; idPanel.appendChild(go);
      idPanel.onsubmit = function (e) {
        e.preventDefault(); go.disabled = true;
        ensureSession().then(function (sid) { return post("/v2/identity/start", { session_id: sid, name: n.input.value, email: em.input.value, phone: ph.input.value }); })
          .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (x) { if (x.ok) { stage = "codes"; status(T.codesSent); buildIdentity(); } else { go.disabled = false; status(typeof x.j.detail === "string" ? x.j.detail : T.error); } })
          .catch(function () { go.disabled = false; status(T.error); });
      };
    } else {
      var ec = field(T.emailCode, "text", "email_code", "one-time-code"), pc = field(T.phoneCode, "text", "phone_code", "one-time-code");
      [ec, pc].forEach(function (f) { f.input.inputMode = "numeric"; f.input.maxLength = 12; idPanel.appendChild(f.wrap); });
      var ok = el("button", "mpd-send", T.confirm); ok.type = "submit"; idPanel.appendChild(ok);
      idPanel.onsubmit = function (e) {
        e.preventDefault(); ok.disabled = true;
        post("/v2/identity/verify", { session_id: sessionId, email_code: ec.input.value, phone_code: pc.input.value })
          .then(function (r) { if (r.ok) { idPanel.hidden = true; markVerified(); stage = "details"; status(T.verified); } else { ok.disabled = false; status(T.wrongCodes); } })
          .catch(function () { ok.disabled = false; status(T.error); });
      };
    }
    var cancel = el("button", "mpd-link-btn", T.cancel); cancel.type = "button";
    cancel.addEventListener("click", function () { idPanel.hidden = true; stage = "details"; });
    idPanel.appendChild(cancel);
  }
  verifyBtn.addEventListener("click", function () { buildIdentity(); idPanel.hidden = !idPanel.hidden; });

  function markVerified() { verifyBtn.hidden = true; acctBtn.hidden = false; }

  // --- account: security code, Google connection, memory, data export, deletion, end conversation ---
  function call(method, path, body) {
    var opts = { method: method };
    if (body) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    });
  }
  function detail(x) { return typeof x.j.detail === "string" ? x.j.detail : T.error; }
  function btn(label, onClick, cls) {
    var b = el("button", cls || "mpd-chip", label); b.type = "button";
    b.addEventListener("click", function () { onClick(b); });
    return b;
  }
  function group() { return el("div", "mpd-account-row"); }
  function asFile(name, text) {
    var url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    var a = el("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function buildAccount() {
    acctPanel.textContent = "";
    var sid = sessionId, g;

    var code = field(T.stepCode, "text", "stepup_code", "one-time-code");
    code.input.inputMode = "numeric"; code.input.maxLength = 12; code.input.required = false;
    g = group(); g.appendChild(code.wrap);
    g.appendChild(btn(T.sendStepCode, function () {
      call("POST", "/v2/account/stepup/start", { session_id: sid }).then(function (x) { status(x.ok ? T.codeSent : detail(x)); }).catch(function () { status(T.error); });
    }));
    g.appendChild(btn(T.confirm, function () {
      call("POST", "/v2/account/stepup/verify", { session_id: sid, code: code.input.value }).then(function (x) { status(x.ok ? T.stepDone : T.wrongCodes); }).catch(function () { status(T.error); });
    }));
    acctPanel.appendChild(g);

    g = group();
    g.appendChild(btn(T.google, function () {
      call("GET", "/v2/integrations/google/start?session_id=" + encodeURIComponent(sid)).then(function (x) {
        if (x.ok && x.j.url && safeUrl(x.j.url)) { window.open(safeUrl(x.j.url), "_blank", "noopener,noreferrer"); status(T.googleOpened); }
        else status(x.status === 403 ? T.needStepUp : detail(x));
      }).catch(function () { status(T.error); });
    }));
    g.appendChild(btn(T.googleOff, function () {
      call("POST", "/v2/integrations/google/disconnect", { session_id: sid }).then(function (x) { status(x.ok ? T.googleNone : detail(x)); }).catch(function () { status(T.error); });
    }));
    acctPanel.appendChild(g);

    g = group();
    g.appendChild(btn(T.memoryOn, function () { call("POST", "/v2/memory/consent", { session_id: sid, enabled: true }).then(function (x) { status(x.ok ? T.memoryDone : detail(x)); }).catch(function () { status(T.error); }); }));
    g.appendChild(btn(T.memoryOff, function () { call("POST", "/v2/memory/consent", { session_id: sid, enabled: false }).then(function (x) { status(x.ok ? T.memoryDone : detail(x)); }).catch(function () { status(T.error); }); }));
    g.appendChild(btn(T.memoryShow, function () {
      call("GET", "/v2/memory?session_id=" + encodeURIComponent(sid)).then(function (x) {
        if (!x.ok) { status(detail(x)); return; }
        var items = x.j.memories || [];
        bubbleMsg("bot", items.length ? items.map(function (m) { return "- " + m.text; }).join("\n") : T.memoryNone);
      }).catch(function () { status(T.error); });
    }));
    g.appendChild(btn(T.memoryForget, function () { call("POST", "/v2/memory/forget", { session_id: sid }).then(function (x) { status(x.ok ? T.memoryDone : detail(x)); }).catch(function () { status(T.error); }); }));
    acctPanel.appendChild(g);

    g = group();
    g.appendChild(btn(T.download, function () {
      call("GET", "/v2/account/export?session_id=" + encodeURIComponent(sid)).then(function (x) {
        if (x.ok) asFile("my-data.json", JSON.stringify(x.j, null, 2)); else status(x.status === 403 ? T.needStepUp : detail(x));
      }).catch(function () { status(T.error); });
    }));
    g.appendChild(btn(T.endChat, function () {
      call("POST", "/v2/session/" + encodeURIComponent(sid) + "/end").then(function (x) {
        if (x.ok) { log.textContent = ""; status(T.ended); } else status(detail(x));
      }).catch(function () { status(T.error); });
    }));
    acctPanel.appendChild(g);

    var confirmDel = field(T.delHint, "text", "delete_confirm", "off"); confirmDel.input.required = false;
    g = group(); g.appendChild(confirmDel.wrap);
    g.appendChild(btn(T.del, function () {
      call("POST", "/v2/account/delete", { session_id: sid, confirm: confirmDel.input.value }).then(function (x) {
        if (x.ok) {
          try { sessionStorage.removeItem("mpd_session"); } catch (e) {}
          sessionId = null; acctPanel.hidden = true; acctBtn.hidden = true; verifyBtn.hidden = false; log.textContent = ""; status(T.deleted);
        } else status(x.status === 403 ? T.needStepUp : detail(x));
      }).catch(function () { status(T.error); });
    }, "mpd-chip mpd-danger"));
    acctPanel.appendChild(g);

    acctPanel.appendChild(btn(T.close2, function () { acctPanel.hidden = true; }, "mpd-link-btn"));
  }
  acctBtn.addEventListener("click", function () { if (acctPanel.hidden) { buildAccount(); acctPanel.hidden = false; idPanel.hidden = true; } else acctPanel.hidden = true; });

  if (sessionId) {
    fetch(API + "/v2/session/" + encodeURIComponent(sessionId)).then(function (r) {
      if (!r.ok) { sessionId = null; try { sessionStorage.removeItem("mpd_session"); } catch (e) {} return null; }
      return r.json();
    }).then(function (j) { if (j && j.verified) markVerified(); }).catch(function () {});
  }
})();
