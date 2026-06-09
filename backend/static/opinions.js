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

  const state = { sources: [], filters: {}, offset: 0, limit: 50, total: 0 };

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
      tbody.innerHTML = `<tr><td colspan="6" class="muted">暂无数据</td></tr>`;
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
      tr.appendChild(td(it.author || "-"));
      tr.appendChild(td(formatDate(it.published_at)));
      tr.appendChild(td(it.origin));
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
    document.getElementById("opinionDialogTitle").textContent = it.title || "(无标题)";
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
    document.getElementById("opinionDialogBody").textContent = lines.join("\n");
    document.getElementById("opinionDialog").classList.remove("hidden");
  };

  const closeDetail = () => {
    document.getElementById("opinionDialog").classList.add("hidden");
  };

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("opinionFilter").addEventListener("submit", submitFilter);
    document.getElementById("opReset").addEventListener("click", resetFilter);
    document.getElementById("opPrev").addEventListener("click", () => {
      if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); load(); }
    });
    document.getElementById("opNext").addEventListener("click", () => {
      if (state.offset + state.limit < state.total) { state.offset += state.limit; load(); }
    });
    document.getElementById("opinionDialogClose").addEventListener("click", closeDetail);
    document.getElementById("opinionDialog").addEventListener("click", (e) => {
      if (e.target.id === "opinionDialog") closeDetail();
    });
    await fillSources();
    await load();
  });
})();
