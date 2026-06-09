(function () {
  "use strict";

  // Polling cadence for the auto-refresh. The page also re-renders
  // immediately after visibility changes so a user coming back from a
  // backgrounded tab does not stare at stale numbers.
  const REFRESH_INTERVAL_MS = 30000;

  const RISK_LABEL = { low: "低", medium: "中", high: "高", severe: "严重" };
  const STATUS_LABEL = { pending: "待确认", confirmed: "已确认", ignored: "已忽略" };

  const csrfSafeFetch = (url) =>
    fetch(url, { credentials: "same-origin" });

  const setStatus = (message, isError) => {
    const el = document.getElementById("dashStatus");
    if (!el) return;
    el.textContent = message || "";
    el.classList.toggle("error", !!isError);
    el.classList.toggle("ok", !isError && !!message);
  };

  const setField = (key, value) => {
    const nodes = document.querySelectorAll(`[data-field="${key}"]`);
    nodes.forEach((el) => {
      if (value === null || value === undefined) {
        el.textContent = "-";
        el.parentElement.classList.add("muted-card");
        return;
      }
      el.parentElement.classList.remove("muted-card");
      el.textContent = formatValue(key, value);
    });
  };

  const formatValue = (key, value) => {
    if (key === "opinion_negative_ratio") {
      return `占比 ${(value * 100).toFixed(1)}%`;
    }
    if (key === "opinion_analyzed_total") {
      return `已分析 ${value} 条`;
    }
    if (key === "alerts_pending") {
      return `待确认 ${value} 条`;
    }
    if (key === "tickets_unassigned") {
      return `未指派 ${value} 条`;
    }
    return String(value);
  };

  const hideCardIfMissing = (key) => {
    const card = document.querySelector(`[data-card] [data-field="${key}"]`);
    if (!card) return;
    const article = card.closest(".metric-card");
    if (article) article.classList.add("hidden");
  };

  const showAllCards = () => {
    document.querySelectorAll(".metric-card").forEach((el) => el.classList.remove("hidden"));
  };

  const formatDate = (iso) => {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const formatDateShort = (iso) => {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };

  // ---- trend renderer ----

  const renderTrend = (points) => {
    const container = document.getElementById("dashTrendBars");
    if (!container) return;
    container.innerHTML = "";
    if (!Array.isArray(points) || points.length === 0) {
      container.innerHTML = '<p class="muted small">暂无趋势数据</p>';
      return;
    }
    const maxTotal = Math.max(1, ...points.map((p) => p.total || 0));
    points.forEach((p) => {
      const row = document.createElement("div");
      row.className = "trend-bar";
      row.setAttribute("role", "listitem");

      const totalHeight = Math.round(((p.total || 0) / maxTotal) * 100);
      const negativeHeight = Math.round(((p.negative || 0) / maxTotal) * 100);
      const severeHeight = Math.round(((p.high_or_severe || 0) / maxTotal) * 100);

      const stack = document.createElement("div");
      stack.className = "trend-stack";
      stack.style.height = `${Math.max(4, totalHeight)}%`;
      stack.title = `日期 ${p.date} · 总数 ${p.total} · 负面 ${p.negative} · 高/严重 ${p.high_or_severe}`;

      if (severeHeight > 0) {
        const severe = document.createElement("div");
        severe.className = "trend-segment severe";
        severe.style.height = `${(severeHeight / Math.max(1, totalHeight)) * 100}%`;
        stack.appendChild(severe);
      }
      if (negativeHeight > 0) {
        const negative = document.createElement("div");
        negative.className = "trend-segment negative";
        negative.style.height = `${(negativeHeight / Math.max(1, totalHeight)) * 100}%`;
        stack.appendChild(negative);
      }

      row.appendChild(stack);

      const label = document.createElement("div");
      label.className = "trend-label";
      label.textContent = formatDateShort(p.date);
      row.appendChild(label);

      const count = document.createElement("div");
      count.className = "trend-count";
      count.textContent = String(p.total || 0);
      row.appendChild(count);

      container.appendChild(row);
    });
  };

  // ---- latest alerts renderer ----

  const renderLatestAlerts = (items) => {
    const tbody = document.getElementById("dashLatestAlerts");
    if (!tbody) return;
    if (!Array.isArray(items) || items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted">暂无预警</td></tr>';
      return;
    }
    tbody.innerHTML = "";
    items.forEach((it) => {
      const tr = document.createElement("tr");
      const title = document.createElement("td");
      title.textContent = it.opinion_title || `舆情 #${it.opinion_item_id}`;
      tr.appendChild(title);

      const source = document.createElement("td");
      source.textContent = it.opinion_source_name || it.opinion_source_code || "-";
      tr.appendChild(source);

      const risk = document.createElement("td");
      const riskPill = document.createElement("span");
      riskPill.className = `risk-pill ${it.risk_level || "none"}`;
      riskPill.textContent = `${RISK_LABEL[it.risk_level] || "—"}(${it.risk_score})`;
      risk.appendChild(riskPill);
      tr.appendChild(risk);

      const status = document.createElement("td");
      const statusPill = document.createElement("span");
      statusPill.className = `alert-pill ${it.status || "none"}`;
      statusPill.textContent = STATUS_LABEL[it.status] || it.status || "—";
      status.appendChild(statusPill);
      tr.appendChild(status);

      const time = document.createElement("td");
      time.textContent = formatDate(it.created_at);
      tr.appendChild(time);

      tbody.appendChild(tr);
    });
  };

  // ---- main ----

  const renderSummary = (summary) => {
    showAllCards();
    const numericFields = [
      "opinion_total",
      "opinion_analyzed_total",
      "opinion_negative_total",
      "opinion_negative_ratio",
      "alerts_high_or_severe_total",
      "alerts_pending",
      "tickets_unassigned",
      "tickets_in_progress",
    ];
    numericFields.forEach((key) => {
      const value = summary[key];
      if (value === null || value === undefined) {
        // Field missing for this role - hide the card and its sub.
        setField(key, null);
        hideCardIfMissing(key);
        return;
      }
      setField(key, value);
    });

    // If the alerts/tickets cards are entirely null, hide the parent panel.
    const alertsCard = document.querySelector('[data-card="alerts"]');
    if (
      summary.alerts_high_or_severe_total === null
      && summary.alerts_pending === null
    ) {
      alertsCard?.classList.add("hidden");
    }
    const ticketsCard = document.querySelector('[data-card="tickets"]');
    if (
      summary.tickets_in_progress === null
      && summary.tickets_unassigned === null
    ) {
      ticketsCard?.classList.add("hidden");
    }

    renderTrend(summary.trend || []);
    renderLatestAlerts(summary.latest_alerts || []);
  };

  const loadSummary = async () => {
    try {
      const res = await csrfSafeFetch("/api/dashboard/summary");
      if (!res.ok) {
        setStatus(`加载失败 (HTTP ${res.status})`, true);
        return;
      }
      const body = await res.json();
      renderSummary(body);
      setStatus(`已更新 · ${formatDate(body.generated_at)}`, false);
    } catch (err) {
      setStatus(`网络错误: ${err.message || err}`, true);
    }
  };

  // Initial load + auto-refresh. Re-render on visibility change so a
  // backgrounded tab does not show stale numbers when the user returns.
  loadSummary();
  setInterval(loadSummary, REFRESH_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadSummary();
  });
})();
