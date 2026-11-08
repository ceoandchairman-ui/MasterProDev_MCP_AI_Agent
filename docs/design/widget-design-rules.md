# Chat widget design rules

Rules for the Master Pro Dev chat widget and the hosted `/widget` page. They describe what the code in
`src/mpd_assistant/api/static/widget/` does today; change the code and this file together.

## Content: only the company's own data
- Company wording (name, tagline, overview, presence, the twelve pillars and their one-line summaries) comes from
  `company.json`, generated from `Company_Documents/*.docx` by `scripts/build_company_content.py`. Never type it into HTML, CSS or JS.
- A test fails if `company.json` differs from the documents. After editing a document, re-run the script and commit the result.
- UI copy that is not company data is limited to short labels ("Welcome to ...", "Choose a topic or ask me anything", mode names).
- `company.json` is English only; other languages keep the plain header and no welcome block.

## Layout
- The chat is the centre of the hosted page: one column, max 880 px, chat card first, then "Pillars of Service", then the overview.
- The embedded widget is a 380 x 600 panel opened from a round launcher; `data-mode="full"` renders it as a page card instead.
- Fresh chat: a centred welcome block (logo mark, title, tagline, four topic chips). It disappears on the first message.
- Mobile: the same single column; the chat card is at least 460 px tall; pillars stack one per row.

## Tokens (CSS variables on `:root`, prefix `--mpd-`)
| Token | Value | Use |
|---|---|---|
| `--mpd-accent` | `#00c896` | Logo mark, avatar, focus rings. Never behind text. |
| `--mpd-action` | `#00805f` | Buttons and user bubbles with white text (contrast 4.9:1). |
| `--mpd-action-hover` | `#006b50` | Hover for actions. |
| `--mpd-link` | `#2563eb` | Links. |
| `--mpd-bg` / `--mpd-bot` | `#ffffff` / `#f4f4f5` | Card and assistant bubbles. |
| `--mpd-fg` / `--mpd-muted` | `#202123` / `#71717a` | Text. |
| `--mpd-border` | `#e8e8e8` | Dividers. |
- Page background: brand gradient `#00c896 -> #ffb800 -> #2563eb -> #009977`, animated; static when the user prefers reduced motion.
- Radius: card 16-20 px, bubbles 18 px, inputs and buttons 8-10 px, chips pill. Font: system UI stack; 14 px body, 15 px title, 11 px tagline.
- Light theme only, as in the original product. White text goes on `--mpd-action`, never on `--mpd-accent`.

## Components (all classes are prefixed `mpd-`)
- Header (56 px min): logo mark, name, tagline, "Verify my identity".
- Reply style bar: Chat, Voice, Hybrid and an Avatar toggle (`aria-pressed`).
- Avatar: pure CSS face, states `idle`, `listening`, `thinking`, `delighted`, `helpful`, plus a speaking mouth. The backend chooses the state
  (`avatar_state` field); the client only shows `thinking` while waiting.
- Bubbles: assistant grey on the left, user green on the right, max width 78 %.
- Chips: outlined, `--mpd-action` text. Pillar cards: numbered badge, name, summary; clicking one asks the assistant about it.
- Master View: add `?master=1` to show mode, avatar state and timings (first reply, total, speech start).

## Rules every change must keep
- Text is inserted with text nodes only: no `innerHTML`, `eval` or `document.write` (a test enforces this).
- No inline styles and no external scripts, fonts or images: the hosted page's policy is `default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'`.
- Everything must work by keyboard: visible focus ring, buttons are real `<button>` elements, the log is `role="log"`, the avatar label is `role="status"`.
- Respect `prefers-reduced-motion`.
- Embedding on another site is one script tag: `<script src="https://BACKEND/widget/chat-widget.js" defer></script>`; the site must be listed in `CORS_ORIGINS`.
