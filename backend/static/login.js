(function () {
  const form = document.getElementById("loginForm");
  const errorEl = document.getElementById("loginError");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.classList.add("hidden");
    errorEl.textContent = "";
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    if (!username || !password) return;
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        errorEl.textContent = (body && body.detail) || "登录失败";
        errorEl.classList.remove("hidden");
        return;
      }
      window.location.href = "/web/workbench";
    } catch (err) {
      errorEl.textContent = "网络错误,请稍后重试";
      errorEl.classList.remove("hidden");
    }
  });
})();
