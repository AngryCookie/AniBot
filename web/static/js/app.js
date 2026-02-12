import { apiFetch, setApiErrorHandler } from "./api.js";
import { confirmModal, setLoading, showToast, validateForm, withErrorBoundary } from "./ui.js";
import { initOverview } from "./pages/overview.js";
import { initLeveling } from "./pages/leveling.js";
import { initEconomy } from "./pages/economy.js";
import { initEconomyAnalytics } from "./pages/economy_analytics.js";
import { initCommunityGoal } from "./pages/community_goal.js";
import { initMonthlyGoals } from "./pages/monthly_goals.js";
import { initReferralPromo } from "./pages/referral_promo.js";
import { initGrowth } from "./pages/growth.js";
import { initBetting } from "./pages/betting.js";
import { initPvp } from "./pages/pvp.js";
import { initReports } from "./pages/reports.js";

const appState = { guildId: null, currentRoute: null };

const routes = {
  overview: { title: "Overview", page: "/static/pages/overview.html", init: () => initOverview(appState.guildId) },
  economy: { title: "Economy", page: "/static/pages/economy.html", init: () => initEconomy(appState.guildId) },
  shop: { title: "Shop", page: "/static/pages/shop.html", init: initShop },
  betting: { title: "Betting", page: "/static/pages/betting.html", init: () => initBetting(appState.guildId) },
  pvp: { title: "PvP", page: "/static/pages/pvp.html", init: () => initPvp(appState.guildId) },
  growth: { title: "Growth", page: "/static/pages/growth.html", init: () => initGrowth(appState.guildId) },
  logs: { title: "Logs", page: "/static/pages/logs.html", init: () => initSettingsPage("logs") },
  "feature-flags": { title: "Feature Flags", page: "/static/pages/feature-flags.html" },
  history: { title: "History", page: "/static/pages/history.html" },
  leveling: { title: "Leveling", page: "/static/pages/leveling.html", init: () => initLeveling(appState.guildId) },
  "economy-analytics": { title: "Economy Analytics", page: "/static/pages/economy-analytics.html", init: () => initEconomyAnalytics(appState.guildId) },
  gambling: { title: "Gambling", page: "/static/pages/gambling.html", init: () => initSettingsPage("gambling") },
  "community-goal": { title: "Community Goal", page: "/static/pages/community-goal.html", init: () => initCommunityGoal(appState.guildId) },
  "monthly-goals": { title: "Monthly Goals", page: "/static/pages/monthly-goals.html", init: () => initMonthlyGoals(appState.guildId) },
  "referral-promo": { title: "Referral & Promo", page: "/static/pages/referral-promo.html", init: () => initReferralPromo(appState.guildId) },
  reports: { title: "Reports", page: "/static/pages/reports.html", init: () => initReports(appState.guildId) },
};

let pageContent; let pageTitle; let pageError; let pageLoading;

const fieldHelpText = {
  gambling: {
    enabled: "Включает/отключает все игровые команды ставок.",
    min_bet: "Минимальная сумма одной ставки.",
    max_bet: "Максимальная сумма одной ставки.",
    house_edge_percent: "Комиссия бота с выигрышей, в процентах.",
    streak_bonus: "Бонус за серии побед в игровых режимах.",
  },
  logs: {
    enabled: "Включает запись событий в канал аудита.",
    log_channel_id: "ID канала, куда отправляются логи.",
    log_moderation: "Логировать модерацию и предупреждения.",
    log_economy: "Логировать экономические транзакции.",
    log_gambling: "Логировать игровые ставки и результаты.",
  },
  shop: {
    enabled: "Включает модуль магазина.",
    show_out_of_stock: "Показывает товары без наличия в интерфейсе.",
    highlight_discounts: "Подсвечивает позиции со скидкой.",
  },
  pvp: {
    enabled: "Включает дуэли между участниками.",
    min_bet: "Минимальная ставка на дуэль.",
    max_bet: "Максимальная ставка на дуэль.",
    cooldown_seconds: "Пауза между дуэлями одного игрока.",
    max_active_duels_per_user: "Лимит одновременных активных дуэлей.",
    level_influence_percent: "Влияние уровня игрока на исход дуэли.",
  },
};

const getRouteFromHash = () => window.location.hash.replace(/^#\/?/, "") || "overview";

const setError = (message) => {
  if (!pageError) return;
  pageError.classList.toggle("hidden", !message);
  pageError.textContent = message || "";
};

const setActiveNav = (route) => {
  document.querySelectorAll(".sidebar nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === route);
  });
};

const requireGuildId = () => {
  const guildId = new URLSearchParams(window.location.search).get("guild_id");
  if (!guildId) {
    window.location.href = "/servers.html";
    return null;
  }
  appState.guildId = guildId;
  const selector = document.getElementById("guildSelector");
  if (selector) {
    selector.innerHTML = `<option selected>${guildId}</option>`;
  }
  return guildId;
};

const fillForm = (form, data) => {
  Object.entries(data || {}).forEach(([key, value]) => {
    const field = form.elements.namedItem(key);
    if (!field) return;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value ?? "";
  });
};

const formToPayload = (form) => {
  const payload = {};
  Array.from(form.elements).forEach((field) => {
    if (!field.name) return;
    if (field.type === "checkbox") payload[field.name] = field.checked;
    else if (field.type === "number" || field.dataset.type === "number" || field.dataset.type === "float") {
      payload[field.name] = field.value === "" ? null : Number(field.value);
    } else payload[field.name] = field.value;
  });
  return payload;
};

const attachFieldHints = (form, endpoint) => {
  const hints = fieldHelpText[endpoint] || {};
  Object.entries(hints).forEach(([name, text]) => {
    const field = form.elements.namedItem(name);
    if (!field || field.closest(".setting")?.querySelector(".field-hint")) return;
    const host = field.closest("label");
    if (!host || host.querySelector(`[data-help-for='${name}']`)) return;
    const hint = document.createElement("p");
    hint.className = "field-hint";
    hint.dataset.helpFor = name;
    hint.textContent = text;
    host.appendChild(hint);
  });
};

const initSettingsPage = async (endpoint) => {
  const guildId = appState.guildId;
  const form = document.querySelector("form[data-endpoint]");
  if (!guildId || !form) return;

  attachFieldHints(form, endpoint);
  const saveButton = form.querySelector("button[type='submit']");
  const resetButton = form.querySelector("[data-action='reset']");
  const successMessage = form.dataset.successMessage || "Настройки сохранены";

  fillForm(form, await apiFetch(`/api/guilds/${guildId}/${endpoint}`));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateForm(form)) return;
    setLoading(saveButton, true);
    await withErrorBoundary(async () => {
      await apiFetch(`/api/guilds/${guildId}/${endpoint}`, { method: "PUT", body: JSON.stringify(formToPayload(form)) });
      showToast(successMessage, "success");
    }, (msg) => showToast(msg, "error"));
    setLoading(saveButton, false);
  });

  if (resetButton) {
    resetButton.addEventListener("click", async () => {
      const confirmed = await confirmModal("Сбросить настройки?", "Это действие вернёт значения по умолчанию.");
      if (!confirmed) return;
      await withErrorBoundary(async () => {
        fillForm(form, await apiFetch(`/api/guilds/${guildId}/${endpoint}/reset`, { method: "POST" }));
        showToast("Настройки сброшены", "success");
      }, (msg) => showToast(msg, "error"));
    });
  }
};

const initShop = async () => {
  await initSettingsPage("shop");
  const guildId = appState.guildId;
  const itemForm = document.getElementById("shopItemForm");
  const itemTableBody = document.getElementById("shopItemsBody");
  if (!guildId || !itemForm || !itemTableBody) return;

  const renderItems = async () => {
    const items = await apiFetch(`/api/guilds/${guildId}/shop/items`);
    itemTableBody.innerHTML = "";
    items.forEach((item) => {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${item.name}</td><td>${item.base_price}</td><td>${item.item_type}</td><td>${item.is_active ? "Да" : "Нет"}</td><td><button class="secondary" data-id="${item.id}">Удалить</button></td>`;
      row.querySelector("button")?.addEventListener("click", async () => {
        if (!(await confirmModal("Удалить предмет?", `Предмет «${item.name}» будет удалён безвозвратно.`))) return;
        await apiFetch(`/api/guilds/${guildId}/shop/items/${item.id}`, { method: "DELETE" });
        showToast("Предмет удалён", "success");
        await renderItems();
      });
      itemTableBody.appendChild(row);
    });
  };

  itemForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateForm(itemForm)) return;
    const submitButton = itemForm.querySelector("button[type='submit']");
    setLoading(submitButton, true);
    await apiFetch(`/api/guilds/${guildId}/shop/items`, { method: "POST", body: JSON.stringify(formToPayload(itemForm)) });
    itemForm.reset();
    setLoading(submitButton, false);
    showToast("Товар добавлен", "success");
    await renderItems();
  });

  await renderItems();
};

const loadRoute = async () => {
  const routeKey = routes[getRouteFromHash()] ? getRouteFromHash() : "overview";
  const route = routes[routeKey];
  appState.currentRoute = routeKey;
  setActiveNav(routeKey);
  pageTitle.textContent = route.title;
  document.title = `AniBot Admin - ${route.title}`;
  setError(null);
  setLoading(pageLoading, true);

  await withErrorBoundary(async () => {
    const response = await fetch(route.page, { cache: "no-store" });
    if (!response.ok) throw new Error("Не удалось загрузить страницу");
    pageContent.innerHTML = await response.text();
    if (route.init) await route.init();
  }, (message) => setError(message));

  setLoading(pageLoading, false);
};

const loadLayout = async () => {
  const mount = document.getElementById("layoutMount");
  if (!mount) return false;
  const response = await fetch("/static/_layout.html", { cache: "no-store" });
  if (!response.ok) return false;
  mount.innerHTML = await response.text();
  pageContent = document.getElementById("pageContent");
  pageTitle = document.getElementById("pageTitle");
  pageError = document.getElementById("pageError");
  pageLoading = document.getElementById("pageLoading");
  return true;
};

const initApp = async () => {
  if (!(await loadLayout())) return;
  setApiErrorHandler((message) => setError(message));
  if (!requireGuildId()) return;
  await loadRoute();
  window.addEventListener("hashchange", loadRoute);
};

document.addEventListener("DOMContentLoaded", () => {
  withErrorBoundary(initApp, (message) => {
    document.body.innerHTML = `<div class='page-content'><div class='alert error'>${message}</div></div>`;
  });
});
