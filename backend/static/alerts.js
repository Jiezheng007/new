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
  const STATUS_LABEL = { pending: "待确认", confirmed: "已确认", ignored: "已忽略" };
  const SENTIMENT_LABEL = { positive: "正面", neutral: "中性", negative: "负面" };

  // Mirrors the API role set in app/api/alerts.py so the UI hides
  // confirm/ignore actions for read-only roles.
  const CAN_WRITE = (window.__userRole === "admin" || window.__userRole === "risk_control");

  const riskPill = (level) => {
    const span = document.createElement("span");
    span.className = `risk-pill ${level || "none"}`;
    span.textContent = RISK_LABEL[level] || "—";
    return span;
  };

  const statusPill = (status) => {
    const span = document.createElement("span");
    span.className = `alert-pill ${status || "none"}`;
    span.textContent = STATUS_LABEL[status] || status || "—";
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
    const select = document.getElementById("al_source");
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
    const tbody = document.getElementById("alTbody");
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
      link.textContent = it.opinion.title || "(无标题)";
      link.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
      titleCell.appendChild(link);
      tr.appendChild(titleCell);
      tr.appendChild(td(it.opinion.source_code));
      const levelCell = document.createElement("td");
      levelCell.appendChild(riskPill(it.risk_level));
      tr.appendChild(levelCell);
      tr.appendChild(td(String(it.risk_score)));
      const statusCell = document.createElement("td");
      statusCell.appendChild(statusPill(it.status));
      tr.appendChild(statusCell);
      tr.appendChild(td(formatDate(it.created_at)));
      const actionCell = document.createElement("td");
      if (it.status === "pending") {
        const viewLink = document.createElement("a");
        viewLink.href = "#";
        viewLink.textContent = "查看/处理";
        viewLink.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
        actionCell.appendChild(viewLink);
      } else {
        const viewLink = document.createElement("a");
        viewLink.href = "#";
        viewLink.textContent = "查看";
        viewLink.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
        actionCell.appendChild(viewLink);
      }
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    });
  };

  const renderPager = () => {
    const page = Math.floor(state.offset / state.limit) + 1;
    const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
    document.getElementById("alPager").textContent = `第 ${page} / ${totalPages} 页,共 ${state.total} 条`;
    document.getElementById("alPrev").disabled = state.offset <= 0;
    document.getElementById("alNext").disabled = state.offset + state.limit >= state.total;
  };

  const load = async () => {
    const status = document.getElementById("alStatus");
    setStatus(status, "");
    const res = await csrfSafeFetch(`/api/alerts?${buildQuery()}`);
    if (res.status === 401) { window.location.href = "/login"; return; }
    if (res.status === 403) { alert("当前角色无权访问预警列表"); return; }
    if (!res.ok) { setStatus(status, `加载失败: ${res.status}`, true); return; }
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
      q: document.getElementById("al_q").value.trim(),
      status: document.getElementById("al_status").value,
      risk_level: document.getElementById("al_level").value,
      source_id: document.getElementById("al_source").value,
      start_at: toIsoSeconds(document.getElementById("al_start").value),
      end_at: toIsoSeconds(document.getElementById("al_end").value),
    };
    state.offset = 0;
    load();
  };

  const resetFilter = () => {
    document.getElementById("alertFilter").reset();
    state.filters = {};
    state.offset = 0;
    load();
  };

  const openDetail = (it) => {
    state.currentDetail = it;
    document.getElementById("alertDialogTitle").textContent =
      `[${STATUS_LABEL[it.status] || it.status}] ${it.opinion.title || "(无标题)"}`;
    renderDetailBody(it);
    const footer = document.getElementById("alertDialogFooter");
    if (it.status === "pending" && CAN_WRITE) {
      footer.style.display = "flex";
      document.getElementById("alertConfirmBtn").disabled = false;
      document.getElementById("alertIgnoreBtn").disabled = false;
    } else {
      footer.style.display = "none";
    }
    document.getElementById("alertDialogStatus").textContent = "";
    document.getElementById("alertDialog").classList.remove("hidden");
  };

  const renderDetailBody = (it) => {
    const lines = [
      `数据源: ${it.opinion.source_code} (${it.opinion.source_type})`,
      `作者: ${it.opinion.author || "-"}`,
      `发布时间: ${formatDate(it.opinion.published_at)}`,
      `原文链接: ${it.opinion.url || "-"}`,
      "",
      "正文:",
      it.opinion.content || "(无正文)",
    ];
    let html = `<pre style="margin:0; white-space: pre-wrap; font-family: inherit;">${escapeHtml(lines.join("\n"))}</pre>`;
    html += `<section class="analysis-section">`;
    html += `<h4>预警信息</h4>`;
    html += `<div class="analysis-grid">`;
    const rows = [
      { label: "状态", html: statusPill(it.status).outerHTML },
      { label: "风险等级", html: riskPill(it.risk_level).outerHTML },
      { label: "分数", value: String(it.risk_score) },
      { label: "情感", value: SENTIMENT_LABEL[it.opinion.sentiment] || "—" },
      { label: "触发时间", value: formatDate(it.created_at) },
    ];
    rows.forEach((m) => {
      html += `<div class="metric"><div class="label">${escapeHtml(m.label)}</div><div class="value">${m.html || escapeHtml(String(m.value))}</div></div>`;
    });
    html += `</div>`;
    if (it.status === "confirmed") {
      html += `<p class="muted small">确认人: <strong>${escapeHtml(it.confirmed_by_username || "-")}</strong> · ${formatDate(it.confirmed_at)}</p>`;
    } else if (it.status === "ignored") {
      html += `<p class="muted small">忽略人: <strong>${escapeHtml(it.ignored_by_username || "-")}</strong> · ${formatDate(it.ignored_at)}</p>`;
      html += `<p class="muted small">忽略原因: ${escapeHtml(it.ignore_reason || "-")}</p>`;
    }
    if (Array.isArray(it.trigger_explanation) && it.trigger_explanation.length) {
      html += `<p class="muted small">触发原因 (基于 Phase 4 评分解释):</p><ul>`;
      it.trigger_explanation.forEach((line) => { html += `<li>${escapeHtml(line)}</li>`; });
      html += `</ul>`;
    }
    html += `</section>`;
    document.getElementById("alertDialogBody").innerHTML = html;
  };

  const escapeHtml = (s) => String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const closeDetail = () => {
    document.getElementById("alertDialog").classList.add("hidden");
    state.currentDetail = null;
  };

  const confirmAlert = async () => {
    if (!state.currentDetail) return;
    const id = state.currentDetail.id;
    const status = document.getElementById("alertDialogStatus");
    setStatus(status, "确认中...");
    document.getElementById("alertConfirmBtn").disabled = true;
    const res = await csrfSafeFetch(`/api/alerts/${id}/confirm`, { method: "POST" });
    if (!res.ok) {
      setStatus(status, `确认失败: ${res.status} ${(await res.text()).slice(0, 200)}`, true);
      document.getElementById("alertConfirmBtn").disabled = false;
      return;
    }
    const body = await res.json();
    state.currentDetail.status = body.status;
    state.currentDetail.confirmed_by_username = body.confirmed_by_username;
    state.currentDetail.confirmed_at = body.confirmed_at;
    renderDetailBody(state.currentDetail);
    document.getElementById("alertDialogFooter").style.display = "none";
    setStatus(status, "已确认");
    await load();
  };

  const openIgnoreDialog = () => {
    if (!state.currentDetail) return;
    document.getElementById("ignoreReason").value = "";
    setStatus(document.getElementById("ignoreStatus"), "");
    document.getElementById("ignoreDialog").classList.remove("hidden");
  };

  const closeIgnoreDialog = () => {
    document.getElementById("ignoreDialog").classList.add("hidden");
  };

  const submitIgnore = async () => {
    if (!state.currentDetail) return;
    const reason = document.getElementById("ignoreReason").value.trim();
    const status = document.getElementById("ignoreStatus");
    if (reason.length < 2) {
      setStatus(status, "忽略原因至少 2 个字符", true);
      return;
    }
    setStatus(status, "提交中...");
    const res = await csrfSafeFetch(`/api/alerts/${state.currentDetail.id}/ignore`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    if (!res.ok) {
      setStatus(status, `忽略失败: ${res.status} ${(await res.text()).slice(0, 200)}`, true);
      return;
    }
    const body = await res.json();
    state.currentDetail.status = body.status;
    state.currentDetail.ignored_by_username = body.ignored_by_username;
    state.currentDetail.ignored_at = body.ignored_at;
    state.currentDetail.ignore_reason = body.ignore_reason;
    closeIgnoreDialog();
    renderDetailBody(state.currentDetail);
    document.getElementById("alertDialogFooter").style.display = "none";
    setStatus(document.getElementById("alertDialogStatus"), "已忽略");
    await load();
  };

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("alertFilter").addEventListener("submit", submitFilter);
    document.getElementById("alReset").addEventListener("click", resetFilter);
    document.getElementById("alPrev").addEventListener("click", () => {
      if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); load(); }
    });
    document.getElementById("alNext").addEventListener("click", () => {
      if (state.offset + state.limit < state.total) { state.offset += state.limit; load(); }
    });
    document.getElementById("alertDialogClose").addEventListener("click", closeDetail);
    document.getElementById("alertConfirmBtn").addEventListener("click", confirmAlert);
    document.getElementById("alertIgnoreBtn").addEventListener("click", openIgnoreDialog);
    document.getElementById("alertDialog").addEventListener("click", (e) => {
      if (e.target.id === "alertDialog") closeDetail();
    });
    document.getElementById("ignoreDialogClose").addEventListener("click", closeIgnoreDialog);
    document.getElementById("ignoreCancel").addEventListener("click", closeIgnoreDialog);
    document.getElementById("ignoreSubmit").addEventListener("click", submitIgnore);
    document.getElementById("ignoreDialog").addEventListener("click", (e) => {
      if (e.target.id === "ignoreDialog") closeIgnoreDialog();
    });
    await fillSources();
    await load();
  });
})();
