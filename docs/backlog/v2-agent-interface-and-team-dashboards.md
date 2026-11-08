# Backlog v2: AI Agent Interface and Team Dashboards

Continues the backlog in the plan file (E0 to E23). New epics are E24 to E31. Same rules: Fibonacci points (1, 2, 3, 5, 8), a story above 8 must be split, IDs are `S<epic>.<n>`, priorities P0 (must) to P3 (later). Status is not tracked here; read the repo and git history.

## Personas
| Persona | Who |
|---|---|
| Visitor | Anyone on the website, not verified |
| Customer | A visitor who verified email and phone |
| Support agent | Staff who answer escalations |
| Sales rep | Staff who work leads and quotes |
| Team lead | Manages the team and reads reports |
| AI quality owner | Decides what the assistant should say and how well it does |
| Operator | Engineer who runs the platform |
| Security officer | Owns privacy, access and audit |

## What exists today (so it is not built twice)
| Area | Today |
|---|---|
| Interface | Chat with streaming, Chat / Voice / Hybrid styles, CSS avatar, uploads, mic, identity verification, account panel (memory consent, export, delete, Google connect, step-up), pillar cards, Master View strip |
| Staff console `/admin` | Overview, escalation list and resolve, people lookup and merge, cache purge, undelivered messages, quote approve or decline, approved reply patterns. One shared staff token. |
| Grafana | "MPD Agent Health" (turns, latency, mode mix, evaluator verdicts, escalations, tools, cache, tokens, PII detections) and "MPD Cost, Delivery and Quality" (tokens, messages by channel, blocked messages, tool latency and errors, offline eval scores, escalations by reason), plus alert rules in `observability/alerts/mpd.yml` |

## Totals
| Epic | Name | Points |
|---|---|---|
| E24 | Conversation experience | 30 |
| E25 | Human handoff and booking | 21 |
| E26 | Multimodal and language | 32 |
| E27 | Trust, accessibility and embedding | 28 |
| E28 | Team: conversations and escalations | 32 |
| E29 | Team: sales and business | 27 |
| E30 | Team: AI quality and knowledge | 44 |
| E31 | Team: operations, cost and security | 30 |
| | **Total** | **244** |

---

# PART A. THE AGENT INTERFACE (what customers see)

## E24. Conversation experience (P1, 30 pts)

**S24.1 Rate an answer** | 3 pts | P1
As a visitor, I want to mark an answer helpful or not helpful, so the team can fix weak answers.
- AC: thumbs up and down on every assistant reply; a down vote offers an optional reason (wrong, unclear, off topic, other); the rating is stored with the turn id and never shown to other users.
- Feeds: S30.1, S30.2.

**S24.2 Show sources** | 5 pts | P1
As a visitor, I want to see where an answer came from, so I can trust it.
- AC: replies that used company documents show source chips (document and pillar name); tapping a chip shows the cited passage; replies with no source say so; sources never include personal data.
- Builds on: retrieval citations (S7.5).

**S24.3 Rich replies** | 5 pts | P1
As a visitor, I want choices, tables and steps shown clearly, so replies are easy to act on.
- AC: the backend can return buttons (quick replies), a table, a numbered list and a card; the widget renders each from data, never from raw HTML; a "copy" button on each reply; long replies collapse with "show more".

**S24.4 Conversation history** | 5 pts | P1
As a customer, I want my past conversations to be there when I come back, so I do not repeat myself.
- AC: a history panel lists my last conversations with date and first question; I can open one and continue it; I can delete one; guests keep only the current tab's conversation.

**S24.5 Progress and tool status** | 3 pts | P2
As a visitor, I want to see what the assistant is doing while I wait, so it does not feel stuck.
- AC: shows "Searching our documents", "Checking the calendar" and similar from tool events; a visible "taking longer than usual" after 10 s; the avatar shows the thinking state.

**S24.6 Stop, regenerate, edit** | 3 pts | P2
As a visitor, I want to stop a reply, ask again, or fix my last question.
- AC: a Stop button cancels the turn; Regenerate reruns the last question; editing the last message replaces that turn; a cancelled turn is recorded as cancelled.

**S24.7 Errors, offline and retry** | 3 pts | P1
As a visitor, I want clear messages when something fails, so I know what to do.
- AC: network loss shows an offline banner and queues the draft; a failed reply shows Retry; a provider outage shows a friendly message and the contact option (S25.3); no raw error text is ever displayed.

**S24.8 Send me this conversation** | 3 pts | P3
As a customer, I want a copy of the chat by email or as a file.
- AC: a verified customer can email themselves a transcript or download it; it follows the same masking and consent rules as the data export.

## E25. Human handoff and booking (P1, 21 pts)

**S25.1 Talk to a person** | 5 pts | P1
As a visitor, I want to reach a human easily, so I am never stuck with the bot.
- AC: a persistent "Talk to a person" action; shows team hours and the expected response time; after handoff the widget shows the reference number and what happens next; outside hours it offers S25.3.
- Builds on: escalation flow (S6.6).

**S25.2 Staff replies inside the widget** | 8 pts | P1
As a customer, I want the staff member's reply to appear in the same chat, so the conversation continues in one place.
- AC: staff messages stream to the widget in real time; the bot stays paused for that conversation; the widget labels who is speaking (assistant or staff name); the customer can return to the assistant when the staff member closes the case.
- Depends on: S28.3.

**S25.3 Leave a message or request a callback** | 3 pts | P1
As a visitor, I want to leave contact details when nobody is online.
- AC: a short form (name, email or phone, topic, preferred time); creates an escalation with the conversation summary; sends a confirmation message; respects consent rules.

**S25.4 Book a call in the chat** | 5 pts | P2
As a prospect, I want to pick a time for a discovery call without leaving the chat.
- AC: shows free slots in my time zone from the calendar tool; I choose one; I get an on-screen and emailed confirmation and can reschedule or cancel; double bookings are impossible.
- Builds on: Comms and Scheduling agent (S6.5).

## E26. Multimodal and language (P2, 32 pts)

**S26.1 Upload experience** | 3 pts | P1
As a visitor, I want to see what I attached and what happened to it.
- AC: shows file name, size, progress and a remove button; rejects unsupported types and sizes with a clear message before upload; shows "reading your file" and "ready"; the assistant says which file it used.

**S26.2 Tables and charts in files** | 8 pts | P2
As a customer, I want the assistant to understand tables, pie charts and bar charts in my documents and images.
- AC: Word and PDF tables become Markdown rows; chart images are described by the vision model (type, title, axes, categories, values, marked approximate unless labelled); each table is kept whole when indexed; a cap per file bounds cost; tests use sample files.

**S26.3 Voice conversation** | 8 pts | P2
As a visitor, I want to talk to the assistant and hear it answer.
- AC: push-to-talk or hands-free; the transcript appears as I speak; I can interrupt the voice reply; spoken replies use the short style; works on mobile; latency is shown in Master View.
- Needs: speech services configured.

**S26.4 French and language switch** | 5 pts | P2
As a French speaker, I want the interface and company content in French.
- AC: a language switch in the header; `company.json` gains French fields built from French documents; welcome, chips, pillars and mode labels switch; replies follow the language chosen.

**S26.5 3D avatar option** | 8 pts | P3
As a visitor, I want a more lifelike avatar.
- AC: an optional 3D avatar (open-source, in the browser) driven by the same avatar state and spoken text; falls back to the 2D face on weak devices; no GPU server.

## E27. Trust, accessibility and embedding (P1, 28 pts)

**S27.1 Privacy notice and consent** | 3 pts | P1
As a visitor, I want to know how my data is used, so I can decide what to share.
- AC: a short notice on first open with a link to the full policy; memory is off until I opt in; I can open the notice again from the menu.

**S27.2 Accessibility to WCAG 2.2 AA** | 5 pts | P1
As a visitor using a keyboard or screen reader, I want the chat to be fully usable.
- AC: an audit with fixes; focus is trapped in the open panel and returned on close; announcements for new replies; contrast and target sizes pass; automated checks run in CI.

**S27.3 AI disclosure** | 2 pts | P1
As a visitor, I want to know I am talking to an AI.
- AC: a visible label and a first-message line; the assistant never claims to be human; escalation text names that a person will take over.

**S27.4 Abuse protection for anonymous users** | 5 pts | P1
As the business, I want bots and scripts kept out without hurting real visitors.
- AC: a lightweight human check (Turnstile or similar) before many messages or any upload; limits per IP and per session; blocked attempts are counted for S31.4.

**S27.5 Theming and white label** | 5 pts | P2
As a team lead, I want the widget to match each site without code changes.
- AC: colors, logo, title and welcome text come from a site config; defaults are the Master Pro Dev look; the design rules document stays the reference.

**S27.6 Widget performance** | 3 pts | P2
As a site owner, I want the widget not to slow my pages.
- AC: the script loads after the page and is under an agreed size; assets are cached; the chat connection opens only on first use; a budget test runs in CI.

**S27.7 Per-site embed keys** | 5 pts | P1
As the business, I want each embedding site to have its own key and permissions.
- AC: a site key identifies the site; each key lists allowed origins and which actions the site can use (for example chat only, or chat plus uploads); a key can be revoked; the server checks the key, not only the Origin header.
- Context: CORS alone does not stop non-browser callers.

---

# PART B. TEAM DASHBOARDS (what the staff see)

All team dashboards need: sign-in with roles (S28.4), PII masked by default, every view of personal data written to the audit log, and CSV export for the data on screen.

## E28. Team: conversations and escalations (P1, 32 pts)

**S28.1 Live conversations board** | 5 pts | P1
As a support agent, I want to see active conversations, so I can step in early.
- AC: a live list with channel, topic, age, language, sentiment flag and whether the bot is paused; filter by channel and status; updates within 5 seconds.

**S28.2 Conversation viewer and search** | 8 pts | P1
As a team lead, I want to open any conversation and see what happened.
- AC: full transcript with the agent, mode and tools used per turn, timing and evaluator verdict; search by keyword, date, channel and rating; personal data masked unless the role may reveal it, and each reveal is logged.

**S28.3 Escalation inbox v2** | 8 pts | P1
As a support agent, I want to work cases with owners and deadlines.
- AC: assign to a person; status (new, open, waiting, resolved); a service-level timer per priority with warnings; internal notes; tags; reply to the customer in the widget (S25.2) or by email; a one-click summary of the conversation.
- Builds on: the escalation list and resolve actions in `/admin`.

**S28.4 Staff accounts, roles and audit** | 8 pts | P0
As a security officer, I want staff to sign in as themselves with limited roles, instead of sharing one token.
- AC: single sign-on (provider decided in the open questions); roles (support, sales, quality, admin); the single staff token is retired; an audit log viewer shows who looked at or changed what, filterable and exportable.

**S28.5 Reply library** | 3 pts | P2
As a support agent, I want ready-made replies, so I answer faster and consistently.
- AC: a searchable library of approved replies in English and French; insert into a staff reply; usage counts; admins approve new entries.
- Builds on: approved reply patterns review.

## E29. Team: sales and business (P1, 27 pts)

**S29.1 Funnel dashboard** | 5 pts | P1
As a team lead, I want to see how visitors become customers.
- AC: visitors, conversations, verified, leads, quotes sent, quotes accepted, paid, as counts and conversion rates by day, week and channel; compare periods.

**S29.2 Leads board** | 8 pts | P1
As a sales rep, I want to manage leads through the stages.
- AC: a board by stage (the "3 Es" once defined); a lead page with the need, timeline, budget, conversation and quotes; assign an owner; add notes; move stages (rules enforced); export to CSV.
- Builds on: lead stage state machine (S18.6).

**S29.3 Quote approvals v2** | 3 pts | P1
As a sales rep, I want to review held-back quotes with the numbers in front of me.
- AC: shows line items, totals, the reason it was held, and a comparison with similar past quotes; approve, adjust or decline with a reason.

**S29.4 Meetings dashboard** | 3 pts | P2
As a sales rep, I want to see booked calls.
- AC: upcoming calls with who, topic and the conversation summary; booked, held and no-show counts; link to the lead.

**S29.5 Pillar interest report** | 3 pts | P2
As a team lead, I want to know which services people ask about.
- AC: counts and trends for the twelve pillars from questions, chips and pillar-card clicks; top unanswered topics per pillar; by site and by week.

**S29.6 Revenue and payments** | 5 pts | P2
As a team lead, I want to see money collected.
- AC: payments, refunds and failures from Stripe webhooks; revenue by pillar and period; quotes awaiting payment; reconcile against Stripe totals.
- Depends on: payments enabled.

## E30. Team: AI quality and knowledge (P1, 44 pts)

**S30.1 Quality scorecard** | 5 pts | P1
As an AI quality owner, I want one page that says how good the assistant is.
- AC: helpful rate from ratings, evaluator pass rate, "no answer" rate, escalation rate, grounded-answer rate; per agent, per language and per week; targets and trend arrows.
- Builds on: evaluator metrics and offline eval scores in Grafana.

**S30.2 Failure review queue** | 8 pts | P1
As an AI quality owner, I want to review bad answers and turn them into fixes.
- AC: a queue of down-voted, low-scored and escalated turns; open a turn to see the question, answer, sources and tools; label the cause (wrong, missing knowledge, wrong tool, tone); one click adds it to the golden evaluation set or creates a knowledge task.

**S30.3 Knowledge gaps** | 5 pts | P1
As an AI quality owner, I want to see what customers ask that we cannot answer.
- AC: clusters of unanswered or low-confidence questions with counts and examples; suggested pillar; mark as "document needed" and assign it.

**S30.4 Prompt and agent versions with experiments** | 8 pts | P2
As an AI quality owner, I want to change prompts safely and compare results.
- AC: lists every prompt version in use; publish a new version to a percentage of traffic; shows quality, latency and cost per version; roll back in one click; changes are audited.
- Builds on: prompt registry (S2.7).

**S30.5 Model comparison and tiers** | 5 pts | P2
As an AI quality owner, I want to compare models for each tier.
- AC: shows pass rate, speed and cost from `scripts/compare_models.py` runs; the model per tier is visible and changing it is an admin action with an audit entry.

**S30.6 Memory governance console** | 5 pts | P2
As a security officer, I want to see and control what the assistant remembers.
- AC: counts of memories by type and age; look up one person's memories with consent status; delete on request with confirmation; shows the nightly consolidation report.
- Builds on: memory governance (S19.21).

**S30.7 Knowledge base manager** | 8 pts | P1
As a team lead, I want to update company knowledge without a deployment.
- AC: upload or replace documents; shows index status and last indexed time per document; trigger a reindex; preview the pillar content built for the website (`company.json`) and approve it; changes are versioned and can be rolled back.
- Replaces: the documents baked into the worker image.

## E31. Team: operations, cost and security (P1, 30 pts)

**S31.1 Service health board** | 3 pts | P1
As an operator, I want one view of whether everything is up.
- AC: status and uptime for the backend, worker, tool services, Postgres and Redis; latency against targets; deployment history with the commit; links to runbooks.

**S31.2 Cost and budget** | 5 pts | P1
As a team lead, I want to see what the assistant costs.
- AC: model spend by tier, agent and channel; Railway usage against the spend limit; cost per conversation and per lead; projected month end; alerts at 50, 75 and 90 percent of budget.

**S31.3 Model provider status** | 3 pts | P1
As an operator, I want to know at once when a model provider fails.
- AC: per-provider success rate, 402, 429 and timeout counts, circuit-breaker state and fallback use; an alert on payment-required or sustained errors.
- Why: it would have flagged the current Hugging Face "payment required" failure.

**S31.4 Security and privacy board** | 5 pts | P1
As a security officer, I want to watch for abuse and privacy problems.
- AC: PII detections by boundary, canary hits, failed sign-ins and code requests, blocked abuse, staff access to personal data, data-request queue with due dates.

**S31.5 Channel delivery board** | 3 pts | P2
As an operator, I want to see message delivery by channel.
- AC: sent, delivered, failed, blocked by consent for SMS, WhatsApp and email; the dead-letter list with retry; opt-out counts.
- Builds on: delivery tracking (S22.5) and the existing undelivered list.

**S31.6 Alert routing** | 3 pts | P1
As an operator, I want the right person told about the right problem.
- AC: alerts go to Slack or email by severity; each alert links to its runbook; acknowledge and snooze; weekly list of noisy alerts.

**S31.7 Widget analytics** | 5 pts | P2
As a team lead, I want to know how the widget performs on each site.
- AC: loads, opens, first messages, conversations, drop-off point and ratings by site and page; no personal data; respects consent.

**S31.8 Scheduled reports** | 3 pts | P3
As a team lead, I want a weekly summary without logging in.
- AC: an emailed summary (funnel, quality, cost, top topics, open escalations) every Monday; recipients and sections configurable.

---

## Suggested order
1. **First (safety and basics):** S28.4 staff accounts, S31.3 provider status, S31.2 cost, S27.3 AI disclosure, S27.1 consent, S27.7 site keys, S24.7 error states.
2. **Then (daily team use):** S28.1 to S28.3 conversations and escalations, S25.1 to S25.3 handoff, S30.7 knowledge manager, S24.1 ratings, S30.1 scorecard.
3. **Then (growth):** S29.1 to S29.3 funnel, leads and quotes, S30.2 to S30.3 failure review and gaps, S24.2 to S24.4 sources, rich replies and history.
4. **Later:** voice, French, charts and tables, 3D avatar, experiments, scheduled reports.

## Open questions
1. Which sign-in provider for staff (Google Workspace, Microsoft, or another)?
2. Which roles and who may see unmasked personal data?
3. Which CRM, if any, should leads sync to (the plan so far keeps leads in our database)?
4. Team hours and response targets for handoff, and who staffs the inbox?
5. What are the "3 Es" stages, and who approves custom quotes?
6. Are other websites besides masterprodev.com going to embed the widget?
7. Where should dashboards live: inside `/admin`, in Grafana, or both? (Suggestion: operational metrics in Grafana, people-and-case work in `/admin`.)
