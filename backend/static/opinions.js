(function () {
  const csrfSafeFetch = (url, options = {}) => {
    const opts = Object.assign({ credentials: "same-origin" }, options);
    if (opts.headers === undefined) {
      opts.headers = { "Content-Type": "application/json" };
    } else if (!opts.headers["Content-Type"] && opts.body) {
      opts.headers["Content-Type"] = "application/json";
    }
    return fetch(url, opts);
  };

  const setStatus = (el, message, isError = false) => {
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.toggle("ok", !isError && !!message);
  };

  const formatDate = (iso) => {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const td = (text) => {
    const el = document.createElement("td");
    el.textContent = text == null ? "" : String(text);
    return el;
  };

  const RISK_LABEL = { low: "低", medium: "中", high: "高", severe: "严重" };
  const SENTIMENT_LABEL = { positive: "正面", neutral: "中性", negative: "负面" };
  const STATUS_LABEL = { success: "已完成", pending: "未分析", failed: "失败" };

  const riskPill = (level) => {
    const span = document.createElement("span");
    span.className = `risk-pill ${level || "none"}`;
    span.textContent = RISK_LABEL[level] || "未分析";
    return span;
  };

  const sentimentPill = (sentiment) => {
    const span = document.createElement("span");
    span.className = `sentiment-pill ${sentiment || "none"}`;
    span.textContent = SENTIMENT_LABEL[sentiment] || "—";
    return span;
  };

  const state = {
    sources: [],
    filters: {},
    offset: 0,
    limit: 50,
    total: 0,
    currentDetail: null,
  };

  const fillSources = async () => {
    const res = await csrfSafeFetch("/api/datasources");
    if (!res.ok) return;
    const items = await res.json();
    const select = document.getElementById("op_source");
    state.sources = items;
    items.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `${s.name} (${s.code})`;
      select.appendChild(opt);
    });
  };

  const buildQuery = () => {
    const params = new URLSearchParams();
    Object.entries(state.filters).forEach(([k, v]) => {
      if (v !== "" && v !== null && v !== undefined) params.append(k, v);
    });
    params.append("limit", String(state.limit));
    params.append("offset", String(state.offset));
    return params.toString();
  };

  const renderRows = (items) => {
    const tbody = document.getElementById("opTbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">暂无数据</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    items.forEach((it) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(it.id));
      const titleCell = document.createElement("td");
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = it.title || "(无标题)";
      link.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
      titleCell.appendChild(link);
      tr.appendChild(titleCell);
      tr.appendChild(td(it.source_code));
      const sentCell = document.createElement("td");
      sentCell.appendChild(sentimentPill(it.analysis && it.analysis.sentiment));
      tr.appendChild(sentCell);
      const riskCell = document.createElement("td");
      riskCell.appendChild(riskPill(it.analysis && it.analysis.level));
      tr.appendChild(riskCell);
      const score = it.analysis && it.analysis.score;
      tr.appendChild(td(score == null ? "—" : String(score)));
      const statusCell = document.createElement("td");
      const status = (it.analysis && it.analysis.status) || "pending";
      statusCell.textContent = STATUS_LABEL[status] || status;
      tr.appendChild(statusCell);
      tr.appendChild(td(formatDate(it.published_at)));
      tbody.appendChild(tr);
    });
  };

  const renderPager = () => {
    const page = Math.floor(state.offset / state.limit) + 1;
    const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
    document.getElementById("opPager").textContent = `第 ${page} / ${totalPages} 页,共 ${state.total} 条`;
    document.getElementById("opPrev").disabled = state.offset <= 0;
    document.getElementById("opNext").disabled = state.offset + state.limit >= state.total;
  };

  const load = async () => {
    const status = document.getElementById("opStatus");
    setStatus(status, "");
    const res = await csrfSafeFetch(`/api/opinions?${buildQuery()}`);
    if (res.status === 401) { window.location.href = "/login"; return; }
    if (res.status === 403) { alert("当前角色无权访问舆情列表"); return; }
    const body = await res.json();
    state.total = body.total;
    renderRows(body.items);
    renderPager();
    setStatus(status, `已加载 ${body.items.length} 条`);
  };

  const toIsoSeconds = (value) => {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return d.toISOString();
  };

  const submitFilter = (event) => {
    event.preventDefault();
    state.filters = {
      q: document.getElementById("op_q").value.trim(),
      source_id: document.getElementById("op_source").value,
      start_at: toIsoSeconds(document.getElementById("op_start").value),
      end_at: toIsoSeconds(document.getElementById("op_end").value),
      sentiment: document.getElementById("op_sentiment").value,
      risk_level: document.getElementById("op_risk_level").value,
      analysis_status: document.getElementById("op_status").value,
    };
    state.offset = 0;
    load();
  };

  const resetFilter = () => {
    document.getElementById("opinionFilter").reset();
    state.filters = {};
    state.offset = 0;
    load();
  };

  const openDetail = (it) => {
    state.currentDetail = it;
    document.getElementById("opinionDialogTitle").textContent = it.title || "(无标题)";
    renderDetailBody(it);
    document.getElementById("opinionDialog").classList.remove("hidden");
  };

  const renderDetailBody = (it) => {
    const a = it.analysis || {};
    const analysis = a.status === "pending" || !a.status
      ? "未分析 (点击下方按钮触发分析)"
      : a.status === "failed"
        ? `分析失败: ${a.error_message || "未知错误"}`
        : null;
    const lines = [
      `来源: ${it.source_code} (${it.source_type})`,
      `作者: ${it.author || "-"}`,
      `发布时间: ${formatDate(it.published_at)}`,
      `抓取时间: ${formatDate(it.fetched_at)}`,
      `原文链接: ${it.url || "-"}`,
      `来源标记: ${it.origin}`,
      `内容指纹: ${it.content_hash}`,
      "",
      "正文:",
      it.content || "(无正文)",
    ];
    let html = `<pre style="margin:0; white-space: pre-wrap; font-family: inherit;">${escapeHtml(lines.join("\n"))}</pre>`;
    html += `<section class="analysis-section">`;
    html += `<h4>分析结果</h4>`;
    if (analysis) {
      html += `<p class="muted small">${escapeHtml(analysis)}</p>`;
    } else {
      const items = [
        { label: "情感", value: SENTIMENT_LABEL[a.sentiment] || "—", pill: sentimentPill(a.sentiment).outerHTML },
        { label: "风险等级", value: RISK_LABEL[a.level] || "—", pill: riskPill(a.level).outerHTML },
        { label: "分数", value: a.score == null ? "—" : String(a.score) },
        { label: "置信度", value: a.confidence == null ? "—" : Number(a.confidence).toFixed(2) },
        { label: "提供方", value: a.provider || "—" },
        { label: "分析时间", value: formatDate(a.analyzed_at) },
      ];
      html += `<div class="analysis-grid">`;
      items.forEach((m) => {
        html += `<div class="metric"><div class="label">${escapeHtml(m.label)}</div><div class="value">${m.pill || escapeHtml(String(m.value))}</div></div>`;
      });
      html += `</div>`;
      const factors = a.factors || {};
      const breakdown = factors.sensitive_keywords && factors.sensitive_keywords.hits ? factors.sensitive_keywords.hits : [];
      const subjects = factors.subject_keywords && factors.subject_keywords.hits ? factors.subject_keywords.hits : [];
      if (breakdown.length) {
        html += `<p class="muted small">命中敏感词:</p><ul>`;
        breakdown.forEach((h) => {
          html += `<li>${escapeHtml(h.keyword)} <span class="muted">[${escapeHtml(h.severity)},+${h.contribution}]</span></li>`;
        });
        html += `</ul>`;
      }
      if (subjects.length) {
        html += `<p class="muted small">命中主体词:</p><ul>`;
        subjects.forEach((h) => {
          html += `<li>${escapeHtml(h.keyword)} <span class="muted">(+${h.contribution})</span></li>`;
        });
        html += `</ul>`;
      }
      if (Array.isArray(a.explanation) && a.explanation.length) {
        html += `<p class="muted small">评分解释:</p><ul>`;
        a.explanation.forEach((line) => { html += `<li>${escapeHtml(line)}</li>`; });
        html += `</ul>`;
      }
    }
    html += `</section>`;
    document.getElementById("opinionDialogBody").innerHTML = html;
    document.getElementById("opinionReanalyzeStatus").textContent = "";
  };

  const escapeHtml = (s) => String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const closeDetail = () => {
    document.getElementById("opinionDialog").classList.add("hidden");
    state.currentDetail = null;
  };

  const reanalyze = async () => {
    if (!state.currentDetail) return;
    const status = document.getElementById("opinionReanalyzeStatus");
    setStatus(status, "分析中...");
    const res = await csrfSafeFetch(`/api/opinions/${state.currentDetail.id}/analyze`, { method: "POST" });
    if (!res.ok) {
      setStatus(status, `分析失败: ${res.status} ${(await res.text()).slice(0, 200)}`, true);
      return;
    }
    const body = await res.json();
    state.currentDetail.analysis = {
      status: body.status,
      sentiment: body.sentiment,
      confidence: null,
      provider: state.currentDetail.analysis && state.currentDetail.analysis.provider,
      score: body.risk_score,
      level: body.risk_level,
      error_message: body.error_message,
      factors: state.currentDetail.analysis && state.currentDetail.analysis.factors,
      explanation: state.currentDetail.analysis && state.currentDetail.analysis.explanation,
      analyzed_at: body.analyzed_at,
    };
    renderDetailBody(state.currentDetail);
    setStatus(status, body.status === "success" ? "分析完成" : "分析失败 (见上方错误)", body.status !== "success");
    await load();
  };

  const analyzePending = async () => {
    const status = document.getElementById("opStatus");
    setStatus(status, "正在分析未完成项...");
    const res = await csrfSafeFetch("/api/opinions/analyze-pending?limit=200", { method: "POST" });
    if (res.status === 403) { setStatus(status, "当前角色无权触发分析", true); return; }
    if (!res.ok) { setStatus(status, `分析失败: ${res.status}`, true); return; }
    const body = await res.json();
    setStatus(status, `已分析 ${body.succeeded} 条, 失败 ${body.failed} 条`);
    await load();
  };

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("opinionFilter").addEventListener("submit", submitFilter);
    document.getElementById("opReset").addEventListener("click", resetFilter);
    document.getElementById("opAnalyzePending").addEventListener("click", analyzePending);
    document.getElementById("opPrev").addEventListener("click", () => {
      if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); load(); }
    });
    document.getElementById("opNext").addEventListener("click", () => {
      if (state.offset + state.limit < state.total) { state.offset += state.limit; load(); }
    });
    document.getElementById("opinionDialogClose").addEventListener("click", closeDetail);
    document.getElementById("opinionReanalyze").addEventListener("click", reanalyze);
    document.getElementById("opinionDialog").addEventListener("click", (e) => {
      if (e.target.id === "opinionDialog") closeDetail();
    });
    await fillSources();
    await load();
  });
})();
