(function () {
  const csrfSafeFetch = (url, options = {}) => {
    const opts = Object.assign({ credentials: "same-origin" }, options);
    if (opts.headers === undefined) {
      opts.headers = {};
    }
    return fetch(url, opts);
  };

  const setStatus = (el, message, isError = false) => {
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.toggle("ok", !isError && !!message);
  };

  const showResult = (body) => {
    document.getElementById("importResult").textContent = JSON.stringify(body, null, 2);
  };

  const submitForm = async (formId, statusId, endpoint) => {
    const form = document.getElementById(formId);
    const status = document.getElementById(statusId);
    setStatus(status, "");
    const fd = new FormData(form);
    const res = await csrfSafeFetch(endpoint, { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = (body && (body.detail || body.message)) || "上传失败";
      setStatus(status, typeof detail === "string" ? detail : JSON.stringify(detail), true);
      showResult(body);
      return;
    }
    setStatus(status, body.message || "完成", false);
    showResult(body);
  };

  const loadDemo = async () => {
    const status = document.getElementById("demoStatus");
    setStatus(status, "");
    const res = await csrfSafeFetch("/api/import/demo", { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = (body && body.detail) || "加载失败";
      setStatus(status, typeof detail === "string" ? detail : JSON.stringify(detail), true);
      return;
    }
    setStatus(status, body.message || "完成", false);
    showResult(body);
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("csvForm").addEventListener("submit", (e) => {
      e.preventDefault();
      submitForm("csvForm", "csvStatus", "/api/import/csv");
    });
    document.getElementById("jsonForm").addEventListener("submit", (e) => {
      e.preventDefault();
      submitForm("jsonForm", "jsonStatus", "/api/import/json");
    });
    document.getElementById("loadDemo").addEventListener("click", loadDemo);
  });
})();
