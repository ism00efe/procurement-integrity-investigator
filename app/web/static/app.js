const state = { limit: 25, offset: 0, total: 0, search: "", riskLevel: "", diversify: true };

// Selected by scripts/validate_ranking.py as the strongest hackathon demo
// case: highest deterministic score with the most independent indicators
// (6/9) of any case in the real dataset, and a coherent, explainable story
// (a national COVID-19 print-materials rollout where one supplier won every
// zonal lot). See the validation write-up for the full rationale.
const FEATURED_CASE_ID = "ocds-gyl66f-521003001-000378";

const INDICATOR_LABELS = {
  SINGLE_BIDDER: "only one bidder competed",
  LOW_COMPETITION_METHOD: "awarded via a low-competition method",
  SHORT_TENDER_PERIOD: "unusually short bidding window",
  PRICE_DEVIATION: "price deviates from the tender estimate",
  SUPPLIER_CONCENTRATION: "supplier holds an outsized share of this buyer's spend",
  REPEATED_RELATIONSHIP: "supplier is a repeat winner with this buyer",
  MISSING_SUPPLIER_IDENTITY: "winning supplier's identity is undisclosed",
  PEER_PRICE_OUTLIER: "price is an outlier against comparable tenders",
  BUYER_AWARD_BURST: "buyer issued an unusual burst of awards",
};
const indicatorLabel = (id) => INDICATOR_LABELS[id] || id.toLowerCase().replaceAll("_", " ");

const fmtNum = (n) => Number(n).toLocaleString("en-US");

const fmtMoney = (amount, currency) => {
  if (amount === null || amount === undefined) return "—";
  return `${fmtNum(Math.round(amount))} ${currency || ""}`.trim();
};

// `large` adds the "/100" denominator and a caption. The table omits both:
// its column header carries the scale once, for all 25 rows at a time.
function riskMeter(score, level, large = false) {
  const pct = Math.max(4, Math.min(100, Number(score) || 0));
  return `
    <div class="risk-meter ${large ? "large" : ""}">
      <div class="risk-meter-num ${level}">${score}${large ? '<span class="risk-meter-max">/100</span>' : ""}</div>
      <div class="risk-meter-track"><div class="risk-meter-fill ${level}" style="width:${pct}%"></div></div>
      ${large ? '<div class="risk-meter-caption">risk score</div>' : ""}
    </div>`;
}

async function loadSummary() {
  const res = await fetch("/api/summary");
  const data = await res.json();
  document.getElementById("stat-total").textContent = fmtNum(data.total_procurements_analyzed);
  document.getElementById("stat-risky").textContent = fmtNum(data.risky_procurements_detected);
  document.getElementById("stat-high").textContent = fmtNum(data.high_risk_cases);
  document.getElementById("stats-secondary").textContent =
    `Also ${fmtNum(data.medium_risk_cases)} medium-risk. Across ${fmtNum(data.distinct_buyers)} buyers ` +
    `and ${fmtNum(data.distinct_suppliers)} suppliers.`;
}

async function loadHealth() {
  const res = await fetch("/api/health");
  const data = await res.json();
  const badge = document.getElementById("llm-badge");
  if (data.llm_configured) {
    badge.textContent = `AI investigation: ON (${data.llm_model})`;
    badge.className = "llm-badge on";
  } else {
    badge.textContent = "AI investigation: OFF (set OPENROUTER_API_KEY)";
    badge.className = "llm-badge off";
  }
}

async function loadSpotlight() {
  const el = document.getElementById("spotlight");
  try {
    const res = await fetch(`/api/cases/${encodeURIComponent(FEATURED_CASE_ID)}`);
    const c = await res.json();
    const top = (c.indicators || []).slice(0, 3).map((i) => indicatorLabel(i.id));
    const relCount = c.related_supplier_cases ? c.related_supplier_cases.other_case_count + 1 : null;
    el.innerHTML = `
      <div class="spotlight-eyebrow">★ Recommended case &middot; strongest independent-indicator match in this dataset</div>
      <div class="spotlight-body">
        ${riskMeter(c.risk_score, c.risk_level, true)}
        <div class="spotlight-main">
          <p class="spotlight-title">${c.tender_title || "Untitled tender"}</p>
          <p class="spotlight-buyer">${c.buyer_name || "Unknown buyer"} &middot; <span class="mono">${c.case_id}</span></p>
          <p class="spotlight-why">${top.map((t) => `<span class="signal-chip">${t}</span>`).join("")}</p>
          ${relCount ? `<p class="spotlight-pattern">Part of a pattern: this buyer awarded <strong>${relCount} contracts</strong> to the same supplier in this dataset.</p>` : ""}
        </div>
        <button id="spotlight-open" class="run-btn">Open full investigation &rarr;</button>
      </div>`;
    document.getElementById("spotlight-open").addEventListener("click", () => openCase(FEATURED_CASE_ID));
  } catch (err) {
    el.innerHTML = `<p class="muted">Recommended case unavailable.</p>`;
  }
}

async function loadCases() {
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.search) params.set("search", state.search);
  if (state.riskLevel) params.set("risk_level", state.riskLevel);
  if (state.diversify) params.set("diversify", "true");
  const res = await fetch(`/api/cases?${params}`);
  const data = await res.json();
  state.total = data.total;
  renderRows(data.cases);
  renderPager();
}

function renderRows(cases) {
  const tbody = document.getElementById("case-rows");
  tbody.innerHTML = "";
  if (!cases.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="4">
      No contracts match this search or filter. Clear the search box or choose "All risk levels".
    </td></tr>`;
    return;
  }
  for (const c of cases) {
    const tr = document.createElement("tr");
    tr.className = `row-${c.risk_level}`;
    const signals = c.main_indicators.map((i) => indicatorLabel(i));
    tr.innerHTML = `
      <td>${riskMeter(c.risk_score, c.risk_level)}</td>
      <td>
        <div class="case-cell-title">${c.tender_title || "—"}</div>
        <div class="case-cell-buyer">${c.buyer || "—"}</div>
      </td>
      <td class="mono">${fmtMoney(c.contract_value, c.currency)}</td>
      <td><span class="signal-summary">${signals.join(" &middot; ") || "No indicators triggered"}</span></td>
    `;
    tr.addEventListener("click", () => openCase(c.case_id));
    tbody.appendChild(tr);
  }
}

function renderPager() {
  const page = Math.floor(state.offset / state.limit) + 1;
  const pages = Math.max(1, Math.ceil(state.total / state.limit));
  document.getElementById("page-info").textContent = `Page ${page} of ${pages} (${state.total} cases)`;
  document.getElementById("prev-page").disabled = state.offset === 0;
  document.getElementById("next-page").disabled = state.offset + state.limit >= state.total;
}

document.getElementById("prev-page").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  loadCases();
});
document.getElementById("next-page").addEventListener("click", () => {
  state.offset += state.limit;
  loadCases();
});
document.getElementById("search").addEventListener("input", (e) => {
  state.search = e.target.value;
  state.offset = 0;
  loadCases();
});
document.getElementById("risk-filter").addEventListener("change", (e) => {
  state.riskLevel = e.target.value;
  state.offset = 0;
  loadCases();
});
function closeDrawer() {
  document.getElementById("overlay").classList.add("hidden");
  document.body.classList.remove("drawer-open");
}
document.getElementById("close-drawer").addEventListener("click", closeDrawer);
// Clicking the dimmed backdrop and pressing Escape are both what people try
// first to get out of a panel like this; neither did anything before.
document.getElementById("overlay").addEventListener("click", (e) => {
  if (e.target.id === "overlay") closeDrawer();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("overlay").classList.contains("hidden")) closeDrawer();
});
document.getElementById("diversify-toggle").addEventListener("change", (e) => {
  state.diversify = e.target.checked;
  state.offset = 0;
  loadCases();
});

const STATUS_ICON = { verified: "✓", downgraded: "⚠", rejected: "✗" };
const STATUS_LABEL = {
  verified: "Recomputed from source data",
  downgraded: "Not independently checked",
  rejected: "Contradicted by source data",
};

function renderEvidenceChips(refs, currentCaseId) {
  if (!refs || !refs.length) return '<span class="evidence-chip none">no evidence cited</span>';
  return refs.map((r) => {
    const [scheme, ...rest] = r.split(":");
    const idPart = rest.join(":");
    const isCase = scheme === "case" && idPart && idPart !== currentCaseId;
    const isAward = scheme === "award";
    const openTarget = isCase ? idPart : (isAward ? idPart.split(":")[0] : null);
    const clickable = openTarget && openTarget !== currentCaseId;
    return `<span class="evidence-chip ${clickable ? "clickable" : ""}" ${clickable ? `data-open-case="${openTarget}"` : ""} title="${r}">
      <span class="evidence-scheme">${scheme}</span>${idPart.length > 18 ? idPart.slice(0, 16) + "…" : idPart}
    </span>`;
  }).join("");
}

async function openCase(caseId) {
  const overlay = document.getElementById("overlay");
  const content = document.getElementById("drawer-content");
  overlay.classList.remove("hidden");
  document.body.classList.add("drawer-open");
  content.innerHTML = `<p class="muted">Loading case ${caseId}…</p>`;
  document.querySelector(".drawer").scrollTop = 0;

  const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}`);
  const c = await res.json();

  content.innerHTML = renderDrawerStepper() +
    `<div id="stage-discover">` + renderCaseHeader(c) + renderIndicatorSection(c) + renderRelatedCasesSection(c) + `</div>` +
    `<div id="stage-investigate">` + renderInvestigationPlaceholder(c) + `</div>` +
    `<div id="stage-verify" class="section"><h3><span class="stage-num">3</span>Independent verification</h3><p class="muted" id="verify-placeholder">Every AI claim is taken back to the database and re-checked. Claims that state a number get that number recomputed from the raw records; the rest are explicitly marked as not independently checked. Run the investigation to see results here.</p><div id="verify-result"></div></div>` +
    `<div id="stage-conclude" class="section"><h3><span class="stage-num">4</span>Conclusion</h3><p class="muted" id="conclude-placeholder">The final report is built only from claims that survived verification, and says plainly which of them were independently recomputed. Hedged, human-review language throughout.</p><div id="conclude-result"></div></div>`;

  bindOpenCaseLinks(content, caseId);

  const runBtn = document.getElementById("run-investigation-btn");
  if (runBtn) runBtn.addEventListener("click", () => runInvestigation(caseId));

  for (const step of content.querySelectorAll(".pipeline-step-link")) {
    step.addEventListener("click", () => scrollToStage(step.dataset.target));
  }

  // Auto-load a cached investigation if one exists.
  const cached = await fetch(`/api/cases/${encodeURIComponent(caseId)}/investigation`);
  if (cached.ok) {
    const data = await cached.json();
    renderInvestigationResult(data, caseId);
    if (runBtn) runBtn.textContent = "Re-run AI investigation";
    // Say plainly that these results were loaded from an earlier run rather
    // than produced just now -- otherwise results that appear the instant the
    // case opens look pre-written rather than generated.
    const note = document.getElementById("cached-note");
    if (note) {
      note.textContent = "Showing a saved run of this investigation. Re-run it to watch the agents work live.";
      note.hidden = false;
    }
  }
}

// Scrolls the drawer to a stage. Deliberately not element.scrollIntoView():
// with behavior:"smooth" it silently does nothing inside this scroll container,
// which left all four stage links dead. Scrolling the container directly works,
// and offsetting by the sticky stepper keeps the stage heading from landing
// underneath it.
function scrollToStage(targetId) {
  const drawer = document.querySelector(".drawer");
  const target = document.getElementById(targetId);
  if (!drawer || !target) return;
  const stepper = drawer.querySelector(".drawer-stepper");
  const top = Math.max(0, target.offsetTop - (stepper ? stepper.offsetHeight : 0) - 8);
  drawer.scrollTo({ top, behavior: "smooth" });
  // Some engines ignore smooth scrolling on a container; land there regardless.
  setTimeout(() => {
    if (Math.abs(drawer.scrollTop - top) > 4) drawer.scrollTop = top;
  }, 400);
}

function bindOpenCaseLinks(root, currentCaseId) {
  for (const el of root.querySelectorAll("[data-open-case]")) {
    if (el.dataset.openCase === currentCaseId) continue;
    el.addEventListener("click", (e) => {
      e.preventDefault();
      openCase(el.dataset.openCase);
    });
  }
}

function renderDrawerStepper() {
  return `
    <div class="drawer-stepper">
      <span class="pipeline-step-link" data-target="stage-discover"><span class="pipeline-num">1</span>Discover</span>
      <span class="pipeline-arrow">&rarr;</span>
      <span class="pipeline-step-link" data-target="stage-investigate"><span class="pipeline-num">2</span>Investigate</span>
      <span class="pipeline-arrow">&rarr;</span>
      <span class="pipeline-step-link" data-target="stage-verify"><span class="pipeline-num">3</span>Verify</span>
      <span class="pipeline-arrow">&rarr;</span>
      <span class="pipeline-step-link" data-target="stage-conclude"><span class="pipeline-num">4</span>Conclude</span>
    </div>`;
}

function renderCaseHeader(c) {
  return `
    <div class="case-header">
      ${riskMeter(c.risk_score, c.risk_level, true)}
      <div>
        <p class="case-title">${c.tender_title || "Untitled tender"}</p>
        <p class="case-sub">${c.buyer_name || "Unknown buyer"} &middot; <span class="mono">${c.case_id}</span></p>
      </div>
    </div>
    <div class="kv-row"><span class="k">Contract value</span><span class="mono">${fmtMoney(c.tender_value_amount, c.tender_value_currency)}</span></div>
    <div class="kv-row"><span class="k">Procurement method</span><span>${c.procurement_method_details || "—"}</span></div>
    <div class="kv-row"><span class="k">Number of tenderers</span><span>${c.number_of_tenderers ?? "—"}</span></div>
  `;
}

function renderRelatedCasesSection(c) {
  const rel = c.related_supplier_cases;
  if (!rel || !rel.other_case_count) return "";
  const links = rel.sample_cases
    .map((s) => `<li><a href="#" data-open-case="${s.case_id}">${s.tender_title || "untitled"}</a>
      <span class="rel-id mono">${s.case_id}</span></li>`)
    .join("");
  const more = rel.other_case_count > rel.sample_cases.length
    ? `<p class="muted">…and ${rel.other_case_count - rel.sample_cases.length} more.</p>` : "";
  return `
    <div class="section related-cases">
      <h4>Part of a larger pattern</h4>
      <p class="muted">This buyer awarded <strong>${rel.other_case_count + 1} contracts</strong> to the same
      supplier ("${rel.supplier_name}") in this dataset. Other contracts in that relationship:</p>
      <ul class="related-list">${links}</ul>
      ${more}
    </div>`;
}

function renderIndicatorSection(c) {
  const rows = c.indicators
    .map((i) => `
      <div class="indicator-row">
        <div>
          <div><strong>${indicatorLabel(i.id)}</strong> <span class="indicator-id mono">${i.id}</span></div>
          <div class="muted">${i.explanation}</div>
        </div>
        <div class="indicator-score">+${i.score}</div>
      </div>`)
    .join("") || '<p class="muted">No deterministic risk indicators triggered for this case.</p>';
  const total = c.indicators.length
    ? `<div class="indicator-total">
         <span>Risk score = the weights above, added up</span>
         <span class="indicator-total-num">${c.risk_score} / 100</span>
       </div>`
    : "";
  return `<div class="section"><h3><span class="stage-num">1</span>Why this case was flagged</h3><p class="muted">Fixed, published rules applied to every contract in the dataset. No AI is involved in this score, and the same inputs always give the same result.</p>${rows}${total}</div>`;
}

function renderInvestigationPlaceholder(c) {
  return `
    <div class="section">
      <h3><span class="stage-num">2</span>What the AI investigated</h3>
      <p class="muted">Three specialist AI investigators — procedure, supplier relationships and price
      benchmarking — examine this case, each able to query the underlying data. Everything below is what
      the AI <em>claims</em>; nothing here is confirmed yet.</p>
      <button id="run-investigation-btn" class="run-btn">Run AI investigation</button>
      <p id="cached-note" class="cached-note" hidden></p>
      <div id="investigation-result"></div>
    </div>
  `;
}

// Resets stages 3 and 4 to their "nothing has run yet" state.
function clearDownstreamStages() {
  for (const [resultId, placeholderId, waiting] of [
    ["verify-result", "verify-placeholder", "Waiting for the investigation to finish…"],
    ["conclude-result", "conclude-placeholder", "The conclusion is written once verification is done…"],
  ]) {
    const result = document.getElementById(resultId);
    if (result) result.innerHTML = `<p class="muted pending">${waiting}</p>`;
    const placeholder = document.getElementById(placeholderId);
    if (placeholder) placeholder.style.display = "none";
  }
}

async function runInvestigation(caseId) {
  const btn = document.getElementById("run-investigation-btn");
  const resultEl = document.getElementById("investigation-result");
  btn.disabled = true;
  btn.textContent = "Investigating… (running agents, then verifying)";
  resultEl.innerHTML = '<p class="muted pending">Three investigators are examining the case…</p>';
  const note = document.getElementById("cached-note");
  if (note) note.hidden = true;
  // Stages 3 and 4 belong to the run that is being replaced. Leaving them on
  // screen during a re-run shows verification results and a conclusion for an
  // investigation that no longer exists -- the worst possible moment to look
  // like the verdict was written in advance.
  clearDownstreamStages();
  try {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/investigate`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      resultEl.innerHTML = `<div class="error-box">${data.detail || "Investigation is unavailable."}</div>`;
      return;
    }
    renderInvestigationResult(data, caseId);
  } catch (err) {
    resultEl.innerHTML = `<div class="error-box">Investigation failed: ${err}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Re-run AI investigation";
  }
}

// A one-sentence, non-technical reading of the verification outcome. The bar
// alone is easy to misread: a mostly-amber meter looks like a failure, when it
// actually means the system refused to certify claims it could not recompute.
// This states the same three numbers as a conclusion an auditor can act on,
// leading with the fact that decides whether the AI can be trusted at all --
// whether anything it said was contradicted.
function verdictSentence(counts, total) {
  const parts = [];
  parts.push(
    counts.rejected
      ? `<strong class="v-bad">${counts.rejected} of ${total} AI claims were contradicted by the source data</strong> and were excluded from the conclusion.`
      : `<strong class="v-good">Nothing the AI claimed was contradicted by the source data.</strong>`
  );
  if (counts.verified) {
    parts.push(`${counts.verified} claim${counts.verified === 1 ? "" : "s"} stated a number the system could
      recompute from the raw records — ${counts.verified === 1 ? "it matched" : "all of them matched"}.`);
  }
  if (counts.downgraded) {
    parts.push(`The other ${counts.downgraded} state no recomputable number, so they are reported as
      <em>not independently checked</em> rather than as confirmed fact.`);
  }
  return parts.join(" ");
}

function renderInvestigationResult(data, caseId) {
  const resultEl = document.getElementById("investigation-result");
  if (!resultEl) return;

  if (data.llm_status && data.llm_status.startsWith("not_configured")) {
    resultEl.innerHTML = `<div class="error-box">AI investigation is not available: no LLM provider is
      configured. Set OPENROUTER_API_KEY to enable it. The deterministic risk result above is unaffected.</div>`;
    return;
  }

  const verifById = {};
  for (const vf of data.verification || []) {
    verifById[vf.finding.claim] = vf;
  }

  // Stage 2: Investigate — raw AI claims, evidence cited, no verdict yet.
  const investigatorHtml = (data.investigator_outputs || [])
    .map((out) => {
      const findings = (out.findings || [])
        .map((f) => `
            <div class="claim-card">
              <div class="claim-label">AI claim</div>
              <div class="finding-claim">${f.claim}</div>
              <div class="finding-meta">risk: ${f.risk_level} &middot; confidence: ${Math.round(f.confidence * 100)}%</div>
              <div class="evidence-row">${renderEvidenceChips(f.evidence_refs, caseId)}</div>
              ${f.benign_explanation ? `<div class="finding-benign">Possible benign explanation: ${f.benign_explanation}</div>` : ""}
            </div>`)
        .join("") || '<p class="muted">No findings produced.</p>';
      return `
        <div class="investigator-card">
          <h4>${out.investigator}</h4>
          <p>${out.summary}</p>
          ${findings}
        </div>`;
    })
    .join("");
  resultEl.innerHTML = investigatorHtml;
  bindOpenCaseLinks(resultEl, caseId);

  // Stage 3: Verify — trust meter + each claim paired with its independently checked verdict.
  const counts = { verified: 0, downgraded: 0, rejected: 0 };
  for (const vf of data.verification || []) counts[vf.verification_status] = (counts[vf.verification_status] || 0) + 1;
  const totalV = (data.verification || []).length;
  const pct = (n) => (totalV ? (100 * n / totalV) : 0);
  const verifyEl = document.getElementById("verify-result");
  const placeholder = document.getElementById("verify-placeholder");
  if (verifyEl) {
    if (placeholder) placeholder.style.display = "none";
    const meter = totalV ? `
      <p class="verify-headline">${verdictSentence(counts, totalV)}</p>
      <div class="trust-meter">
        <div class="trust-meter-track">
          <div class="trust-seg verified" style="width:${pct(counts.verified)}%" title="${counts.verified} recomputed and matched"></div>
          <div class="trust-seg downgraded" style="width:${pct(counts.downgraded)}%" title="${counts.downgraded} not independently checked"></div>
          <div class="trust-seg rejected" style="width:${pct(counts.rejected)}%" title="${counts.rejected} contradicted by source data"></div>
        </div>
        <div class="trust-meter-legend">
          <span class="legend-item"><span class="dot verified"></span>${counts.verified} recomputed &amp; matched</span>
          <span class="legend-item"><span class="dot downgraded"></span>${counts.downgraded} not independently checked</span>
          <span class="legend-item"><span class="dot rejected"></span>${counts.rejected} contradicted by data</span>
        </div>
      </div>
      <p class="verify-standard">A claim counts as verified <em>only</em> when the verifier re-derived
        its number straight from the database and the number matched. Citing a real record is not
        enough — an AI can cite a genuine record and still describe it wrongly.</p>` : "";
    // Lead with the verdicts that carry information — a contradicted claim first of
    // all, then the ones the database actually confirmed — and let the routine
    // "nothing numeric to check here" verdicts settle at the bottom.
    const VERDICT_ORDER = { rejected: 0, verified: 1, downgraded: 2 };
    const ordered = [...(data.verification || [])].sort(
      (a, b) => VERDICT_ORDER[a.verification_status] - VERDICT_ORDER[b.verification_status]
    );
    const pairs = ordered.map((vf) => `
      <div class="verify-pair ${vf.verification_status}">
        <div class="verify-pair-claim"><span class="claim-label">AI claim</span> ${vf.finding.claim}</div>
        <div class="verify-pair-verdict">
          <span class="verify-badge ${vf.verification_status}">${STATUS_ICON[vf.verification_status]} ${STATUS_LABEL[vf.verification_status]}</span>
          <span class="verify-notes">${vf.verification_notes}</span>
        </div>
      </div>`).join("") || '<p class="muted">No claims to verify.</p>';
    verifyEl.innerHTML = meter + pairs;
  }

  // Stage 4: Conclude — final synthesized report.
  const report = data.report || {};
  const concludeEl = document.getElementById("conclude-result");
  const concludePlaceholder = document.getElementById("conclude-placeholder");
  if (concludeEl) {
    if (concludePlaceholder) concludePlaceholder.style.display = "none";
    const standing = totalV
      ? `<p class="conclude-standing">Written from ${totalV} AI claim${totalV === 1 ? "" : "s"}:
           <strong>${counts.verified} independently recomputed</strong>,
           ${counts.downgraded} not independently checked,
           ${counts.rejected} contradicted and excluded. Unverified claims are hedged, never stated as fact.</p>`
      : "";
    concludeEl.innerHTML = standing + `
      <div class="kv-row"><span class="k">Overall risk level</span><span class="badge ${report.overall_risk_level}">${report.overall_risk_level}</span></div>
      <div class="kv-row"><span class="k">AI's own confidence</span><span>${Math.round((report.confidence || 0) * 100)}%</span></div>
      <p class="narrative">${report.narrative || ""}</p>
      <div class="kv-row"><span class="k">Benign explanations</span><span>${report.benign_explanations || "—"}</span></div>
      <div class="kv-row"><span class="k">Conflicting evidence</span><span>${report.conflicting_evidence || "—"}</span></div>
      <div class="kv-row highlight"><span class="k">Recommended follow-up</span><span>${report.recommended_follow_up || "—"}</span></div>
      <div class="kv-row"><span class="k">Source records</span><span class="evidence-row">${renderEvidenceChips(report.source_record_refs, caseId)}</span></div>
    `;
    bindOpenCaseLinks(concludeEl, caseId);
  }
}

loadSummary();
loadHealth();
loadSpotlight();
loadCases();
