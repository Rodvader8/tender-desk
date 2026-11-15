// All untrusted text (tender text, model output, notes) is written with textContent, never innerHTML.
const $ = (id) => document.getElementById(id);
const money = (n) => (n == null ? "" : "$" + Number(n).toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const SAMPLE = `REQUEST FOR QUOTATION - Rear extension, 14 Example Street (invented sample)

We are seeking a fixed price for a single storey rear extension of approximately 36 square metres.
Scope of work:
1. Site cut and level for the extension footprint, 36 m2.
2. Supply and place 25MPa concrete for the slab on ground, 8 m3, including SL82 reinforcing mesh, 6 sheets.
3. Timber wall framing, 140x45 treated pine, approximately 120 lineal metres.
4. Roof trusses supplied and installed over the 36 m2 footprint.
5. Colorbond roof sheeting supplied and fixed, 42 m2.
6. Plasterboard fixed and set to internal walls and ceiling, 95 m2.
7. Electrician: 6 double power points and 8 LED downlights supplied and installed.
8. Scaffold hire for 3 weeks.
Please include building permit fees. Quote valid for 30 days.`;

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
let toastTimer;
function say(msg) { const s = $("status"); s.textContent = msg; s.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => s.classList.remove("show"), 3500); }
const TOKEN_KEY = "tender_desk_token";
const getToken = () => { try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; } };

async function api(path, opts) {
  const headers = { Authorization: "Bearer " + getToken() };
  if (opts && opts.body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { ...(opts || {}), headers });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) { askToken(); throw new Error("Enter your API token to continue."); }
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong (" + r.status + ")");
  return data;
}

// The token lives in sessionStorage only: it is gone when the tab closes.
function askToken() {
  const input = el("input", { id: "tok", type: "password", autocomplete: "off", placeholder: "API token" });
  const go = el("button", { class: "btn primary", type: "button" }, "Continue");
  go.addEventListener("click", () => {
    try { sessionStorage.setItem(TOKEN_KEY, input.value.trim()); } catch (_) {}
    refreshList().then(newForm).catch((e) => say(e.message));
  });
  $("main").replaceChildren(el("h2", { text: "API token" }),
    el("p", { class: "hint", text: "This server needs its API token (TENDER_DESK_API_TOKEN). It is kept for this browser tab only." }),
    el("label", { for: "tok", text: "Token" }), input, el("div", { class: "row" }, go));
  input.focus();
}
const badge = (s) => el("span", { class: "badge " + s, text: s.replaceAll("_", " ") });

let selected = null;
async function refreshList() {
  const items = await api("/tenders");
  const ul = $("list"); ul.replaceChildren();
  for (const t of items) {
    const b = el("button", { type: "button", class: t.id === selected ? "sel" : "", onclick: () => openTender(t.id) },
      el("span", { class: "t-title", text: t.title }),
      el("span", { class: "t-meta" }, badge(t.status), t.total != null ? money(t.total) : ""));
    ul.append(el("li", {}, b));
  }
  if (!items.length) ul.append(el("li", { class: "hint", text: "No tenders yet." }));
}

function newForm() {
  selected = null; refreshList();
  const title = el("input", { id: "f-title", maxlength: "200", placeholder: "e.g. Rear extension, 14 Example Street" });
  const text = el("textarea", { id: "f-text", maxlength: "20000", placeholder: "Paste the request for quotation here" });
  const go = el("button", { class: "btn primary", type: "button" }, "Price this tender");
  go.addEventListener("click", async () => {
    if (!title.value.trim() || text.value.trim().length < 20) return say("Add a title and the tender text (at least 20 characters).");
    go.disabled = true; say("Reading the tender and pricing it. This takes a few seconds.");
    try { const t = await api("/tenders", { method: "POST", body: JSON.stringify({ title: title.value.trim(), text: text.value }) }); await refreshList(); openTender(t.id); }
    catch (e) { say(e.message); } finally { go.disabled = false; }
  });
  const sample = el("button", { class: "btn", type: "button", onclick: () => { title.value = "Rear extension, 14 Example Street"; text.value = SAMPLE; } }, "Load the sample tender");
  $("main").replaceChildren(el("h2", { text: "New tender" }),
    el("p", { class: "hint", text: "The model drafts a priced quote. Nothing is saved as a quote until you approve it." }),
    el("label", { for: "f-title", text: "Title" }), title, el("label", { for: "f-text", text: "Tender text" }), text,
    el("div", { class: "row" }, go, sample));
}

function draftView(d) {
  const rows = d.lines.map((l, i) => el("tr", { class: l.flags.length ? "flagged" : "" },
    el("td", { text: String(i + 1) }), el("td", { text: l.description }),
    el("td", { class: "num", text: l.qty + " " + l.unit }),
    el("td", {}, l.item_name || el("em", { text: "no price" }), ...l.flags.map((f) => el("span", { class: "flag", text: f }))),
    el("td", { class: "num", text: money(l.unit_price) }), el("td", { class: "num", text: money(l.line_total) }),
    el("td", { text: l.confidence })));
  const head = ["#", "Tender line", "Qty", "Matched price item", "Unit price", "Line total", "Confidence"]
    .map((h, i) => el("th", { scope: "col", class: [2, 4, 5].includes(i) ? "num" : "", text: h }));
  const stat = (v, l) => el("div", { class: "stat" }, el("b", { text: v }), el("span", { text: l }));
  return el("div", {},
    el("p", { text: d.job_summary }),
    d.needs_attention ? el("div", { class: "callout", text: d.flags.length + " item(s) need your attention. Flagged lines are highlighted; lines with no price are not in the total." }) : el("div", { class: "callout ok", text: "No flags raised on this draft." }),
    el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, ...head)), el("tbody", {}, ...rows))),
    el("div", { class: "totals" }, stat(money(d.subtotal), "Subtotal"), stat(d.margin_pct + "%", "Margin (from comparable jobs)"), stat(money(d.total), "Quote total")),
    el("h3", { text: "Comparable past jobs" }),
    el("ul", {}, ...d.comparables.map((c) => el("li", { text: c.title + ": margin " + c.margin_pct + "%, total " + money(c.total) }))));
}

function decisionForm(tid, digest) {
  const by = el("input", { id: "d-by", maxlength: "80", autocomplete: "name" });
  try { by.value = localStorage.getItem("reviewer") || ""; } catch (_) {}
  const notes = el("textarea", { id: "d-notes", class: "short", maxlength: "2000", placeholder: "Optional. If you reject with notes, the draft is revised once using them." });
  const send = async (approve) => {
    if (!by.value.trim()) return say("Enter your name so the decision is on the record.");
    try { localStorage.setItem("reviewer", by.value.trim()); } catch (_) {}
    btns.forEach((b) => (b.disabled = true)); say(approve ? "Saving the approved quote." : "Recording your decision.");
    try { await api("/tenders/" + tid + "/decision", { method: "POST", body: JSON.stringify({ approve, by: by.value.trim(), notes: notes.value, draft_digest: digest }) }); await refreshList(); openTender(tid); }
    catch (e) { say(e.message); btns.forEach((b) => (b.disabled = false)); }
  };
  const ok = el("button", { class: "btn good", type: "button", onclick: () => send(true) }, "Approve and save quote");
  const no = el("button", { class: "btn danger", type: "button", onclick: () => send(false) }, "Reject");
  const btns = [ok, no];
  return el("div", {}, el("h3", { text: "Your decision" }), el("label", { for: "d-by", text: "Your name" }), by,
    el("label", { for: "d-notes", text: "Notes" }), notes, el("div", { class: "row" }, ok, no),
    el("p", { class: "hint", text: "Approving saves the quote. Rejecting with notes asks for one revised draft; rejecting without notes closes the tender." }));
}

async function openTender(id) {
  selected = id; refreshList();
  let t; try { t = await api("/tenders/" + id); } catch (e) { return say(e.message); }
  const main = $("main");
  main.replaceChildren(el("h2", { text: t.title }), el("div", { class: "t-meta" }, badge(t.status), new Date(t.created_at).toLocaleString("en-AU")));
  if (t.draft) main.append(draftView(t.draft), decisionForm(id, t.draft_digest));
  else if (t.quote) {
    main.append(el("div", { class: "callout " + (t.quote.status === "approved" ? "ok" : "bad"), text: "Quote " + t.quote.status + " by " + t.quote.decided_by + (t.quote.notes ? ". Notes: " + t.quote.notes : "") }), draftView(t.quote.draft));
  } else main.append(el("div", { class: "callout bad", text: "This tender did not finish. See the audit trail below." }));
  main.append(el("details", {}, el("summary", { text: "Audit trail (" + t.audit.length + ")" }),
    el("ul", { class: "audit" }, ...t.audit.map((a) => el("li", { text: new Date(a.at).toLocaleTimeString("en-AU") + "  " + a.event + "  " + JSON.stringify(a.detail) })))));
  main.focus();
}

$("new-btn").addEventListener("click", newForm);
refreshList().then(newForm).catch((e) => say(e.message));
