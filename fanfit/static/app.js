// FanFit client. All Qloo/LLM text is inserted with textContent (never innerHTML).
const $ = (s) => document.querySelector(s);
const AGE_LABEL = {
  "24_and_younger": "24 and younger", "25_to_29": "25–29", "30_to_34": "30–34",
  "35_to_44": "35–44", "45_to_54": "45–54", "55_and_older": "55 and older",
};
const TYPE_LABEL = { artist: "Artist", podcast: "Podcast", tv_show: "TV show", person: "Creator / athlete", brand: "Brand" };
let config = { llm: false, qloo_mode: "fixture", presets: [] };
let busy = false;

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) n.append(kid instanceof Node ? kid : document.createTextNode(kid));
  return n;
}
const typeKey = (urn) => (urn || "").split(":").pop();

// ---------- streaming ----------
async function stream(url, body, onStep) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok && res.headers.get("content-type")?.includes("application/json")) return res.json();
  if (!res.ok) return { type: "error", code: "http", message: `Server error (${res.status}).` };
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "", last = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      const ev = JSON.parse(line);
      if (ev.type === "step") onStep(ev.text); else last = ev;
    }
  }
  return last || { type: "error", code: "internal", message: "The server closed the connection early." };
}

// ---------- trace / notices ----------
function traceReset() {
  const t = $("#trace"); t.replaceChildren(); t.hidden = false;
  $("#empty-state").hidden = true;
  const r = $(".results").getBoundingClientRect();
  if (r.top < 0 || r.top > innerHeight * 0.6) $(".results").scrollIntoView({ block: "start" });
}
function traceRunning(text) {
  const t = $("#trace");
  t.querySelector("li.running")?.classList.remove("running");
  t.append(el("li", { class: "running", text }));
}
function traceDone() { $("#trace li.running")?.classList.remove("running"); }
function notice(text, kind = "info") {
  const n = $("#notice");
  if (!text) { n.hidden = true; return; }
  n.className = "notice" + (kind === "error" ? " error" : "");
  n.textContent = text; n.hidden = false;
}
function setBusy(b) {
  busy = b;
  document.querySelectorAll(".primary, .preset").forEach((x) => (x.disabled = b));
}

// ---------- flow ----------
async function runResolve(payload, { autoConfirm = false } = {}) {
  if (busy) return;
  setBusy(true); notice(null);
  $("#cards").replaceChildren(); $("#confirm").hidden = true; $("#footnote").hidden = true; $("#compare").hidden = true;
  traceReset();
  traceRunning(payload.preset ? "Loading example brief…" : "Starting…");
  const r = await stream("/api/resolve", payload, traceRunning);
  traceDone();
  if (r.type === "error") { notice(r.message, "error"); setBusy(false); return; }
  if (r.status === "unresolved") {
    const missing = r.resolution.unresolved.length ? ` We couldn't find: ${r.resolution.unresolved.join(", ")}.` : "";
    notice(`Qloo didn't recognise this brief.${missing} Try the brand's exact name, or a broader category such as "coffee" or "running".`, "error");
    setBusy(false); return;
  }
  if (r.resolution.unresolved.length) notice(`Not found in Qloo and left out: ${r.resolution.unresolved.join(", ")}.`);
  showConfirm(r.brief, r.resolution);
  setBusy(false);
  if (autoConfirm) runShortlist(collectConfirm());
}

let confirmState = null;
function showConfirm(brief, res) {
  confirmState = { brief: { ...brief }, brand: res.brand, candidates: res.brand_candidates || [], tags: [...res.tags] };
  renderConfirm();
}
function renderConfirm() {
  const s = confirmState, box = $("#confirm");
  const brandPart = s.candidates.length > 1
    ? el("label", {}, "Which brand did you mean? ",
        el("select", { id: "c-brand", onchange: (e) => { s.brand = s.candidates.find((c) => c.entity_id === e.target.value) || null; } },
          el("option", { value: "", text: "None of these (use categories only)" }),
          s.candidates.map((c) => el("option", { value: c.entity_id, selected: s.brand?.entity_id === c.entity_id, text: c.name }))))
    : el("div", { class: "chips" }, s.brand ? el("span", { class: "chip qloo", text: `Brand: ${s.brand.name}` }) : el("span", { class: "chip", text: "No brand match: using categories only" }));
  const tags = el("div", { class: "chips" },
    s.tags.map((t, i) => el("span", { class: "chip qloo" }, `Taste tag: ${t.name}`,
      el("button", { type: "button", "aria-label": `Remove ${t.name}`, text: "×", onclick: () => { s.tags.splice(i, 1); renderConfirm(); } }))));
  const meta = [
    s.brief.age && `Age ${AGE_LABEL[s.brief.age]}`,
    s.brief.gender && s.brief.gender,
    s.brief.market && `Market: ${s.brief.market}`,
    `Looking for: ${s.brief.partner_types.map((t) => TYPE_LABEL[t] + "s").join(", ")}`,
  ].filter(Boolean).join(" · ");
  box.replaceChildren(
    el("h3", { text: "Is this what you meant?" }),
    el("p", { text: "These are the exact Qloo entities FanFit will use as the taste signal. Remove anything that's off." }),
    brandPart, tags, el("p", { text: meta }),
    el("div", { class: "actions" },
      el("button", { class: "primary", type: "button", text: "Find partners", onclick: () => runShortlist(collectConfirm()) })));
  box.hidden = false;
}
function collectConfirm() {
  const s = confirmState;
  return { brief: s.brief, brand: s.brand, tags: s.tags };
}

async function runShortlist(payload) {
  if (busy) return;
  if (!payload.brand && !payload.tags.length) { notice("Keep a brand or at least one taste tag to search with.", "error"); return; }
  setBusy(true); notice(null);
  $("#confirm").hidden = true; $("#cards").replaceChildren(); $("#compare").hidden = true;
  traceRunning("Asking Qloo for partner affinities…");
  const r = await stream("/api/shortlist", payload, traceRunning);
  traceDone();
  setBusy(false);
  if (r.type === "error") { notice(r.message, "error"); $("#confirm").hidden = false; return; }
  if (r.status === "empty") {
    notice("No partners matched. Try removing the age band or adding another partner type.", "error");
    $("#confirm").hidden = false; return;
  }
  if (r.llm === "failed") notice("The AI rationale is offline right now, so the cards show the Qloo evidence only.");
  else if (r.llm === "off") notice("AI rationale is off on this server, so the cards show the Qloo evidence only.");
  lastPayload = payload;
  lastCards = r.cards;
  renderCards(r.cards, payload.brief);
  $("#footnote").hidden = false;
  $("#compare-out").replaceChildren();
  $("#compare-btn").hidden = false;
  $("#compare").hidden = !config.llm;
}

// ---------- Qloo vs. AI alone ----------
let lastPayload = null;
const STATUS = {
  shortlisted: ["In FanFit's shortlist", "ok"],
  low: ["Qloo ranks it low for this brief", "warn"],
  not_ranked: ["In Qloo, but not a fit for this brief", "warn"],
  not_found: ["Not found in Qloo's taste graph", "bad"],
};
async function runCompare() {
  if (busy || !lastPayload) return;
  setBusy(true); $("#compare-btn").disabled = true;
  const out = $("#compare-out");
  const steps = el("ol", { class: "trace" });
  out.replaceChildren(steps);
  const step = (t) => { steps.querySelector("li.running")?.classList.remove("running"); steps.append(el("li", { class: "running", text: t })); };
  step("Starting comparison…");
  const r = await stream("/api/compare", lastPayload, step);
  steps.querySelector("li.running")?.classList.remove("running");
  setBusy(false); $("#compare-btn").disabled = false;
  if (r.type === "error") { out.append(el("div", { class: "notice error", text: r.message })); return; }
  $("#compare-btn").hidden = true;
  out.replaceChildren(renderCompare(r));
}
function renderCompare(r) {
  const n = r.llm_only.length;
  const count = (st) => r.llm_only.filter((x) => x.qloo.status === st).length;
  const hit = count("shortlisted"), missing = count("not_found"), weak = count("low") + count("not_ranked");
  const summary = n
    ? `AI alone suggested ${n} partners. Qloo's data backs ${hit}, rates ${weak} as a weak fit, and can't find ${missing} at all. FanFit surfaced ${r.qloo_only.length} partners that AI alone missed.`
    : "AI alone didn't return any usable suggestions for this brief.";
  const fmt = (q) => q.rank ? ` · rank ${q.rank} of ${q.of}, affinity ${q.affinity.toFixed(2)}` : "";
  return el("div", {},
    el("p", { class: "compare-summary", text: summary }),
    config.qloo_mode === "fixture"
      ? el("p", { class: "notice", text: "Demo mode: the sample data only contains fictional entities, so real names the AI suggests can't be found. With live Qloo data they're looked up and ranked." })
      : null,
    el("div", { class: "compare-grid" },
      el("div", {},
        el("h4", { text: "AI alone (no taste data)" }),
        el("ul", { class: "cmp-list" }, r.llm_only.map((x) => {
          const [label, kind] = STATUS[x.qloo.status];
          return el("li", {},
            el("strong", { text: x.name }), " ", el("span", { class: "type", text: TYPE_LABEL[x.type] || x.type }),
            el("div", { class: `status ${kind}`, text: label + fmt(x.qloo) }),
            x.reason ? el("div", { class: "hint", text: `AI's reason: ${x.reason}` }) : null);
        }))),
      el("div", {},
        el("h4", { text: "Only FanFit found" }),
        r.qloo_only.length
          ? el("ul", { class: "cmp-list" }, r.qloo_only.map((x) => el("li", {},
              el("strong", { text: x.name }), " ", el("span", { class: "type", text: TYPE_LABEL[typeKey(x.type)] || typeKey(x.type) }),
              el("div", { class: "status ok", text: `Rank #${x.rank} · Qloo affinity ${x.affinity.toFixed(2)}` }))))
          : el("p", { class: "hint", text: "AI alone found all of FanFit's picks this time." }))));
}
$("#compare-btn").addEventListener("click", runCompare);

// ---------- cards ----------
function renderCards(cards, brief) {
  $("#cards").replaceChildren(...cards.map((c) => renderCard(c, brief)));
}
function ageText(key, v) {
  const band = AGE_LABEL[key.slice(5)] || key.slice(5);
  const idx = `${v.value >= 0 ? "+" : "−"}${Math.abs(v.value).toFixed(2)}`;
  if (v.value >= 0.2) return `Over-indexes with ${band} year olds (${idx})`;
  if (v.value <= -0.2) return `Under-indexes with ${band} year olds (${idx})`;
  return `Roughly average reach with ${band} year olds (${idx})`;
}
function renderCard(c, brief) {
  const ev = c.evidence;
  const tastes = Object.entries(ev).filter(([k]) => k.startsWith("taste:"));
  const demo = Object.entries(ev).find(([k]) => k.startsWith("demo:"));

  const card = el("article", { class: "card" },
    el("div", { class: "card-head" },
      el("span", { class: "rank", text: `#${c.rank}` }),
      el("h3", { text: c.partner.name }),
      el("span", { class: "type", text: TYPE_LABEL[typeKey(c.partner.type)] || typeKey(c.partner.type) })),
    el("div", { class: "score", "data-ev": "affinity" },
      el("span", { text: "Qloo affinity" }),
      el("div", { class: "bar", role: "img", "aria-label": `Affinity ${c.affinity.toFixed(2)} of 1` }, el("i", { style: `width:${Math.round(c.affinity * 100)}%` })),
      el("b", { text: c.affinity.toFixed(2) })),
    el("div", { class: "ev-grid" },
      el("div", { class: "ev" },
        el("h4", { text: "Their audience is into" }),
        tastes.length ? el("div", { class: "chips" }, tastes.map(([k, v]) => el("span", { class: "chip", "data-ev": k, text: v.value })))
                      : el("p", { class: "hint", text: "No taste tags reported." })),
      el("div", { class: "ev" },
        el("h4", { text: "Audience fit" }),
        demo ? el("p", { class: "hint", "data-ev": demo[0], text: ageText(...demo) + (demo[1].target ? "" : " (their strongest age band)") }) : null,
        ev.market ? el("p", { class: "hint", "data-ev": "market", text: `Ranked for ${ev.market.value} with a Qloo location signal` }) : null,
        !demo && !ev.market ? el("p", { class: "hint", text: "No audience profile reported." }) : null)));

  if (c.claims?.length) {
    card.append(el("div", { class: "why" },
      el("h4", {}, "Why this fit ", el("small", { text: "· AI interpretation of the evidence above" })),
      el("ul", {}, c.claims.map((cl) => el("li", {}, cl.text, ...cl.evidence_ids.map((id) => citeChip(card, id, ev[id])))))));
  }
  if (config.llm) {
    const out = el("div", { class: "pitch-out" });
    const btn = el("button", { class: "secondary small", type: "button", text: "Draft outreach email",
      onclick: () => runPitch(c, card, btn, out) });
    card.append(el("div", { class: "pitch" }, btn, out));
  }
  return card;
}
let lastCards = [];
function brandLabel(p) { return p.brand ? p.brand.name : p.tags.map((t) => t.name).join(", "); }
async function runPitch(c, cardEl, btn, out) {
  btn.disabled = true; btn.textContent = "Drafting…";
  const others = lastCards.filter((x) => x !== c).map((x) => x.partner.name);
  const { claims, ...card } = c;
  let r;
  try {
    const res = await fetch("/api/pitch", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brand_label: brandLabel(lastPayload), card, others }) });
    r = await res.json();
  } catch { r = { type: "error", message: "Network error. Try again." }; }
  btn.disabled = false; btn.textContent = "Redraft email";
  if (r.type === "error") { out.replaceChildren(el("div", { class: "notice error", text: r.message })); return; }
  const p = r.pitch, brand = brandLabel(lastPayload);
  const plain = [`Subject: ${p.subject}`, "", p.opening, "", ...p.points.map((x) => `- ${x.text}`), "", p.ask, "", `${brand} partnerships team`].join("\n");
  const copy = el("button", { class: "secondary small", type: "button", text: "Copy email", onclick: async () => {
    try { await navigator.clipboard.writeText(plain); copy.textContent = "Copied"; } catch { copy.textContent = "Copy failed: select the text instead"; }
    setTimeout(() => (copy.textContent = "Copy email"), 2000);
  } });
  out.replaceChildren(el("div", { class: "email" },
    el("div", { class: "email-subject" }, el("span", { class: "hint", text: "Subject: " }), p.subject),
    el("p", { text: p.opening }),
    el("ul", {}, p.points.map((x) => el("li", {}, x.text, ...x.evidence_ids.map((id) => citeChip(cardEl, id, c.evidence[id]))))),
    el("p", { text: p.ask }),
    el("p", { class: "hint", text: `${brand} partnerships team` }),
    el("div", { class: "email-actions" }, copy, el("span", { class: "hint", text: "Every fact in this draft cites the card's Qloo evidence." }))));
}
function citeChip(card, id, v) {
  const label = id === "affinity" ? "affinity"
    : id.startsWith("demo:") ? `age ${AGE_LABEL[id.slice(5)] || id.slice(5)}` : id === "market" ? `market` : (v?.value ?? id);
  const on = () => card.querySelectorAll(`[data-ev="${CSS.escape(id)}"]`).forEach((n) => n.classList.add("hl"));
  const off = () => card.querySelectorAll(".hl").forEach((n) => n.classList.remove("hl"));
  return el("span", { class: "cite", tabindex: "0", title: `Evidence: ${v?.label || id}`, text: String(label),
    onmouseenter: on, onmouseleave: off, onfocus: on, onblur: off });
}

// ---------- wiring ----------
function selectTab(which) {
  for (const t of ["text", "form"]) {
    $(`#tab-${t}`).setAttribute("aria-selected", String(t === which));
    $(`#pane-${t}`).hidden = t !== which;
  }
}
$("#tab-text").addEventListener("click", () => selectTab("text"));
$("#tab-form").addEventListener("click", () => selectTab("form"));

$("#pane-text").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#brief-text").value.trim();
  if (!text) { notice("Describe your campaign first, or pick an example.", "error"); return; }
  runResolve({ text });
});
$("#pane-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const brief = {
    brand: f.get("brand") || null,
    category_terms: f.get("category") ? [f.get("category")] : [],
    age: f.get("age") || null,
    market: f.get("market") || null,
    partner_types: f.getAll("ptype"),
  };
  if (!brief.brand && !brief.category_terms.length) { notice("Enter a brand or a category.", "error"); return; }
  if (!brief.partner_types.length) { notice("Pick at least one partner type.", "error"); return; }
  runResolve({ brief });
});

(async function init() {
  config = await fetch("/api/config").then((r) => r.json());
  const banner = $("#banner");
  if (config.qloo_mode === "fixture") { banner.textContent = "Demo mode: fictional sample data, not live Qloo results."; banner.hidden = false; }
  else if (config.qloo_mode === "replay") { banner.textContent = "Showing cached Qloo data for the example briefs."; banner.hidden = false; }
  if (!config.llm) {
    $("#brief-text").disabled = true;
    $("#brief-text").placeholder = "Free-text briefs need the AI model, which is offline. Use the form or an example.";
    selectTab("form");
  }
  $("#presets").replaceChildren(...config.presets.map((p) =>
    el("button", { class: "preset", type: "button", onclick: () => runResolve({ preset: p.key }, { autoConfirm: true }) },
      el("strong", { text: p.title }), el("span", { text: p.text }))));
})();
