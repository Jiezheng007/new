(function () {
  "use strict";

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
  const STATUS_LABEL = {
    pending: "待生成",
    generating: "生成中",
    completed: "已生成",
    failed: "生成失败",
  };

  // Mirrors app/api/reports.py: only admin / risk_control can create
  // reports. Auditors and viewers can read but not create.
  const ROLE = window.__userRole;
  const CAN_CREATE = (ROLE === "admin" || ROLE === "risk_control");

  const escapeHtml = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const state = {
    filters: {},
    offset: 0,
    limit: 50,
    total: 0,
    currentDetail: null,
    pollTimer: null,
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

  const toIsoSeconds = (value) => {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return d.toISOString();
  };

  const statusPill = (status) => {
    const span = document.createElement("span");
    span.className = `alert-pill ${status || "none"}`;
    span.textContent = STATUS_LABEL[status] || status || "—";
    return span;
  };

  const filterSummary = (it) => {
    const parts = [];
    if (it.start_at || it.end_at) {
      parts.push(`${formatDate(it.start_at).slice(0, 16) || "*"} ~ ${formatDate(it.end_at).slice(0, 16) || "*"}`);
    }
    if (it.risk_level) parts.push(`风险 ${RISK_LABEL[it.risk_level] || it.risk_level}`);
    if (it.subject_keyword) parts.push(`关键词 "${it.subject_keyword}"`);
    return parts.length ? parts.join(" · ") : "全部";
  };

  const renderRows = (items) => {
    const tbody = document.getElementById("repTbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="muted">暂无数据</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    items.forEach((it) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(it.id));
      const titleCell = document.createElement("td");
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = it.title || `报告 #${it.id}`;
      link.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
      titleCell.appendChild(link);
      tr.appendChild(titleCell);
      tr.appendChild(td(filterSummary(it)));
      const statusCell = document.createElement("td");
      statusCell.appendChild(statusPill(it.status));
      tr.appendChild(statusCell);
      tr.appendChild(td(String(it.matched_count || 0)));
      tr.appendChild(td(it.created_by_username || "-"));
      tr.appendChild(td(formatDate(it.created_at)));
      tr.appendChild(td(formatDate(it.completed_at)));
      const actionCell = document.createElement("td");
      if (it.status === "completed") {
        const dl = document.createElement("a");
        dl.href = `/api/reports/${it.id}/download`;
        dl.textContent = "下载";
        dl.setAttribute("download", "");
        actionCell.appendChild(dl);
        const sep = document.createTextNode(" · ");
        actionCell.appendChild(sep);
      }
      const view = document.createElement("a");
      view.href = "#";
      view.textContent = "查看";
      view.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
      actionCell.appendChild(view);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    });
  };

  const renderPager = () => {
    const page = Math.floor(state.offset / state.limit) + 1;
    const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
    document.getElementById("repPager").textContent = `第 ${page} / ${totalPages} 页,共 ${state.total} 条`;
    document.getElementById("repPrev").disabled = state.offset <= 0;
    document.getElementById("repNext").disabled = state.offset + state.limit >= state.total;
  };

  const renderSummary = (s) => {
    const text = `待生成 ${s.pending} · 生成中 ${s.generating} · 已生成 ${s.completed} · 失败 ${s.failed} · 共 ${s.total}`;
    document.getElementById("repSummary").textContent = text;
  };

  const load = async () => {
    const [listRes, summaryRes] = await Promise.all([
      csrfSafeFetch(`/api/reports?${buildQuery()}`),
      csrfSafeFetch("/api/reports/summary"),
    ]);
    if (listRes.status === 401) { window.location.href = "/login"; return; }
    if (listRes.status === 403) { document.getElementById("repTbody").innerHTML = `<tr><td colspan="9" class="muted">当前角色无权访问报告中心</td></tr>`; return; }
    if (!listRes.ok) { document.getElementById("repTbody").innerHTML = `<tr><td colspan="9" class="muted">加载失败: ${listRes.status}</td></tr>`; return; }
    const body = await listRes.json();
    state.total = body.total;
    renderRows(body.items);
    renderPager();
    if (summaryRes.ok) {
      const s = await summaryRes.json();
      renderSummary(s);
    }
    maybeStartPolling();
  };

  const submitFilter = (event) => {
    event.preventDefault();
    state.filters = {
      status: document.getElementById("rep_f_status").value,
    };
    state.offset = 0;
    load();
  };

  const resetFilter = () => {
    document.getElementById("reportFilter").reset();
    state.filters = {};
    state.offset = 0;
    load();
  };

  const openDetail = (it) => {
    state.currentDetail = it;
    document.getElementById("reportDialogTitle").textContent =
      `[${STATUS_LABEL[it.status] || it.status}] ${it.title || `报告 #${it.id}`}`;
    renderDetailBody(it);
    renderDetailFooter(it);
    document.getElementById("reportDialog").classList.remove("hidden");
  };

  const renderDetailBody = (it) => {
    const lines = [
      `创建人: ${it.created_by_username || "-"}`,
      `创建时间: ${formatDate(it.created_at)}`,
      `开始处理: ${formatDate(it.started_at)}`,
      `完成时间: ${formatDate(it.completed_at)}`,
      `筛选: ${filterSummary(it)}`,
      `匹配条数: ${it.matched_count || 0}`,
      `文件大小: ${formatBytes(it.file_size_bytes || 0)}`,
    ];
    if (it.status === "failed" && it.error_message) {
      lines.push("", "失败原因:", it.error_message);
    }
    if (it.description) {
      lines.unshift(`备注: ${it.description}`);
    }
    const html = `<pre style="margin: 0; white-space: pre-wrap; font-family: inherit; line-height: 1.7;">${escapeHtml(lines.join("\n"))}</pre>`;
    document.getElementById("reportDialogBody").innerHTML = html;
  };

  const renderDetailFooter = (it) => {
    const link = document.getElementById("reportDownloadLink");
    if (it.status === "completed") {
      link.href = `/api/reports/${it.id}/download`;
      link.style.display = "";
      link.textContent = "下载 Excel";
      document.getElementById("reportDialogFooter").style.display = "flex";
    } else {
      link.style.display = "none";
      document.getElementById("reportDialogFooter").style.display = "none";
    }
  };

  const closeDetail = () => {
    document.getElementById("reportDialog").classList.add("hidden");
    state.currentDetail = null;
  };

  const formatBytes = (n) => {
    if (!n) return "0 B";
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(2)} MB`;
  };

  // Auto-refresh while any task in view is still pending/generating.
  // We poll every 5 seconds (the report is small - the demo finishes
  // in under a second, so the cadence is for the case where a user
  // walks away with a long task in flight).
  const maybeStartPolling = () => {
    const hasOpen = state.total > 0 && (
      state.filters.status === "pending" ||
      state.filters.status === "generating" ||
      !state.filters.status
    );
    if (hasOpen) {
      if (!state.pollTimer) {
        state.pollTimer = setInterval(load, 5000);
      }
    } else if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  };

  const submitCreate = async (event) => {
    event.preventDefault();
    const status = document.getElementById("repStatus");
    if (!CAN_CREATE) {
      setStatus(status, "当前角色无权生成报告", true);
      return;
    }
    const body = {
      title: document.getElementById("rep_title").value.trim(),
      description: document.getElementById("rep_description").value.trim(),
      start_at: toIsoSeconds(document.getElementById("rep_start").value) || null,
      end_at: toIsoSeconds(document.getElementById("rep_end").value) || null,
      risk_level: document.getElementById("rep_level").value,
      subject_keyword: document.getElementById("rep_keyword").value.trim(),
    };
    setStatus(status, "提交中...");
    const res = await csrfSafeFetch("/api/reports", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (res.status === 201) {
      const data = await res.json();
      setStatus(status, `已创建任务 #${data.id} (${STATUS_LABEL[data.status] || data.status})`, false);
      document.getElementById("reportCreate").reset();
      state.offset = 0;
      await load();
      return;
    }
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch (_) { detail = (await res.text()).slice(0, 200); }
    setStatus(status, `创建失败: ${res.status} ${detail}`, true);
  };

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("reportCreate").addEventListener("submit", submitCreate);
    document.getElementById("reportFilter").addEventListener("submit", submitFilter);
    document.getElementById("repReset").addEventListener("click", resetFilter);
    document.getElementById("repPrev").addEventListener("click", () => {
      if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); load(); }
    });
    document.getElementById("repNext").addEventListener("click", () => {
      if (state.offset + state.limit < state.total) { state.offset += state.limit; load(); }
    });
    document.getElementById("repRefresh").addEventListener("click", load);
    document.getElementById("reportDialogClose").addEventListener("click", closeDetail);
    document.getElementById("reportDialog").addEventListener("click", (e) => {
      if (e.target.id === "reportDialog") closeDetail();
    });
    if (!CAN_CREATE) {
      const submit = document.getElementById("repSubmit");
      if (submit) submit.disabled = true;
    }
    await load();
  });
})();
