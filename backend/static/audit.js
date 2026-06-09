(function () {
  "use strict";

  const csrfSafeFetch = (url, options = {}) => {
    const opts = Object.assign({ credentials: "same-origin" }, options);
    if (opts.headers === undefined) {
      opts.headers = { "Content-Type": "application/json" };
    }
    return fetch(url, opts);
  };

  const formatDate = (iso) => {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };

  const escapeHtml = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const td = (text) => {
    const el = document.createElement("td");
    el.textContent = text == null ? "" : String(text);
    return el;
  };

  // Friendly Chinese labels for the most common actions, mirroring the
  // record_audit callsites across the backend. Unknown actions fall back
  // to the raw code so a new action shows up immediately without a UI
  // patch.
  const ACTION_LABEL = {
    "auth.login": "登录",
    "auth.logout": "登出",
    "user.create": "新建用户",
    "user.update": "修改用户",
    "user.reset_password": "重置密码",
    "datasource.create": "新建数据源",
    "datasource.update": "更新数据源",
    "datasource.fetch": "抓取数据源",
    "rule.sensitive.create": "新建敏感词",
    "rule.sensitive.update": "更新敏感词",
    "rule.subject.create": "新建主体词",
    "rule.subject.update": "更新主体词",
    "rule.threshold.update": "更新风险阈值",
    "import.csv": "CSV 导入",
    "import.json": "JSON 导入",
    "import.demo": "演示数据导入",
    "opinion.analyze": "舆情分析",
    "opinion.analyze_pending": "批量分析",
    "alert.confirm": "确认预警",
    "alert.ignore": "忽略预警",
    "ticket.create": "创建工单",
    "ticket.assign": "指派工单",
    "ticket.start": "开始处理",
    "ticket.complete": "完成工单",
    "ticket.archive": "归档工单",
    "report.create": "生成报告",
    "report.download": "下载报告",
  };

  const RESULT_LABEL = { success: "成功", failure: "失败" };

  const resultPill = (result) => {
    const span = document.createElement("span");
    const cls = result === "success" ? "on" : (result === "failure" ? "off" : "");
    span.className = `status-pill ${cls}`;
    span.textContent = RESULT_LABEL[result] || result || "—";
    return span;
  };

  const actionDisplay = (action) => {
    const label = ACTION_LABEL[action];
    return label ? `${label} (${action})` : action;
  };

  const state = {
    filters: {},
    offset: 0,
    limit: 50,
    total: 0,
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

  const toIso = (value) => {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return d.toISOString();
  };

  // Truncate a long detail blob for the table cell - the row stays
  // single-line; the dialog shows the full payload.
  const detailPreview = (s) => {
    if (!s) return "—";
    if (s.length <= 60) return s;
    return s.slice(0, 60) + "…";
  };

  const targetDisplay = (it) => {
    if (!it.target_type && !it.target_id) return "—";
    if (!it.target_type) return it.target_id;
    if (!it.target_id) return it.target_type;
    return `${it.target_type} #${it.target_id}`;
  };

  const renderRows = (items) => {
    const tbody = document.getElementById("audTbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">暂无数据</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    items.forEach((it) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(it.id));
      tr.appendChild(td(formatDate(it.created_at)));
      tr.appendChild(td(it.actor_username || "-"));
      tr.appendChild(td(actionDisplay(it.action)));
      tr.appendChild(td(targetDisplay(it)));
      const resCell = document.createElement("td");
      resCell.appendChild(resultPill(it.result));
      tr.appendChild(resCell);
      tr.appendChild(td(it.ip_address || "-"));
      const detailCell = document.createElement("td");
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = detailPreview(it.detail || "");
      link.style.textDecoration = "underline";
      link.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
      detailCell.appendChild(link);
      tr.appendChild(detailCell);
      tbody.appendChild(tr);
    });
  };

  const renderPager = () => {
    const page = Math.floor(state.offset / state.limit) + 1;
    const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
    document.getElementById("audPager").textContent = `第 ${page} / ${totalPages} 页,共 ${state.total} 条`;
    document.getElementById("audPrev").disabled = state.offset <= 0;
    document.getElementById("audNext").disabled = state.offset + state.limit >= state.total;
  };

  const renderSummary = () => {
    document.getElementById("auditSummary").textContent = `共 ${state.total} 条记录`;
  };

  const openDetail = (it) => {
    document.getElementById("auditDialogTitle").textContent =
      `[${RESULT_LABEL[it.result] || it.result}] ${actionDisplay(it.action)} #${it.id}`;
    const lines = [
      `时间: ${formatDate(it.created_at)}`,
      `操作人: ${it.actor_username || "-"}` + (it.actor_id ? ` (id=${it.actor_id})` : ""),
      `操作: ${actionDisplay(it.action)}`,
      `目标: ${targetDisplay(it)}`,
      `结果: ${RESULT_LABEL[it.result] || it.result || "-"}`,
      `IP: ${it.ip_address || "-"}`,
      "",
      "详情:",
      formatDetailBlob(it.detail),
    ];
    document.getElementById("auditDialogBody").innerHTML =
      `<pre style="margin: 0; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; line-height: 1.6;">${escapeHtml(lines.join("\n"))}</pre>`;
    document.getElementById("auditDialog").classList.remove("hidden");
  };

  // Audit detail is usually JSON; pretty-print it for readability while
  // falling back to the raw string for plain-text rows.
  const formatDetailBlob = (raw) => {
    if (!raw) return "(无)";
    try {
      const obj = JSON.parse(raw);
      return JSON.stringify(obj, null, 2);
    } catch (_) {
      return raw;
    }
  };

  const closeDetail = () => {
    document.getElementById("auditDialog").classList.add("hidden");
  };

  const populateFacets = async () => {
    const res = await csrfSafeFetch("/api/audit-logs/facets");
    if (!res.ok) return;
    const data = await res.json();
    fillSelect("aud_f_action", data.actions || [], ACTION_LABEL);
    fillSelect("aud_f_target_type", data.target_types || [], {});
  };

  const fillSelect = (selectId, values, labelMap) => {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    // Keep the existing "全部" option.
    const current = sel.value;
    while (sel.options.length > 1) sel.remove(1);
    values.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = labelMap && labelMap[v] ? `${labelMap[v]} (${v})` : v;
      sel.appendChild(opt);
    });
    if (current && values.includes(current)) sel.value = current;
  };

  const load = async () => {
    const res = await csrfSafeFetch(`/api/audit-logs?${buildQuery()}`);
    if (res.status === 401) { window.location.href = "/login"; return; }
    if (res.status === 403) {
      document.getElementById("audTbody").innerHTML = `<tr><td colspan="8" class="muted">当前角色无权访问审计日志</td></tr>`;
      return;
    }
    if (!res.ok) {
      document.getElementById("audTbody").innerHTML = `<tr><td colspan="8" class="muted">加载失败: ${res.status}</td></tr>`;
      return;
    }
    const body = await res.json();
    state.total = body.total;
    renderRows(body.items);
    renderPager();
    renderSummary();
  };

  const submitFilter = (event) => {
    event.preventDefault();
    state.filters = {
      action: document.getElementById("aud_f_action").value,
      target_type: document.getElementById("aud_f_target_type").value,
      target_id: document.getElementById("aud_f_target_id").value.trim(),
      actor: document.getElementById("aud_f_actor").value.trim(),
      result: document.getElementById("aud_f_result").value,
      start_at: toIso(document.getElementById("aud_f_start").value),
      end_at: toIso(document.getElementById("aud_f_end").value),
      q: document.getElementById("aud_f_q").value.trim(),
    };
    state.offset = 0;
    load();
  };

  const resetFilter = () => {
    document.getElementById("auditFilter").reset();
    state.filters = {};
    state.offset = 0;
    load();
  };

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("auditFilter").addEventListener("submit", submitFilter);
    document.getElementById("audReset").addEventListener("click", resetFilter);
    document.getElementById("audPrev").addEventListener("click", () => {
      if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); load(); }
    });
    document.getElementById("audNext").addEventListener("click", () => {
      if (state.offset + state.limit < state.total) { state.offset += state.limit; load(); }
    });
    document.getElementById("audRefresh").addEventListener("click", load);
    document.getElementById("auditDialogClose").addEventListener("click", closeDetail);
    document.getElementById("auditDialog").addEventListener("click", (e) => {
      if (e.target.id === "auditDialog") closeDetail();
    });
    await populateFacets();
    await load();
  });
})();
