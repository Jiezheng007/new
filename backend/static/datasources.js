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

  const renderTable = () => {
    const tbody = document.getElementById("dsTbody");
    if (!state.sources.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="muted">暂无数据源</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    state.sources.forEach((s) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(s.id));
      tr.appendChild(td(s.code));
      tr.appendChild(td(s.name));
      tr.appendChild(td(s.source_type));
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
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  };

  const loadAll = async () => {
    const res = await csrfSafeFetch("/api/datasources");
    if (res.status === 401) { window.location.href = "/login"; return; }
    if (res.status === 403) { alert("当前角色无权管理数据源"); return; }
    state.sources = await res.json();
    renderTable();
  };

  const submitCreate = async (event) => {
    event.preventDefault();
    const status = document.getElementById("dsCreateStatus");
    setStatus(status, "");
    const payload = {
      code: document.getElementById("ds_code").value.trim(),
      name: document.getElementById("ds_name").value.trim(),
      source_type: document.getElementById("ds_source_type").value,
      url: document.getElementById("ds_url").value.trim(),
      weight: parseFloat(document.getElementById("ds_weight").value || "1.0"),
      is_enabled: document.getElementById("ds_is_enabled").checked,
      description: document.getElementById("ds_description").value.trim(),
    };
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
    await loadAll();
  };

  const triggerFetch = async (s) => {
    if (!confirm(`确定要触发数据源「${s.name}」的抓取吗?`)) return;
    const res = await csrfSafeFetch(`/api/datasources/${s.id}/fetch`, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert((body && body.detail) || "抓取失败");
      await loadAll();
      return;
    }
    alert(`抓取完成:${body.message}`);
    await loadAll();
  };

  const toggleSource = async (s) => {
    const verb = s.is_enabled ? "停用" : "启用";
    if (!confirm(`确定要${verb}数据源「${s.name}」吗?`)) return;
    const res = await csrfSafeFetch(`/api/datasources/${s.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_enabled: !s.is_enabled }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      alert((body && body.detail) || `${verb}失败`);
      return;
    }
    await loadAll();
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("dsCreateForm").addEventListener("submit", submitCreate);
    loadAll();
  });
})();
