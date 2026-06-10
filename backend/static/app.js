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

  // ---- In-page modal (confirm / alert) ----
  // Replaces window.confirm/alert so userscript dialog-suppressors
  // (e.g. disable_dialogs.js) cannot auto-accept dangerous actions.
  const ensureModalStyles = () => {
    if (document.getElementById("pageModalStyles")) return;
    const style = document.createElement("style");
    style.id = "pageModalStyles";
    style.textContent = `
      .page-modal-msg {
        color: var(--text);
        line-height: 1.55;
        margin: 0 0 0.4rem;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .page-modal-actions {
        display: flex;
        gap: 0.6rem;
        justify-content: flex-end;
        margin-top: 0.6rem;
      }
    `;
    document.head.appendChild(style);
  };

  const closePageModal = (overlay) => {
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    document.removeEventListener("keydown", overlay._escHandler, true);
  };

  const buildPageModal = ({ title, message, confirmText, cancelText, okOnly, danger }) => {
    ensureModalStyles();
    const overlay = document.createElement("div");
    overlay.className = "dialog";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const card = document.createElement("div");
    card.className = "dialog-card";
    card.style.width = "min(440px, 92vw)";

    const header = document.createElement("header");
    const h3 = document.createElement("h3");
    h3.textContent = title || "提示";
    header.appendChild(h3);
    card.appendChild(header);

    const body = document.createElement("div");
    const p = document.createElement("p");
    p.className = "page-modal-msg";
    p.textContent = message || "";
    body.appendChild(p);
    card.appendChild(body);

    const actions = document.createElement("div");
    actions.className = "page-modal-actions";

    let cancelBtn = null;
    if (!okOnly) {
      cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "link-button";
      cancelBtn.textContent = cancelText || "取消";
      actions.appendChild(cancelBtn);
    }
    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "primary";
    confirmBtn.textContent = confirmText || "确定";
    if (danger) confirmBtn.style.background = "var(--alarm)";
    actions.appendChild(confirmBtn);
    card.appendChild(actions);

    overlay.appendChild(card);
    return { overlay, confirmBtn, cancelBtn };
  };

  window.confirmModal = ({ title, message, confirmText, cancelText, danger } = {}) => {
    return new Promise((resolve) => {
      const { overlay, confirmBtn, cancelBtn } = buildPageModal({
        title, message, confirmText, cancelText, danger,
      });
      const done = (val) => { closePageModal(overlay); resolve(val); };
      confirmBtn.addEventListener("click", () => done(true));
      cancelBtn.addEventListener("click", () => done(false));
      overlay.addEventListener("click", (e) => { if (e.target === overlay) done(false); });
      overlay._escHandler = (e) => {
        if (e.key === "Escape") { e.preventDefault(); done(false); }
      };
      document.addEventListener("keydown", overlay._escHandler, true);
      document.body.appendChild(overlay);
      setTimeout(() => confirmBtn.focus(), 0);
    });
  };

  window.alertModal = ({ title, message, okText, danger } = {}) => {
    return new Promise((resolve) => {
      const { overlay, confirmBtn } = buildPageModal({
        title, message, confirmText: okText, okOnly: true, danger,
      });
      const done = () => { closePageModal(overlay); resolve(); };
      confirmBtn.addEventListener("click", done);
      overlay.addEventListener("click", (e) => { if (e.target === overlay) done(); });
      overlay._escHandler = (e) => {
        if (e.key === "Escape" || e.key === "Enter") { e.preventDefault(); done(); }
      };
      document.addEventListener("keydown", overlay._escHandler, true);
      document.body.appendChild(overlay);
      setTimeout(() => confirmBtn.focus(), 0);
    });
  };
})();
