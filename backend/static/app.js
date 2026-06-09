(function () {
  const btn = document.getElementById("logoutBtn");
  if (btn) {
    btn.addEventListener("click", async () => {
      try {
        await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
      } catch (_) {
        // even if the request fails, drop the local cookie and redirect
      }
      document.cookie = "access_token=; Path=/; Max-Age=0; SameSite=Lax";
      window.location.href = "/login";
    });
  }
})();
