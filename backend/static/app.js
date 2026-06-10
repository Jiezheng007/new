(function () {
  // ---- Logout ----
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

  // ---- Topbar masthead: date stamp + live clock ----
  const topbar = document.querySelector(".topbar");
  const clock = document.getElementById("topbarClock");

  const pad2 = (n) => String(n).padStart(2, "0");
  const ROMAN = ["I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII"];

  const setEdition = () => {
    if (!topbar) return;
    const d = new Date();
    const edition = `Vol. ${d.getFullYear()} · No. ${ROMAN[d.getMonth()]}.${pad2(d.getDate())}`;
    topbar.setAttribute("data-edition", edition);
  };

  const tickClock = () => {
    if (!clock) return;
    const d = new Date();
    clock.textContent = `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  };

  setEdition();
  tickClock();
  setInterval(tickClock, 1000);
})();
