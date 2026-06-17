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

  const state = { sources: [] };

  const readConfig = () => {
    const raw = document.getElementById("ds_config").value.trim();
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (e) {
      throw new Error("高级配置 JSON 格式不正确");
    }
  };

  const buildPayload = () => ({
    code: document.getElementById("ds_code").value.trim(),
    name: document.getElementById("ds_name").value.trim(),
    source_type: document.getElementById("ds_source_type").value,
    url: document.getElementById("ds_url").value.trim(),
    query: document.getElementById("ds_query").value.trim(),
    fetch_interval_minutes: parseInt(document.getElementById("ds_fetch_interval_minutes").value || "60", 10),
    max_items_per_fetch: parseInt(document.getElementById("ds_max_items_per_fetch").value || "50", 10),
    config: readConfig(),
    weight: parseFloat(document.getElementById("ds_weight").value || "1.0"),
    is_enabled: document.getElementById("ds_is_enabled").checked,
    description: document.getElementById("ds_description").value.trim(),
  });

  const renderTable = () => {
    const tbody = document.getElementById("dsTbody");
    if (!state.sources.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="muted">暂无数据源</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    state.sources.forEach((s) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(s.id));
      tr.appendChild(td(s.code));
      tr.appendChild(td(s.name));
      tr.appendChild(td(s.source_type));
      tr.appendChild(td(s.query || "-"));
      tr.appendChild(td(s.weight));
      const statusCell = document.createElement("td");
      const pill = document.createElement("span");
      pill.className = "status-pill " + (s.is_enabled ? "on" : "off");
      pill.textContent = s.is_enabled ? "启用" : "停用";
      statusCell.appendChild(pill);
      tr.appendChild(statusCell);
      tr.appendChild(td(formatDate(s.latest_fetch_at) + (s.latest_fetch_status ? ` (${s.latest_fetch_status})` : "")));
      tr.appendChild(td(s.latest_items_count));

      const actions = document.createElement("td");
      const fetchBtn = document.createElement("button");
      fetchBtn.type = "button";
      fetchBtn.className = "link-button";
      fetchBtn.textContent = "抓取";
      fetchBtn.disabled = !s.is_enabled;
      fetchBtn.addEventListener("click", () => triggerFetch(s));
      actions.appendChild(fetchBtn);
      actions.appendChild(document.createTextNode(" · "));
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "link-button";
      toggleBtn.textContent = s.is_enabled ? "停用" : "启用";
      toggleBtn.addEventListener("click", () => toggleSource(s));
      actions.appendChild(toggleBtn);
      actions.appendChild(document.createTextNode(" · "));
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "link-button danger";
      deleteBtn.textContent = "删除";
      deleteBtn.addEventListener("click", () => deleteSource(s));
      actions.appendChild(deleteBtn);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  };

  const loadAll = async () => {
    const res = await csrfSafeFetch("/api/datasources");
    if (res.status === 401) { window.location.href = "/login"; return; }
    if (res.status === 403) {
      await window.alertModal({ title: "无权操作", message: "当前角色无权管理数据源" });
      return;
    }
    state.sources = await res.json();
    renderTable();
  };

  const submitCreate = async (event) => {
    event.preventDefault();
    const status = document.getElementById("dsCreateStatus");
    setStatus(status, "");
    let payload;
    try {
      payload = buildPayload();
    } catch (e) {
      setStatus(status, e.message || "表单配置不正确", true);
      return;
    }
    const res = await csrfSafeFetch("/api/datasources", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setStatus(status, (body && body.detail) || "新增失败", true);
      return;
    }
    setStatus(status, "已新增", false);
    document.getElementById("dsCreateForm").reset();
    document.getElementById("ds_is_enabled").checked = true;
    document.getElementById("ds_weight").value = "1.0";
    document.getElementById("ds_fetch_interval_minutes").value = "60";
    document.getElementById("ds_max_items_per_fetch").value = "50";
    await loadAll();
  };

  const testConfig = async () => {
    const status = document.getElementById("dsCreateStatus");
    setStatus(status, "");
    let payload;
    try {
      payload = buildPayload();
    } catch (e) {
      setStatus(status, e.message || "表单配置不正确", true);
      return;
    }
    const res = await csrfSafeFetch("/api/datasources/test", {
      method: "POST",
      body: JSON.stringify({
        source_type: payload.source_type,
        url: payload.url,
        query: payload.query,
        max_items_per_fetch: Math.min(payload.max_items_per_fetch || 5, 5),
        config: payload.config,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.ok === false) {
      setStatus(status, (body && (body.message || body.detail)) || "测试抓取失败", true);
      return;
    }
    const firstTitle = body.samples && body.samples[0] ? `: ${body.samples[0].title}` : "";
    setStatus(status, `${body.message}${firstTitle}`, false);
  };

  const triggerFetch = async (s) => {
    if (!(await window.confirmModal({
      title: "触发抓取",
      message: `确定要触发数据源「${s.name}」的抓取吗?`,
      confirmText: "开始抓取",
    }))) return;
    const res = await csrfSafeFetch(`/api/datasources/${s.id}/fetch`, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      await window.alertModal({
        title: "抓取失败",
        message: (body && body.detail) || "抓取失败",
        danger: true,
      });
      await loadAll();
      return;
    }
    await window.alertModal({
      title: "抓取完成",
      message: `抓取完成:${body.message}`,
    });
    await loadAll();
  };

  const toggleSource = async (s) => {
    const verb = s.is_enabled ? "停用" : "启用";
    if (!(await window.confirmModal({
      title: `${verb}数据源`,
      message: `确定要${verb}数据源「${s.name}」吗?`,
      confirmText: verb,
    }))) return;
    const res = await csrfSafeFetch(`/api/datasources/${s.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_enabled: !s.is_enabled }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      await window.alertModal({
        title: `${verb}失败`,
        message: (body && body.detail) || `${verb}失败`,
        danger: true,
      });
      return;
    }
    await loadAll();
  };

  const confirmDeleteSource = (s) => new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "dialog";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const card = document.createElement("div");
    card.className = "dialog-card";
    card.style.width = "min(520px, 92vw)";

    const header = document.createElement("header");
    const title = document.createElement("h3");
    title.textContent = "删除数据源";
    header.appendChild(title);
    card.appendChild(header);

    const body = document.createElement("div");
    const message = document.createElement("p");
    message.className = "page-modal-msg";
    const itemCount = Number(s.latest_items_count || 0);
    message.textContent = `确定要删除数据源「${s.name}」吗? 当前关联历史舆情 ${itemCount} 条。`;
    body.appendChild(message);

    const cascadeLabel = document.createElement("label");
    cascadeLabel.className = "checkbox";
    cascadeLabel.style.marginTop = "0.8rem";
    const cascadeInput = document.createElement("input");
    cascadeInput.type = "checkbox";
    cascadeInput.disabled = itemCount === 0;
    const cascadeText = document.createElement("span");
    cascadeText.textContent = itemCount === 0
      ? "该数据源没有历史舆情数据,无需连带删除"
      : "同时删除该数据源下的历史舆情、分析结果、预警和工单";
    cascadeLabel.appendChild(cascadeInput);
    cascadeLabel.appendChild(cascadeText);
    body.appendChild(cascadeLabel);

    const warning = document.createElement("p");
    warning.className = "muted small";
    warning.style.marginTop = "0.8rem";
    warning.textContent = "连带删除不可恢复;审计日志会保留本次删除记录。";
    body.appendChild(warning);
    card.appendChild(body);

    const actions = document.createElement("div");
    actions.className = "page-modal-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "link-button";
    cancelBtn.textContent = "取消";
    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "primary";
    confirmBtn.style.background = "var(--alarm)";
    confirmBtn.textContent = "删除";
    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    card.appendChild(actions);
    overlay.appendChild(card);

    const escHandler = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        done(false);
      }
    };
    const done = (confirmed) => {
      document.removeEventListener("keydown", escHandler, true);
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      resolve({ confirmed, cascade: confirmed && cascadeInput.checked });
    };
    cancelBtn.addEventListener("click", () => done(false));
    confirmBtn.addEventListener("click", () => done(true));
    overlay.addEventListener("click", (e) => { if (e.target === overlay) done(false); });
    document.addEventListener("keydown", escHandler, true);
    document.body.appendChild(overlay);
    setTimeout(() => confirmBtn.focus(), 0);
  });

  const deleteSource = async (s) => {
    const decision = await confirmDeleteSource(s);
    if (!decision.confirmed) return;
    const cascadeQuery = decision.cascade ? "?cascade=true" : "";
    const res = await csrfSafeFetch(`/api/datasources/${s.id}${cascadeQuery}`, { method: "DELETE" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      await window.alertModal({
        title: "删除失败",
        message: (body && body.detail) || "删除失败",
        danger: true,
      });
      return;
    }
    await loadAll();
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("dsCreateForm").addEventListener("submit", submitCreate);
    document.getElementById("dsTestBtn").addEventListener("click", testConfig);
    loadAll();
  });
})();
