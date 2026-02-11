const apiFetch = async (url, options = {}) => {
  const response = await fetch(url, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 401) {
    window.location.href = "/login.html";
    return null;
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(detail.detail || "Request failed");
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
};

const getGuildId = () => {
  const params = new URLSearchParams(window.location.search);
  return params.get("guild_id");
};

const setActiveNav = (page) => {
  document.querySelectorAll("nav a").forEach((link) => {
    if (link.dataset.page === page) {
      link.classList.add("active");
    }
  });
};

const updateNavLinks = (guildId) => {
  if (!guildId) return;
  document.querySelectorAll("nav a").forEach((link) => {
    const url = new URL(link.getAttribute("href"), window.location.origin);
    url.searchParams.set("guild_id", guildId);
    link.setAttribute("href", url.toString().replace(window.location.origin, ""));
  });
};

const fillForm = (form, data) => {
  Object.entries(data).forEach(([key, value]) => {
    const field = form.elements.namedItem(key);
    if (!field) return;
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
    } else {
      field.value = value ?? "";
    }
  });
};

const formToPayload = (form) => {
  const payload = {};
  Array.from(form.elements).forEach((field) => {
    if (!field.name) return;
    if (field.type === "checkbox") {
      payload[field.name] = field.checked;
      return;
    }
    if (field.type === "number" || field.type === "range" || field.dataset.type === "number") {
      payload[field.name] = field.value === "" ? null : Number(field.value);
      return;
    }
    if (field.dataset.type === "float") {
      payload[field.name] = field.value === "" ? null : Number(field.value);
      return;
    }
    payload[field.name] = field.value;
  });
  return payload;
};

const setupRangeOutputs = () => {
  document.querySelectorAll("input[type='range']").forEach((range) => {
    const output = document.getElementById(range.dataset.output);
    if (!output) return;
    const update = () => {
      output.textContent = range.value;
    };
    range.addEventListener("input", update);
    update();
  });
};

const handleSettingsPage = async (page, endpoint) => {
  const guildId = getGuildId();
  if (!guildId) {
    window.location.href = "/servers.html";
    return;
  }
  updateNavLinks(guildId);
  setActiveNav(page);
  document.getElementById("guildIdLabel").textContent = `Guild: ${guildId}`;

  const form = document.getElementById("settingsForm");
  const resetButton = document.getElementById("resetSettings");

  const data = await apiFetch(`/api/guilds/${guildId}/${endpoint}`);
  if (data) {
    fillForm(form, data);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(form);
    await apiFetch(`/api/guilds/${guildId}/${endpoint}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    alert("Настройки сохранены");
  });

  resetButton.addEventListener("click", async () => {
    const confirmed = confirm("Сбросить настройки до значений по умолчанию?");
    if (!confirmed) return;
    const resetData = await apiFetch(`/api/guilds/${guildId}/${endpoint}/reset`, {
      method: "POST",
    });
    if (resetData) {
      fillForm(form, resetData);
    }
  });

  setupRangeOutputs();
};


const setupPvpPage = async () => {
  const guildId = getGuildId();
  if (!guildId) {
    window.location.href = "/servers.html";
    return;
  }
  updateNavLinks(guildId);
  setActiveNav("pvp");
  document.getElementById("guildIdLabel").textContent = `Guild: ${guildId}`;

  const pvpForm = document.getElementById("settingsForm");
  const resetButton = document.getElementById("resetSettings");
  const pvpData = await apiFetch(`/api/guilds/${guildId}/pvp`);
  if (pvpData) fillForm(pvpForm, pvpData);

  pvpForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(pvpForm);
    await apiFetch(`/api/guilds/${guildId}/pvp`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    alert("Настройки PvP сохранены");
  });

  resetButton.addEventListener("click", async () => {
    const confirmed = confirm("Сбросить PvP настройки до значений по умолчанию?");
    if (!confirmed) return;
    const resetData = await apiFetch(`/api/guilds/${guildId}/pvp/reset`, { method: "POST" });
    if (resetData) fillForm(pvpForm, resetData);
  });

  const seasonForm = document.getElementById("seasonSettingsForm");
  const seasonData = await apiFetch(`/api/guilds/${guildId}/pvp/season`);
  if (seasonData) {
    fillForm(seasonForm, seasonData);
    fillForm(seasonForm, seasonData.reward_roles || {});
  }

  seasonForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(seasonForm);
    payload.reward_roles = {
      top1_role_id: payload.top1_role_id,
      top3_role_id: payload.top3_role_id,
      top10_role_id: payload.top10_role_id,
    };
    delete payload.top1_role_id;
    delete payload.top3_role_id;
    delete payload.top10_role_id;

    await apiFetch(`/api/guilds/${guildId}/pvp/season`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    alert("Сезонные настройки PvP сохранены");
  });
};

const setupOverview = async () => {
  const guildId = getGuildId();
  if (!guildId) {
    window.location.href = "/servers.html";
    return;
  }
  updateNavLinks(guildId);
  setActiveNav("overview");
  document.getElementById("guildIdLabel").textContent = `Guild: ${guildId}`;

  const stats = await apiFetch(`/api/guilds/${guildId}/overview`);
  if (stats) {
    document.getElementById("statMembers").textContent = stats.member_count;
    document.getElementById("statBalance").textContent = stats.total_balance;
    document.getElementById("statLevel").textContent = stats.average_level.toFixed(1);
    document.getElementById("statWarnings").textContent = stats.total_warnings;
    document.getElementById("statShop").textContent = stats.total_shop_items;
  }

  const form = document.getElementById("settingsForm");
  const resetButton = document.getElementById("resetSettings");

  const settings = await apiFetch(`/api/guilds/${guildId}/settings`);
  if (settings) {
    fillForm(form, settings);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(form);
    await apiFetch(`/api/guilds/${guildId}/settings`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    alert("Настройки сервера сохранены");
  });

  resetButton.addEventListener("click", async () => {
    const confirmed = confirm("Сбросить настройки сервера?");
    if (!confirmed) return;
    const resetData = await apiFetch(`/api/guilds/${guildId}/settings`, {
      method: "PUT",
      body: JSON.stringify({
        server_rate: 1.0,
        currency_name: "Coins",
        prefix: "!",
        welcome_channel_id: null,
        moderation_enabled: true,
      }),
    });
    if (resetData) {
      fillForm(form, resetData);
    }
  });

  setupRangeOutputs();
};

const setupServers = async () => {
  const list = document.getElementById("guildList");
  const data = await apiFetch("/api/guilds");
  if (!data) return;
  list.innerHTML = "";
  data.guilds.forEach((guild) => {
    const item = document.createElement("div");
    item.className = "card";
    item.innerHTML = `
      <strong>${guild.name}</strong>
      <div>ID: ${guild.id}</div>
      <div class="footer-actions">
        <a href="/overview.html?guild_id=${guild.id}">Открыть</a>
      </div>
    `;
    list.appendChild(item);
  });
};

const setupShop = async () => {
  const guildId = getGuildId();
  if (!guildId) {
    window.location.href = "/servers.html";
    return;
  }
  updateNavLinks(guildId);
  setActiveNav("shop");
  document.getElementById("guildIdLabel").textContent = `Guild: ${guildId}`;

  const settingsForm = document.getElementById("settingsForm");
  const resetButton = document.getElementById("resetSettings");

  const settings = await apiFetch(`/api/guilds/${guildId}/shop`);
  if (settings) {
    fillForm(settingsForm, settings);
  }

  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(settingsForm);
    await apiFetch(`/api/guilds/${guildId}/shop`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    alert("Настройки магазина сохранены");
  });

  resetButton.addEventListener("click", async () => {
    const confirmed = confirm("Сбросить настройки магазина?");
    if (!confirmed) return;
    const resetData = await apiFetch(`/api/guilds/${guildId}/shop/reset`, {
      method: "POST",
    });
    if (resetData) {
      fillForm(settingsForm, resetData);
    }
  });

  const itemForm = document.getElementById("shopItemForm");
  const itemTableBody = document.getElementById("shopItemsBody");

  const renderItems = async () => {
    const items = await apiFetch(`/api/guilds/${guildId}/shop/items`);
    if (!items) return;
    itemTableBody.innerHTML = "";
    items.forEach((item) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${item.name}</td>
        <td>${item.base_price}</td>
        <td>${item.item_type}</td>
        <td>${item.is_active ? "Да" : "Нет"}</td>
        <td>
          <button class="secondary" data-id="${item.id}">Удалить</button>
        </td>
      `;
      row.querySelector("button").addEventListener("click", async () => {
        const confirmed = confirm("Удалить предмет магазина?");
        if (!confirmed) return;
        await apiFetch(`/api/guilds/${guildId}/shop/items/${item.id}`, {
          method: "DELETE",
        });
        renderItems();
      });
      itemTableBody.appendChild(row);
    });
  };

  itemForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(itemForm);
    await apiFetch(`/api/guilds/${guildId}/shop/items`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    itemForm.reset();
    renderItems();
  });

  renderItems();
  setupRangeOutputs();
};

const init = () => {
  const page = document.body.dataset.page;
  if (!page) return;

  if (page === "login") return;
  if (page === "servers") {
    setupServers();
    return;
  }
  if (page === "overview") {
    setupOverview();
    return;
  }
  if (page === "leveling") return handleSettingsPage("leveling", "leveling");
  if (page === "economy") return handleSettingsPage("economy", "economy");
  if (page === "gambling") return handleSettingsPage("gambling", "gambling");
  if (page === "pvp") return setupPvpPage();
  if (page === "logs") return handleSettingsPage("logs", "logs");
  if (page === "shop") return setupShop();
};

document.addEventListener("DOMContentLoaded", init);
