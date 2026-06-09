(function () {
  const csrfSafeFetch = (url, options = {}) => {
    const opts = Object.assign({ credentials: "same-origin" }, options);
    if (opts.headers === undefined) {
      opts.headers = { "Content-Type": "application/json" };
    } else if (typeof opts.headers.set === "function") {
      // Headers instance - nothing to normalize
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

  const state = { users: [], roles: [] };

  const populateRoleSelect = (selectEl) => {
    if (!selectEl) return;
    selectEl.innerHTML = "";
    state.roles.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.id;
      opt.textContent = `${r.name} (${r.code})`;
      selectEl.appendChild(opt);
    });
  };

  const renderRoles = () => {
    const container = document.getElementById("rolesContainer");
    if (!state.roles.length) {
      container.innerHTML = "<p class='muted'>暂无角色数据</p>";
      return;
    }
    container.innerHTML = "";
    state.roles.forEach((r) => {
      const card = document.createElement("article");
      card.className = "role-card";
      const heading = document.createElement("h3");
      heading.textContent = `${r.name} · ${r.code}`;
      card.appendChild(heading);
      const desc = document.createElement("p");
      desc.className = "muted small";
      desc.textContent = r.description || "";
      card.appendChild(desc);
      const permsTitle = document.createElement("p");
      permsTitle.className = "muted small";
      permsTitle.textContent = "权限:";
      card.appendChild(permsTitle);
      const list = document.createElement("div");
      list.className = "permission-chips";
      if (r.permissions.length === 0) {
        const span = document.createElement("span");
        span.className = "chip muted";
        span.textContent = "(无)";
        list.appendChild(span);
      } else if (r.permissions.includes("*")) {
        const span = document.createElement("span");
        span.className = "chip primary";
        span.textContent = "全部权限";
        list.appendChild(span);
      } else {
        r.permissions.forEach((p) => {
          const span = document.createElement("span");
          span.className = "chip";
          span.textContent = p;
          list.appendChild(span);
        });
      }
      card.appendChild(list);
      container.appendChild(card);
    });
  };

  const renderUsers = () => {
    const tbody = document.getElementById("usersTbody");
    if (!state.users.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">暂无用户</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    state.users.forEach((u) => {
      const tr = document.createElement("tr");

      const tdId = document.createElement("td");
      tdId.textContent = u.id;
      tr.appendChild(tdId);

      const tdUser = document.createElement("td");
      tdUser.textContent = u.username;
      tr.appendChild(tdUser);

      const tdName = document.createElement("td");
      tdName.textContent = u.full_name || "-";
      tr.appendChild(tdName);

      const tdRole = document.createElement("td");
      tdRole.textContent = `${u.role_name} (${u.role})`;
      tr.appendChild(tdRole);

      const tdStatus = document.createElement("td");
      const pill = document.createElement("span");
      pill.className = "status-pill " + (u.is_active ? "on" : "off");
      pill.textContent = u.is_active ? "启用" : "停用";
      tdStatus.appendChild(pill);
      tr.appendChild(tdStatus);

      const tdCreated = document.createElement("td");
      tdCreated.textContent = formatDate(u.created_at);
      tr.appendChild(tdCreated);

      const tdActions = document.createElement("td");
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "link-button";
      editBtn.textContent = "编辑";
      editBtn.addEventListener("click", () => openEditDialog(u));
      tdActions.appendChild(editBtn);

      tdActions.appendChild(document.createTextNode(" · "));

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "link-button";
      toggleBtn.textContent = u.is_active ? "停用" : "启用";
      toggleBtn.addEventListener("click", () => toggleActive(u));
      tdActions.appendChild(toggleBtn);

      tdActions.appendChild(document.createTextNode(" · "));

      const resetBtn = document.createElement("button");
      resetBtn.type = "button";
      resetBtn.className = "link-button";
      resetBtn.textContent = "重置密码";
      resetBtn.addEventListener("click", () => resetPassword(u));
      tdActions.appendChild(resetBtn);

      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
  };

  const loadAll = async () => {
    const [rolesRes, usersRes] = await Promise.all([
      csrfSafeFetch("/api/roles"),
      csrfSafeFetch("/api/users"),
    ]);
    if (!rolesRes.ok || !usersRes.ok) {
      if (rolesRes.status === 401 || usersRes.status === 401) {
        window.location.href = "/login";
        return;
      }
      if (rolesRes.status === 403 || usersRes.status === 403) {
        alert("当前角色无权访问用户管理");
        return;
      }
      alert("加载用户 / 角色数据失败");
      return;
    }
    state.roles = await rolesRes.json();
    state.users = await usersRes.json();
    populateRoleSelect(document.getElementById("cu_role_id"));
    populateRoleSelect(document.getElementById("eu_role_id"));
    renderRoles();
    renderUsers();
  };

  const createUser = async (event) => {
    event.preventDefault();
    const status = document.getElementById("createUserStatus");
    setStatus(status, "");
    const payload = {
      username: document.getElementById("cu_username").value.trim(),
      full_name: document.getElementById("cu_full_name").value.trim(),
      password: document.getElementById("cu_password").value,
      role_id: parseInt(document.getElementById("cu_role_id").value, 10),
      is_active: document.getElementById("cu_is_active").checked,
    };
    const res = await csrfSafeFetch("/api/users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setStatus(status, (body && body.detail) || "创建失败", true);
      return;
    }
    setStatus(status, "已创建", false);
    document.getElementById("createUserForm").reset();
    document.getElementById("cu_is_active").checked = true;
    await loadAll();
  };

  const openEditDialog = (user) => {
    document.getElementById("eu_id").value = user.id;
    document.getElementById("eu_username").value = user.username;
    document.getElementById("eu_full_name").value = user.full_name || "";
    document.getElementById("eu_role_id").value = String(user.role_id);
    document.getElementById("eu_is_active").checked = !!user.is_active;
    setStatus(document.getElementById("editUserStatus"), "");
    document.getElementById("editUserDialog").classList.remove("hidden");
  };

  const closeEditDialog = () => {
    document.getElementById("editUserDialog").classList.add("hidden");
  };

  const saveEdit = async (event) => {
    event.preventDefault();
    const id = document.getElementById("eu_id").value;
    const status = document.getElementById("editUserStatus");
    setStatus(status, "");
    const payload = {
      full_name: document.getElementById("eu_full_name").value,
      role_id: parseInt(document.getElementById("eu_role_id").value, 10),
      is_active: document.getElementById("eu_is_active").checked,
    };
    const res = await csrfSafeFetch(`/api/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setStatus(status, (body && body.detail) || "保存失败", true);
      return;
    }
    setStatus(status, "已保存", false);
    await loadAll();
    setTimeout(closeEditDialog, 600);
  };

  const toggleActive = async (user) => {
    const verb = user.is_active ? "停用" : "启用";
    if (!confirm(`确定要${verb}用户「${user.username}」吗?`)) return;
    const res = await csrfSafeFetch(`/api/users/${user.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: !user.is_active }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      alert((body && body.detail) || `${verb}失败`);
      return;
    }
    await loadAll();
  };

  const resetPassword = async (user) => {
    const choice = prompt(
      `重置用户「${user.username}」的密码。\n留空将自动生成 12 位随机密码,点击确定后会把新密码显示出来。\n也可以直接输入新密码。`,
      ""
    );
    if (choice === null) return;
    const body = choice === "" ? {} : { new_password: choice };
    const res = await csrfSafeFetch(`/api/users/${user.id}/reset-password`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      alert((errBody && errBody.detail) || "重置密码失败");
      return;
    }
    const data = await res.json();
    const verb = data.generated ? "已生成新密码,请妥善保存:" : "已重置为:";
    alert(`${verb}\n\n${data.new_password}`);
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("createUserForm").addEventListener("submit", createUser);
    document.getElementById("editUserForm").addEventListener("submit", saveEdit);
    document.getElementById("editUserClose").addEventListener("click", closeEditDialog);
    document.getElementById("editUserDialog").addEventListener("click", (e) => {
      if (e.target.id === "editUserDialog") closeEditDialog();
    });
    loadAll();
  });
})();
