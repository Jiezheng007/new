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
  const STATUS_LABEL = {
    unassigned: "待分配",
    in_progress: "进行中",
    completed: "已完成",
    archived: "已归档",
  };
  const SENTIMENT_LABEL = { positive: "正面", neutral: "中性", negative: "负面" };

  // Role-driven UI capabilities. Mirrors the role permissions set in
  // app/models/role_codes.py.
  const ROLE = window.__userRole;
  const CAN_MANAGE = (ROLE === "admin" || ROLE === "risk_control");
  const CAN_HANDLE = (ROLE === "admin" || ROLE === "handler");

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
    handlers: [],
    currentDetail: null,
    createDraft: null,
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

  const fillHandlers = async () => {
    if (!CAN_MANAGE) return; // only managers see the dropdown populated
    const res = await csrfSafeFetch("/api/users");
    if (!res.ok) return;
    const items = await res.json();
    state.handlers = items.filter((u) => u.role === "handler" && u.is_active);
    const select = document.getElementById("tk_assignee");
    state.handlers.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h.id;
      opt.textContent = `${h.full_name || h.username} (${h.username})`;
      select.appendChild(opt);
    });
    const assignSelect = document.getElementById("assignSelect");
    state.handlers.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h.id;
      opt.textContent = `${h.full_name || h.username} (${h.username})`;
      assignSelect.appendChild(opt);
    });
    const createSelect = document.getElementById("createSelect");
    state.handlers.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h.id;
      opt.textContent = `${h.full_name || h.username} (${h.username})`;
      createSelect.appendChild(opt);
    });
    const newBtn = document.getElementById("tkNewBtn");
    if (newBtn) newBtn.style.display = "";
  };

  const openNewTicketPicker = async () => {
    // Fetch confirmed alerts and let the user pick one to convert.
    const res = await csrfSafeFetch("/api/alerts?status=confirmed&limit=50");
    if (!res.ok) {
      alert("无法加载已确认的预警");
      return;
    }
    const body = await res.json();
    if (!body.items || !body.items.length) {
      alert("当前没有已确认的预警可以转为工单");
      return;
    }
    const idStr = prompt(
      `请输入要转为工单的预警 ID(已确认列表: ${body.items.map((a) => `#${a.id} ${a.opinion.title || ""}`).slice(0, 8).join(" / ")}):`,
      String(body.items[0].id),
    );
    const parsed = idStr ? Number(idStr) : NaN;
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    await openCreateFromAlertDialog(parsed);
  };

  const renderRows = (items) => {
    const tbody = document.getElementById("tkTbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">暂无数据</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    items.forEach((it) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(it.id));
      const titleCell = document.createElement("td");
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = it.title || it.opinion.title || "(无标题)";
      link.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
      titleCell.appendChild(link);
      tr.appendChild(titleCell);
      const levelCell = document.createElement("td");
      levelCell.appendChild(riskPill(it.risk_level));
      tr.appendChild(levelCell);
      const statusCell = document.createElement("td");
      statusCell.appendChild(statusPill(it.status));
      tr.appendChild(statusCell);
      tr.appendChild(td(it.assignee_username || "-"));
      tr.appendChild(td(formatDate(it.created_at)));
      const actionCell = document.createElement("td");
      const viewLink = document.createElement("a");
      viewLink.href = "#";
      viewLink.textContent = "查看";
      viewLink.addEventListener("click", (e) => { e.preventDefault(); openDetail(it); });
      actionCell.appendChild(viewLink);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    });
  };

  const renderPager = () => {
    const page = Math.floor(state.offset / state.limit) + 1;
    const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
    document.getElementById("tkPager").textContent = `第 ${page} / ${totalPages} 页,共 ${state.total} 条`;
    document.getElementById("tkPrev").disabled = state.offset <= 0;
    document.getElementById("tkNext").disabled = state.offset + state.limit >= state.total;
  };

  const renderSummary = (s) => {
    const summary = `未分配 ${s.unassigned} · 进行中 ${s.in_progress} · 已完成 ${s.completed} · 已归档 ${s.archived} · 共 ${s.total}`;
    document.getElementById("tkSummary").textContent = summary;
  };

  const load = async () => {
    const status = document.getElementById("tkStatus");
    setStatus(status, "");
    const [listRes, summaryRes] = await Promise.all([
      csrfSafeFetch(`/api/tickets?${buildQuery()}`),
      csrfSafeFetch("/api/tickets/summary"),
    ]);
    if (listRes.status === 401) { window.location.href = "/login"; return; }
    if (listRes.status === 403) { alert("当前角色无权访问工单列表"); return; }
    if (!listRes.ok) { setStatus(status, `加载失败: ${listRes.status}`, true); return; }
    const body = await listRes.json();
    state.total = body.total;
    renderRows(body.items);
    renderPager();
    setStatus(status, `已加载 ${body.items.length} 条`);
    if (summaryRes.ok) {
      const s = await summaryRes.json();
      renderSummary(s);
    }
  };

  const submitFilter = (event) => {
    event.preventDefault();
    state.filters = {
      q: document.getElementById("tk_q").value.trim(),
      status: document.getElementById("tk_status").value,
      risk_level: document.getElementById("tk_level").value,
      assignee_id: document.getElementById("tk_assignee").value,
      start_at: toIsoSeconds(document.getElementById("tk_start").value),
      end_at: toIsoSeconds(document.getElementById("tk_end").value),
    };
    state.offset = 0;
    load();
  };

  const resetFilter = () => {
    document.getElementById("ticketFilter").reset();
    state.filters = {};
    state.offset = 0;
    load();
  };

  const openDetail = (it) => {
    state.currentDetail = it;
    document.getElementById("ticketDialogTitle").textContent =
      `[${STATUS_LABEL[it.status] || it.status}] #${it.id} ${it.title || it.opinion.title || ""}`;
    renderDetailBody(it);
    renderDetailFooter(it);
    document.getElementById("ticketDialogStatus").textContent = "";
    document.getElementById("ticketDialog").classList.remove("hidden");
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
    html += `<section class="analysis-section"><h4>工单信息</h4><div class="analysis-grid">`;
    const rows = [
      { label: "状态", html: statusPill(it.status).outerHTML },
      { label: "风险等级", html: riskPill(it.risk_level).outerHTML },
      { label: "分数", value: String(it.risk_score) },
      { label: "情感", value: SENTIMENT_LABEL[it.opinion.sentiment] || "—" },
      { label: "创建人", value: it.created_by_username || "—" },
      { label: "创建时间", value: formatDate(it.created_at) },
      { label: "处置人", value: it.assignee_username || "—" },
      { label: "指派人", value: it.assigned_by_username || "—" },
      { label: "指派时间", value: formatDate(it.assigned_at) },
      { label: "开始时间", value: formatDate(it.started_at) },
      { label: "完成时间", value: formatDate(it.completed_at) },
      { label: "归档时间", value: formatDate(it.archived_at) },
    ];
    rows.forEach((m) => {
      html += `<div class="metric"><div class="label">${escapeHtml(m.label)}</div><div class="value">${m.html || escapeHtml(String(m.value))}</div></div>`;
    });
    html += `</div>`;
    if (it.handling_result) {
      html += `<p class="muted small">处置结果:</p><pre style="white-space: pre-wrap; font-family: inherit;">${escapeHtml(it.handling_result)}</pre>`;
    }
    if (it.description) {
      html += `<p class="muted small">描述:</p><pre style="white-space: pre-wrap; font-family: inherit;">${escapeHtml(it.description)}</pre>`;
    }
    html += `<p class="muted small">关联预警 #${it.alert_summary.id} (${it.alert_summary.status}, 由 ${escapeHtml(it.alert_summary.confirmed_by_username || "-")} 于 ${formatDate(it.alert_summary.confirmed_at)} 确认)</p>`;
    html += `</section>`;
    document.getElementById("ticketDialogBody").innerHTML = html;
  };

  const renderDetailFooter = (it) => {
    const footer = document.getElementById("ticketDialogFooter");
    footer.innerHTML = "";
    const myId = (it.assignee_id == null) ? null : Number(it.assignee_id);
    const isMine = (ROLE === "admin") || (ROLE === "handler" && myId !== null);

    const buttons = [];
    if (CAN_MANAGE && it.status !== "archived") {
      buttons.push({ id: "tkAssignBtn", label: it.status === "unassigned" ? "指派处置人" : "重新指派", primary: true });
    }
    if (isMine && (it.status === "unassigned" || it.status === "in_progress")) {
      buttons.push({ id: "tkStartBtn", label: it.status === "unassigned" ? "开始处置" : "刷新开始时间" });
    }
    if (isMine && it.status === "in_progress") {
      buttons.push({ id: "tkCompleteBtn", label: "提交完成", primary: true });
    }
    if (CAN_MANAGE && it.status === "completed") {
      buttons.push({ id: "tkArchiveBtn", label: "归档", primary: true });
    }
    if (!buttons.length) {
      footer.style.display = "none";
      return;
    }
    footer.style.display = "flex";
    buttons.forEach((b) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = b.id;
      btn.textContent = b.label;
      if (b.primary) btn.className = "primary";
      btn.addEventListener("click", () => onFooterAction(b.id));
      footer.appendChild(btn);
    });
  };

  const onFooterAction = (id) => {
    if (id === "tkAssignBtn") openAssignDialog();
    else if (id === "tkStartBtn") callStart();
    else if (id === "tkCompleteBtn") openCompleteDialog();
    else if (id === "tkArchiveBtn") callArchive();
  };

  // ----- Assign -----

  const openAssignDialog = () => {
    if (!state.currentDetail) return;
    if (!state.handlers.length) {
      alert("暂无可用处置人员");
      return;
    }
    const cur = state.currentDetail;
    document.getElementById("assignTitle").value = cur.title || "";
    document.getElementById("assignDescription").value = cur.description || "";
    const select = document.getElementById("assignSelect");
    if (cur.assignee_id) select.value = String(cur.assignee_id);
    setStatus(document.getElementById("assignStatus"), "");
    document.getElementById("assignDialog").classList.remove("hidden");
  };

  const closeAssignDialog = () => {
    document.getElementById("assignDialog").classList.add("hidden");
  };

  const submitAssign = async () => {
    if (!state.currentDetail) return;
    const select = document.getElementById("assignSelect");
    if (!select.value) {
      setStatus(document.getElementById("assignStatus"), "请选择处置人", true);
      return;
    }
    const status = document.getElementById("assignStatus");
    setStatus(status, "提交中...");
    const body = {
      assignee_id: Number(select.value),
      title: document.getElementById("assignTitle").value.trim(),
      description: document.getElementById("assignDescription").value.trim(),
    };
    const res = await csrfSafeFetch(`/api/tickets/${state.currentDetail.id}/assign`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      setStatus(status, `指派失败: ${res.status} ${(await res.text()).slice(0, 200)}`, true);
      return;
    }
    const data = await res.json();
    Object.assign(state.currentDetail, {
      status: data.status,
      assignee_username: data.assignee_username,
      assigned_by_username: data.assigned_by_username,
      assigned_at: data.assigned_at,
      started_at: data.started_at,
    });
    closeAssignDialog();
    renderDetailBody(state.currentDetail);
    renderDetailFooter(state.currentDetail);
    setStatus(document.getElementById("ticketDialogStatus"), "已指派");
    await load();
  };

  // ----- Start -----

  const callStart = async () => {
    if (!state.currentDetail) return;
    const id = state.currentDetail.id;
    setStatus(document.getElementById("ticketDialogStatus"), "提交中...");
    const res = await csrfSafeFetch(`/api/tickets/${id}/start`, { method: "POST" });
    if (!res.ok) {
      setStatus(
        document.getElementById("ticketDialogStatus"),
        `开始失败: ${res.status} ${(await res.text()).slice(0, 200)}`,
        true,
      );
      return;
    }
    const data = await res.json();
    state.currentDetail.status = data.status;
    state.currentDetail.started_at = data.started_at;
    renderDetailBody(state.currentDetail);
    renderDetailFooter(state.currentDetail);
    setStatus(document.getElementById("ticketDialogStatus"), "已开始");
    await load();
  };

  // ----- Complete -----

  const openCompleteDialog = () => {
    if (!state.currentDetail) return;
    document.getElementById("completeResult").value = "";
    setStatus(document.getElementById("completeStatus"), "");
    document.getElementById("completeDialog").classList.remove("hidden");
  };

  const closeCompleteDialog = () => {
    document.getElementById("completeDialog").classList.add("hidden");
  };

  const submitComplete = async () => {
    if (!state.currentDetail) return;
    const result = document.getElementById("completeResult").value.trim();
    const status = document.getElementById("completeStatus");
    if (result.length < 2) {
      setStatus(status, "处置结果至少 2 个字符", true);
      return;
    }
    setStatus(status, "提交中...");
    const res = await csrfSafeFetch(`/api/tickets/${state.currentDetail.id}/complete`, {
      method: "POST",
      body: JSON.stringify({ handling_result: result }),
    });
    if (!res.ok) {
      setStatus(status, `完成失败: ${res.status} ${(await res.text()).slice(0, 200)}`, true);
      return;
    }
    const data = await res.json();
    state.currentDetail.status = data.status;
    state.currentDetail.completed_by_username = data.completed_by_username;
    state.currentDetail.completed_at = data.completed_at;
    state.currentDetail.handling_result = result;
    closeCompleteDialog();
    renderDetailBody(state.currentDetail);
    renderDetailFooter(state.currentDetail);
    setStatus(document.getElementById("ticketDialogStatus"), "已完成");
    await load();
  };

  // ----- Archive -----

  const callArchive = async () => {
    if (!state.currentDetail) return;
    if (!confirm("确认要归档这个工单吗?归档后将从活动列表中分离。")) return;
    setStatus(document.getElementById("ticketDialogStatus"), "提交中...");
    const res = await csrfSafeFetch(`/api/tickets/${state.currentDetail.id}/archive`, { method: "POST" });
    if (!res.ok) {
      setStatus(
        document.getElementById("ticketDialogStatus"),
        `归档失败: ${res.status} ${(await res.text()).slice(0, 200)}`,
        true,
      );
      return;
    }
    const data = await res.json();
    state.currentDetail.status = data.status;
    state.currentDetail.archived_by_username = data.archived_by_username;
    state.currentDetail.archived_at = data.archived_at;
    renderDetailBody(state.currentDetail);
    renderDetailFooter(state.currentDetail);
    setStatus(document.getElementById("ticketDialogStatus"), "已归档");
    await load();
  };

  // ----- dialogs -----

  const closeDetail = () => {
    document.getElementById("ticketDialog").classList.add("hidden");
    state.currentDetail = null;
  };

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("ticketFilter").addEventListener("submit", submitFilter);
    document.getElementById("tkReset").addEventListener("click", resetFilter);
    document.getElementById("tkPrev").addEventListener("click", () => {
      if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); load(); }
    });
    document.getElementById("tkNext").addEventListener("click", () => {
      if (state.offset + state.limit < state.total) { state.offset += state.limit; load(); }
    });
    document.getElementById("ticketDialogClose").addEventListener("click", closeDetail);
    document.getElementById("ticketDialog").addEventListener("click", (e) => {
      if (e.target.id === "ticketDialog") closeDetail();
    });
    document.getElementById("assignDialogClose").addEventListener("click", closeAssignDialog);
    document.getElementById("assignCancel").addEventListener("click", closeAssignDialog);
    document.getElementById("assignSubmit").addEventListener("click", submitAssign);
    document.getElementById("assignDialog").addEventListener("click", (e) => {
      if (e.target.id === "assignDialog") closeAssignDialog();
    });
    document.getElementById("completeDialogClose").addEventListener("click", closeCompleteDialog);
    document.getElementById("completeCancel").addEventListener("click", closeCompleteDialog);
    document.getElementById("completeSubmit").addEventListener("click", submitComplete);
    document.getElementById("completeDialog").addEventListener("click", (e) => {
      if (e.target.id === "completeDialog") closeCompleteDialog();
    });
    document.getElementById("createDialogClose").addEventListener("click", closeCreateDialog);
    document.getElementById("createCancel").addEventListener("click", closeCreateDialog);
    document.getElementById("createSubmit").addEventListener("click", submitCreate);
    document.getElementById("createDialog").addEventListener("click", (e) => {
      if (e.target.id === "createDialog") closeCreateDialog();
    });
    await fillHandlers();
    await load();

    const newBtn = document.getElementById("tkNewBtn");
    if (newBtn && CAN_MANAGE) {
      newBtn.style.display = "";
      newBtn.addEventListener("click", openNewTicketPicker);
    }

    // If we arrived via "转为工单" from the alerts page, the URL has
    // ?from_alert=<id>. Open the create dialog preloaded for that alert.
    if (CAN_MANAGE) {
      const params = new URLSearchParams(window.location.search);
      const fromAlert = params.get("from_alert");
      if (fromAlert) {
        await openCreateFromAlertDialog(Number(fromAlert));
      }
    }
  });

  const openCreateFromAlertDialog = async (alertId) => {
    // Fetch the alert so we can show its title / level inside the dialog.
    const res = await csrfSafeFetch(`/api/alerts/${alertId}`);
    if (!res.ok) {
      alert("无法加载该预警");
      return;
    }
    const alert = await res.json();
    if (alert.status !== "confirmed") {
      alert("只有已确认的预警可以转为工单");
      return;
    }
    state.createDraft = { alertId, title: alert.opinion.title || "", description: "" };
    renderCreateDialog();
    document.getElementById("createDialog").classList.remove("hidden");
  };

  const renderCreateDialog = () => {
    if (!state.createDraft) return;
    document.getElementById("createTitle").value = state.createDraft.title || "";
    document.getElementById("createDescription").value = state.createDraft.description || "";
    document.getElementById("createSelect").value = "";
    document.getElementById("createDialogHint").textContent =
      `将预警 #${state.createDraft.alertId} 转为工单。`;
    setStatus(document.getElementById("createStatus"), "");
  };

  const closeCreateDialog = () => {
    document.getElementById("createDialog").classList.add("hidden");
    state.createDraft = null;
  };

  const submitCreate = async () => {
    if (!state.createDraft) return;
    const status = document.getElementById("createStatus");
    const assigneeId = document.getElementById("createSelect").value;
    const body = {
      alert_id: state.createDraft.alertId,
      title: document.getElementById("createTitle").value.trim(),
      description: document.getElementById("createDescription").value.trim(),
    };
    if (assigneeId) body.assignee_id = Number(assigneeId);
    setStatus(status, "提交中...");
    const res = await csrfSafeFetch("/api/tickets/from-alert", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (res.status === 201) {
      const data = await res.json();
      closeCreateDialog();
      // Clean the URL so reloads don't re-open the dialog.
      const url = new URL(window.location.href);
      url.searchParams.delete("from_alert");
      window.history.replaceState({}, "", url.toString());
      setStatus(document.getElementById("tkStatus"),
        `已创建工单 #${data.id} (${data.status})`, false);
      await load();
      return;
    }
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch (_) { detail = (await res.text()).slice(0, 200); }
    setStatus(status, `创建失败: ${res.status} ${detail}`, true);
  };
})();
