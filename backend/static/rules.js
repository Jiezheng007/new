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

  const state = { sensitive: [], subject: [], thresholds: [] };

  const renderThresholds = () => {
    document.querySelectorAll("[data-threshold-level]").forEach((input) => {
      const level = input.dataset.thresholdLevel;
      const match = state.thresholds.find((t) => t.level === level);
      if (match) input.value = match.min_score;
    });
  };

  const renderSensitive = () => {
    const tbody = document.getElementById("sensitiveTbody");
    if (!state.sensitive.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">暂无敏感词</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    state.sensitive.forEach((s) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(s.id));
      tr.appendChild(td(s.keyword));
      tr.appendChild(td(s.category || "-"));
      tr.appendChild(td(s.severity));
      const statusCell = document.createElement("td");
      const pill = document.createElement("span");
      pill.className = "status-pill " + (s.is_active ? "on" : "off");
      pill.textContent = s.is_active ? "启用" : "停用";
      statusCell.appendChild(pill);
      tr.appendChild(statusCell);
      tr.appendChild(td(formatDate(s.updated_at)));
      const actions = document.createElement("td");
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "link-button";
      toggleBtn.textContent = s.is_active ? "停用" : "启用";
      toggleBtn.addEventListener("click", () => toggleSensitive(s));
      actions.appendChild(toggleBtn);
      actions.appendChild(document.createTextNode(" · "));
      const severityBtn = document.createElement("button");
      severityBtn.type = "button";
      severityBtn.className = "link-button";
      const order = ["low", "medium", "high", "severe"];
      const next = order[(order.indexOf(s.severity) + 1) % order.length];
      severityBtn.textContent = `改 ${next}`;
      severityBtn.addEventListener("click", () => updateSensitive(s, { severity: next }));
      actions.appendChild(severityBtn);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  };

  const renderSubject = () => {
    const tbody = document.getElementById("subjectTbody");
    if (!state.subject.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="muted">暂无主体词</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    state.subject.forEach((s) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(s.id));
      tr.appendChild(td(s.keyword));
      tr.appendChild(td(s.category || "-"));
      const statusCell = document.createElement("td");
      const pill = document.createElement("span");
      pill.className = "status-pill " + (s.is_active ? "on" : "off");
      pill.textContent = s.is_active ? "启用" : "停用";
      statusCell.appendChild(pill);
      tr.appendChild(statusCell);
      tr.appendChild(td(formatDate(s.updated_at)));
      const actions = document.createElement("td");
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "link-button";
      toggleBtn.textContent = s.is_active ? "停用" : "启用";
      toggleBtn.addEventListener("click", () => toggleSubject(s));
      actions.appendChild(toggleBtn);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  };

  const td = (text) => {
    const el = document.createElement("td");
    el.textContent = text == null ? "" : String(text);
    return el;
  };

  const loadAll = async () => {
    const [s, b, t] = await Promise.all([
      csrfSafeFetch("/api/rules/sensitive-keywords"),
      csrfSafeFetch("/api/rules/subject-keywords"),
      csrfSafeFetch("/api/rules/thresholds"),
    ]);
    if ([s, b, t].some((r) => r.status === 401)) {
      window.location.href = "/login";
      return;
    }
    if ([s, b, t].some((r) => r.status === 403)) {
      alert("当前角色无权访问规则管理");
      return;
    }
    state.sensitive = await s.json();
    state.subject = await b.json();
    state.thresholds = await t.json();
    renderThresholds();
    renderSensitive();
    renderSubject();
  };

  const submitThresholds = async (event) => {
    event.preventDefault();
    const status = document.getElementById("thresholdStatus");
    setStatus(status, "");
    const thresholds = Array.from(document.querySelectorAll("[data-threshold-level]"))
      .map((input) => ({ level: input.dataset.thresholdLevel, min_score: parseInt(input.value, 10) }))
      .filter((t) => Number.isFinite(t.min_score));
    const res = await csrfSafeFetch("/api/rules/thresholds", {
      method: "PUT",
      body: JSON.stringify({ thresholds }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setStatus(status, (body && body.detail) || "保存失败", true);
      return;
    }
    setStatus(status, "已保存", false);
    await loadAll();
  };

  const submitSensitive = async (event) => {
    event.preventDefault();
    const status = document.getElementById("sensitiveStatus");
    setStatus(status, "");
    const payload = {
      keyword: document.getElementById("sk_keyword").value.trim(),
      category: document.getElementById("sk_category").value.trim(),
      severity: document.getElementById("sk_severity").value,
      is_active: document.getElementById("sk_is_active").checked,
      remark: document.getElementById("sk_remark").value.trim(),
    };
    const res = await csrfSafeFetch("/api/rules/sensitive-keywords", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setStatus(status, (body && body.detail) || "新增失败", true);
      return;
    }
    setStatus(status, "已新增", false);
    document.getElementById("sensitiveCreateForm").reset();
    document.getElementById("sk_is_active").checked = true;
    document.getElementById("sk_severity").value = "medium";
    await loadAll();
  };

  const submitSubject = async (event) => {
    event.preventDefault();
    const status = document.getElementById("subjectStatus");
    setStatus(status, "");
    const payload = {
      keyword: document.getElementById("sbj_keyword").value.trim(),
      category: document.getElementById("sbj_category").value.trim(),
      is_active: document.getElementById("sbj_is_active").checked,
      remark: document.getElementById("sbj_remark").value.trim(),
    };
    const res = await csrfSafeFetch("/api/rules/subject-keywords", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setStatus(status, (body && body.detail) || "新增失败", true);
      return;
    }
    setStatus(status, "已新增", false);
    document.getElementById("subjectCreateForm").reset();
    document.getElementById("sbj_is_active").checked = true;
    await loadAll();
  };

  const updateSensitive = async (row, payload) => {
    const res = await csrfSafeFetch(`/api/rules/sensitive-keywords/${row.id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      alert((body && body.detail) || "更新失败");
      return;
    }
    await loadAll();
  };

  const toggleSensitive = (row) => updateSensitive(row, { is_active: !row.is_active });

  const updateSubject = async (row, payload) => {
    const res = await csrfSafeFetch(`/api/rules/subject-keywords/${row.id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      alert((body && body.detail) || "更新失败");
      return;
    }
    await loadAll();
  };

  const toggleSubject = (row) => updateSubject(row, { is_active: !row.is_active });

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("thresholdForm").addEventListener("submit", submitThresholds);
    document.getElementById("sensitiveCreateForm").addEventListener("submit", submitSensitive);
    document.getElementById("subjectCreateForm").addEventListener("submit", submitSubject);
    loadAll();
  });
})();
