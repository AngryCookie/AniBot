import { apiFetch } from "./api.js";
import { initOverview } from "./pages/overview.js";
import { initLeveling } from "./pages/leveling.js";
import { initEconomy } from "./pages/economy.js";
import { initEconomyAnalytics } from "./pages/economy_analytics.js";
import { initCommunityGoal } from "./pages/community_goal.js";
import { initMonthlyGoals } from "./pages/monthly_goals.js";

const appState = {
  guildId: null,
  currentRoute: null,
};

const routes = {
  overview: {
    title: "Overview",
    page: "/static/pages/overview.html",
    init: () => initOverview(appState.guildId),
  },
  leveling: {
    title: "Leveling",
    page: "/static/pages/leveling.html",
    init: () => initLeveling(appState.guildId),
  },
  economy: {
    title: "Economy",
    page: "/static/pages/economy.html",
    init: () => initEconomy(appState.guildId),
  },
  "economy-analytics": {
    title: "Economy Analytics",
    page: "/static/pages/economy-analytics.html",
    init: () => initEconomyAnalytics(appState.guildId),
  },
  gambling: {
    title: "Gambling",
    page: "/static/pages/gambling.html",
    init: () => initSettingsPage("gambling"),
  },
  shop: {
    title: "Shop",
    page: "/static/pages/shop.html",
    init: initShop,
  },
  logs: {
    title: "Logs",
    page: "/static/pages/logs.html",
    init: () => initSettingsPage("logs"),
  },
  "community-goal": {
    title: "Community Goal",
    page: "/static/pages/community-goal.html",
    init: () => initCommunityGoal(appState.guildId),
  },
  "monthly-goals": {
    title: "Monthly Goals",
    page: "/static/pages/monthly-goals.html",
    init: () => initMonthlyGoals(appState.guildId),
  },
  "feature-flags": {
    title: "Feature Flags",
    page: "/static/pages/feature-flags.html",
  },
  history: {
    title: "History",
    page: "/static/pages/history.html",
  },
};

const pageContent = document.getElementById("pageContent");
const pageTitle = document.getElementById("pageTitle");
const pageError = document.getElementById("pageError");
const pageLoading = document.getElementById("pageLoading");
const guildIdLabel = document.getElementById("guildIdLabel");

const setLoading = (isLoading) => {
  if (!pageLoading) return;
  pageLoading.classList.toggle("hidden", !isLoading);
};

const setError = (message) => {
  if (!pageError) return;
  if (!message) {
    pageError.classList.add("hidden");
    pageError.textContent = "";
    return;
  }
  pageError.classList.remove("hidden");
  pageError.textContent = message;
};

const getRouteFromHash = () => {
  const raw = window.location.hash.replace(/^#\/?/, "");
  if (!raw) return "overview";
  return raw;
};

const setActiveNav = (route) => {
  document.querySelectorAll(".sidebar nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === route);
  });
};

const requireGuildId = () => {
  const params = new URLSearchParams(window.location.search);
  const guildId = params.get("guild_id");
  if (!guildId) {
    window.location.href = "/servers.html";
    return null;
  }
  appState.guildId = guildId;
  if (guildIdLabel) {
    guildIdLabel.textContent = `Guild: ${guildId}`;
  }
  return guildId;
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

const initSettingsPage = async (endpoint) => {
  const guildId = appState.guildId;
  if (!guildId) return;

  const form = document.querySelector("form[data-endpoint]");
  if (!form) return;

  const resetButton = form.querySelector("[data-action='reset']");
  const successMessage = form.dataset.successMessage || "Настройки сохранены";

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
    alert(successMessage);
  });

  if (resetButton) {
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
  }

  setupRangeOutputs();
};

const initShop = async () => {
  await initSettingsPage("shop");

  const guildId = appState.guildId;
  if (!guildId) return;

  const itemForm = document.getElementById("shopItemForm");
  const itemTableBody = document.getElementById("shopItemsBody");
  if (!itemForm || !itemTableBody) return;

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
        await apiFetch(`/api/guilds/${guildId}/shop/items/${item.id}`,
          { method: "DELETE" });
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
};

const loadRoute = async () => {
  const rawRouteKey = getRouteFromHash();
  const routeKey = routes[rawRouteKey] ? rawRouteKey : "overview";
  const route = routes[routeKey];
  appState.currentRoute = routeKey;
  setActiveNav(routeKey);

  pageTitle.textContent = route.title;
  document.title = `AniBot Admin - ${route.title}`;
  setError(null);
  setLoading(true);

  try {
    const response = await fetch(route.page, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Не удалось загрузить страницу");
    }
    const html = await response.text();
    pageContent.innerHTML = html;
    if (route.init) {
      await route.init();
    }
  } catch (error) {
    setError(error.message || "Ошибка загрузки");
  } finally {
    setLoading(false);
  }
};

const initApp = () => {
  if (!requireGuildId()) return;
  setError(null);
  loadRoute();
  window.addEventListener("hashchange", loadRoute);
};

document.addEventListener("DOMContentLoaded", initApp);
