const state = { limit: 25, offset: 0, total: 0, search: "", riskLevel: "" };

const fmtMoney = (amount, currency) => {
  if (amount === null || amount === undefined) return "—";
  return `${Math.round(amount).toLocaleString()} ${currency || ""}`.trim();
};

async function loadSummary() {
  const res = await fetch("/api/summary");
  const data = await res.json();
  document.getElementById("stat-total").textContent = data.total_procurements_analyzed.toLocaleString();
  document.getElementById("stat-risky").textContent = data.risky_procurements_detected.toLocaleString();
  document.getElementById("stat-high").textContent = data.high_risk_cases.toLocaleString();
  document.getElementById("stat-medium").textContent = data.medium_risk_cases.toLocaleString();
  document.getElementById("stat-buyers").textContent = data.distinct_buyers.toLocaleString();
  document.getElementById("stat-suppliers").textContent = data.distinct_suppliers.toLocaleString();
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

async function loadCases() {
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.search) params.set("search", state.search);
  if (state.riskLevel) params.set("risk_level", state.riskLevel);
  const res = await fetch(`/api/cases?${params}`);
  const data = await res.json();
  state.total = data.total;
  renderRows(data.cases);
  renderPager();
}

function renderRows(cases) {
  const tbody = document.getElementById("case-rows");
  tbody.innerHTML = "";
  for (const c of cases) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="badge ${c.risk_level}">${c.risk_score}</span></td>
      <td>${c.buyer || "—"}</td>
      <td>${c.tender_title || "—"}</td>
      <td>${fmtMoney(c.contract_value, c.currency)}</td>
      <td>${c.procurement_method || "—"}</td>
      <td>${c.main_indicators.map((i) => `<span class="indicator-chip">${i}</span>`).join("")}</td>
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
document.getElementById("close-drawer").addEventListener("click", () => {
  document.getElementById("overlay").classList.add("hidden");
});

const STATUS_ICON = { verified: "✓", downgraded: "⚠", rejected: "✗" };

async function openCase(caseId) {
  const overlay = document.getElementById("overlay");
  const content = document.getElementById("drawer-content");
  overlay.classList.remove("hidden");
  content.innerHTML = `<p class="muted">Loading case ${caseId}…</p>`;

  const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}`);
  const c = await res.json();

  content.innerHTML = renderCaseHeader(c) + renderIndicatorSection(c) + renderInvestigationPlaceholder(c);

  const runBtn = document.getElementById("run-investigation-btn");
  if (runBtn) runBtn.addEventListener("click", () => runInvestigation(caseId));

  // Auto-load a cached investigation if one exists.
  const cached = await fetch(`/api/cases/${encodeURIComponent(caseId)}/investigation`);
  if (cached.ok) {
    const data = await cached.json();
    renderInvestigationResult(data);
  }
}

function renderCaseHeader(c) {
  return `
    <div class="case-header">
      <div class="score-badge ${c.risk_level}">${c.risk_score}</div>
      <div>
        <p class="case-title">${c.tender_title || "Untitled tender"}</p>
        <p class="case-sub">${c.buyer_name || "Unknown buyer"} &middot; ${c.case_id}</p>
      </div>
    </div>
    <div class="kv-row"><span class="k">Contract value</span><span>${fmtMoney(c.tender_value_amount, c.tender_value_currency)}</span></div>
    <div class="kv-row"><span class="k">Procurement method</span><span>${c.procurement_method_details || "—"}</span></div>
    <div class="kv-row"><span class="k">Number of tenderers</span><span>${c.number_of_tenderers ?? "—"}</span></div>
  `;
}

function renderIndicatorSection(c) {
  const rows = c.indicators
    .map((i) => `
      <div class="indicator-row">
        <div>
          <div><strong>${i.id}</strong></div>
          <div class="muted">${i.explanation}</div>
        </div>
        <div class="indicator-score">+${i.score}</div>
      </div>`)
    .join("") || '<p class="muted">No deterministic risk indicators triggered for this case.</p>';
  return `<div class="section"><h3>Why this case was flagged</h3>${rows}</div>`;
}

function renderInvestigationPlaceholder(c) {
  return `
    <div class="section" id="investigation-section">
      <h3>AI investigation</h3>
      <p class="muted">Three specialist AI investigators (procedure, supplier relationships, price
      benchmarking) analyze this case using bounded, deterministic tools over the underlying data.
      Every claim is independently re-verified against the database before it's shown here.</p>
      <button id="run-investigation-btn" class="run-btn">Run AI investigation</button>
      <div id="investigation-result"></div>
    </div>
  `;
}

async function runInvestigation(caseId) {
  const btn = document.getElementById("run-investigation-btn");
  const resultEl = document.getElementById("investigation-result");
  btn.disabled = true;
  btn.textContent = "Investigating… (parallel LLM calls + verification)";
  resultEl.innerHTML = "";
  try {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/investigate`, { method: "POST" });
    const data = await res.json();
    renderInvestigationResult(data);
  } catch (err) {
    resultEl.innerHTML = `<div class="error-box">Investigation failed: ${err}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Re-run AI investigation";
  }
}

function renderInvestigationResult(data) {
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

  const counts = { verified: 0, downgraded: 0, rejected: 0 };
  for (const vf of data.verification || []) counts[vf.verification_status] = (counts[vf.verification_status] || 0) + 1;
  const verificationSummaryHtml = (data.verification || []).length
    ? `<p class="verification-summary">
        <span class="verify-icon">✓</span>${counts.verified} verified
        &nbsp;&middot;&nbsp; <span class="verify-icon">⚠</span>${counts.downgraded} downgraded
        &nbsp;&middot;&nbsp; <span class="verify-icon">✗</span>${counts.rejected} rejected by verification
      </p>`
    : "";

  const investigatorHtml = (data.investigator_outputs || [])
    .map((out) => {
      const findings = (out.findings || [])
        .map((f) => {
          const vf = verifById[f.claim];
          const status = vf ? vf.verification_status : "unverified";
          const icon = STATUS_ICON[status] || "?";
          return `
            <div class="finding ${status}">
              <div class="finding-claim">${icon} ${f.claim}</div>
              <div class="finding-meta">risk: ${f.risk_level} &middot; confidence: ${f.confidence} &middot;
                evidence: ${(f.evidence_refs || []).join(", ") || "none"}</div>
              ${vf ? `<div class="finding-meta">Verification: ${vf.verification_notes}</div>` : ""}
              ${f.benign_explanation ? `<div class="finding-benign">Benign explanation: ${f.benign_explanation}</div>` : ""}
            </div>`;
        })
        .join("") || '<p class="muted">No findings produced.</p>';
      return `
        <div class="investigator-card">
          <h4>${out.investigator}</h4>
          <p>${out.summary}</p>
          ${findings}
        </div>`;
    })
    .join("");

  const report = data.report || {};
  const reportHtml = `
    <div class="section">
      <h3>Final investigation report</h3>
      <div class="kv-row"><span class="k">Overall risk level</span><span class="badge ${report.overall_risk_level}">${report.overall_risk_level}</span></div>
      <div class="kv-row"><span class="k">Confidence</span><span>${report.confidence}</span></div>
      <p class="narrative">${report.narrative || ""}</p>
      <div class="kv-row"><span class="k">Benign explanations</span><span>${report.benign_explanations || "—"}</span></div>
      <div class="kv-row"><span class="k">Conflicting evidence</span><span>${report.conflicting_evidence || "—"}</span></div>
      <div class="kv-row"><span class="k">Recommended follow-up</span><span>${report.recommended_follow_up || "—"}</span></div>
      <div class="kv-row"><span class="k">Source records</span><span>${(report.source_record_refs || []).join(", ") || "—"}</span></div>
    </div>
  `;

  resultEl.innerHTML = `<div class="section">${verificationSummaryHtml}${investigatorHtml}</div>${reportHtml}`;
}

loadSummary();
loadHealth();
loadCases();
