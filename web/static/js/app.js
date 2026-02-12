import { apiFetch, setApiErrorHandler } from "./api.js";
import { confirmModal, setLoading, showToast, validateForm, withErrorBoundary } from "./ui.js";
import { initOverview } from "./pages/overview.js";
import { initLeveling } from "./pages/leveling.js";
import { initEconomy } from "./pages/economy.js";
import { initEconomyAnalytics } from "./pages/economy_analytics.js";
import { initEconomyRecommendations } from "./pages/economy_recommendations.js";
import { initCommunityGoal } from "./pages/community_goal.js";
import { initMonthlyGoals } from "./pages/monthly_goals.js";
import { initReferralPromo } from "./pages/referral_promo.js";
import { initGrowth } from "./pages/growth.js";
import { initBetting } from "./pages/betting.js";
import { initPvp } from "./pages/pvp.js";
import { initReports } from "./pages/reports.js";
import { initRituals } from "./pages/rituals.js";
import { initPresence } from "./pages/presence.js";

const appState = { guildId: null, currentRoute: null };

const routes = {
  overview: { title: "Overview", page: "/static/pages/overview.html", init: () => initOverview(appState.guildId) },
  economy: { title: "Economy", page: "/static/pages/economy.html", init: () => initEconomy(appState.guildId) },
  shop: { title: "Shop", page: "/static/pages/shop.html", init: initShop },
  jobs: { title: "Jobs", page: "/static/pages/jobs.html", init: initJobs },
  betting: { title: "Betting", page: "/static/pages/betting.html", init: () => initBetting(appState.guildId) },
  pvp: { title: "PvP", page: "/static/pages/pvp.html", init: () => initPvp(appState.guildId) },
  growth: { title: "Growth", page: "/static/pages/growth.html", init: () => initGrowth(appState.guildId) },
  logs: { title: "Logs", page: "/static/pages/logs.html", init: () => initSettingsPage("logs") },
  passport: { title: "Passport", page: "/static/pages/passport.html", init: () => initSettingsPage("passport") },
  "feature-flags": { title: "Feature Flags", page: "/static/pages/feature-flags.html" },
  history: { title: "History", page: "/static/pages/history.html" },
  leveling: { title: "Leveling", page: "/static/pages/leveling.html", init: () => initLeveling(appState.guildId) },
  "economy-analytics": { title: "Economy Analytics", page: "/static/pages/economy-analytics.html", init: () => initEconomyAnalytics(appState.guildId) },
  "economy-recommendations": { title: "Economy Recommendations", page: "/static/pages/economy-recommendations.html", init: () => initEconomyRecommendations(appState.guildId) },
  gambling: { title: "Gambling", page: "/static/pages/gambling.html", init: () => initSettingsPage("gambling") },
  "community-goal": { title: "Community Goal", page: "/static/pages/community-goal.html", init: () => initCommunityGoal(appState.guildId) },
  "monthly-goals": { title: "Monthly Goals", page: "/static/pages/monthly-goals.html", init: () => initMonthlyGoals(appState.guildId) },
  "referral-promo": { title: "Referral & Promo", page: "/static/pages/referral-promo.html", init: () => initReferralPromo(appState.guildId) },
  reports: { title: "Reports", page: "/static/pages/reports.html", init: () => initReports(appState.guildId) },
  rituals: { title: "Rituals", page: "/static/pages/rituals.html", init: () => initRituals(appState.guildId) },
  presence: { title: "Presence", page: "/static/pages/presence.html", init: initPresence },
  "word-emoji-stats": { title: "Word/Emoji Stats", page: "/static/pages/word-emoji-stats.html", init: () => initWordEmojiStats(appState.guildId) },
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
  passport: {
    enabled: "Включает slash-команду /passport на сервере.",
    hide_balance_for_others: "Скрывает баланс при просмотре чужого профиля.",
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

const initWordEmojiStats = async (guildId) => {
  const form = document.querySelector("form[data-endpoint='word-emoji-stats']");
  if (!guildId || !form) return;
  const data = await apiFetch(`/api/guilds/${guildId}/word-emoji-stats`);
  form.elements.namedItem("enabled").checked = Boolean(data.enabled);
  form.elements.namedItem("min_token_length").value = data.min_token_length ?? 3;
  form.elements.namedItem("max_tokens_per_message").value = data.max_tokens_per_message ?? 20;
  form.elements.namedItem("ignore_bots").checked = Boolean(data.ignore_bots);
  form.elements.namedItem("retention_days").value = data.retention_days ?? 400;
  form.elements.namedItem("ignore_channels").value = Array.isArray(data.ignore_channels) ? data.ignore_channels.join(",") : "";

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const raw = form.elements.namedItem("ignore_channels").value || "";
    const ignore_channels = raw
      .split(",")
      .map((part) => part.trim())
      .filter((part) => part && !Number.isNaN(Number(part)))
      .map((part) => Number(part));
    await apiFetch(`/api/guilds/${guildId}/word-emoji-stats`, {
      method: "PUT",
      body: JSON.stringify({
        enabled: form.elements.namedItem("enabled").checked,
        min_token_length: Number(form.elements.namedItem("min_token_length").value || 3),
        max_tokens_per_message: Number(form.elements.namedItem("max_tokens_per_message").value || 20),
        ignore_bots: form.elements.namedItem("ignore_bots").checked,
        ignore_channels,
        retention_days: Number(form.elements.namedItem("retention_days").value || 400),
      }),
    });
    showToast("Настройки word/emoji stats сохранены", "success");
  });
};

const initShop = async () => {
  await initSettingsPage("shop");
  const guildId = appState.guildId;
  const itemForm = document.getElementById("shopItemForm");
  const itemTableBody = document.getElementById("shopItemsBody");
  const itemType = document.getElementById("shopItemType");
  const buffFields = document.getElementById("buffFields");
  if (!guildId || !itemForm || !itemTableBody) return;

  const toggleBuffFields = () => {
    const isBuff = itemType?.value === "buff";
    if (buffFields) buffFields.style.display = isBuff ? "block" : "none";
  };
  itemType?.addEventListener("change", toggleBuffFields);
  toggleBuffFields();

  const toItemPayload = (form) => {
    const payload = formToPayload(form);
    const isBuff = payload.item_type === "buff";
    const durationHours = Number(payload.duration_hours || 0);
    payload.duration_seconds = isBuff && durationHours > 0 ? durationHours * 3600 : null;
    payload.max_active_per_user = payload.max_active_per_user ? Number(payload.max_active_per_user) : 1;
    payload.purchase_limit_per_user = payload.purchase_limit_per_user ? Number(payload.purchase_limit_per_user) : null;
    payload.purchase_limit_total = payload.purchase_limit_total ? Number(payload.purchase_limit_total) : null;
    payload.buff_json = isBuff
      ? {
          buff_type: payload.buff_type || "jobs_bonus",
          value_percent: Number(payload.value_percent || 0),
        }
      : null;
    delete payload.buff_type;
    delete payload.value_percent;
    delete payload.duration_hours;
    return payload;
  };

  const renderItems = async () => {
    const items = await apiFetch(`/api/guilds/${guildId}/shop/items`);
    itemTableBody.innerHTML = "";
    items.forEach((item) => {
      const row = document.createElement("tr");
      const buffText = item.item_type === "buff" && item.buff_json
        ? `${item.buff_json.buff_type || ""}: +${Number(item.buff_json.value_percent || 0)}% / ${Math.round((item.duration_seconds || 0) / 3600)}ч`
        : "—";
      row.innerHTML = `<td>${item.name}</td><td>${item.base_price}</td><td>${item.item_type}</td><td>${buffText}</td><td>${item.is_active && item.enabled ? "Да" : "Нет"}</td><td><button class="secondary" data-id="${item.id}">Удалить</button></td>`;
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
    await apiFetch(`/api/guilds/${guildId}/shop/items`, { method: "POST", body: JSON.stringify(toItemPayload(itemForm)) });
    itemForm.reset();
    toggleBuffFields();
    setLoading(submitButton, false);
    showToast("Товар добавлен", "success");
    await renderItems();
  });

  await renderItems();
};




const initJobs = async () => {
  const guildId = appState.guildId;
  const form = document.getElementById("jobsForm");
  const body = document.getElementById("jobsBody");
  if (!guildId || !form || !body) return;

  const payloadFromForm = () => ({
    name: form.elements.namedItem("name").value?.trim(),
    description: form.elements.namedItem("description").value || "",
    cooldown_seconds: Number(form.elements.namedItem("cooldown_seconds").value || 3600),
    reward_min: Number(form.elements.namedItem("reward_min").value || 0),
    reward_max: Number(form.elements.namedItem("reward_max").value || 0),
    fail_chance: Number(form.elements.namedItem("fail_chance").value || 0),
    penalty_min: Number(form.elements.namedItem("penalty_min").value || 0),
    penalty_max: Number(form.elements.namedItem("penalty_max").value || 0),
    weight: Number(form.elements.namedItem("weight").value || 1),
    enabled: form.elements.namedItem("enabled").checked,
  });

  const render = async () => {
    const jobs = await apiFetch(`/api/guilds/${guildId}/jobs`);
    body.innerHTML = "";
    jobs.forEach((job) => {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${job.name}</td><td>cd ${job.cooldown_seconds}с • reward ${job.reward_min}-${job.reward_max} • fail ${Math.round((job.fail_chance || 0) * 100)}% • penalty ${job.penalty_min}-${job.penalty_max}</td><td>${job.enabled ? "Вкл" : "Выкл"}</td><td><button class="secondary" data-action="toggle">${job.enabled ? "Отключить" : "Включить"}</button> <button class="danger" data-action="delete">Удалить</button></td>`;
      row.querySelector('[data-action="toggle"]')?.addEventListener('click', async () => {
        await apiFetch(`/api/guilds/${guildId}/jobs/${job.id}`, { method: 'PUT', body: JSON.stringify({ ...job, enabled: !job.enabled }) });
        await render();
      });
      row.querySelector('[data-action="delete"]')?.addEventListener('click', async () => {
        if (!(await confirmModal("Удалить работу?", `Работа «${job.name}» будет удалена.`))) return;
        await apiFetch(`/api/guilds/${guildId}/jobs/${job.id}`, { method: 'DELETE' });
        await render();
      });
      body.appendChild(row);
    });
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = payloadFromForm();
    if (payload.reward_min > payload.reward_max || payload.penalty_min > payload.penalty_max) {
      showToast("Проверьте диапазоны min/max", "error");
      return;
    }
    await apiFetch(`/api/guilds/${guildId}/jobs`, { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    showToast("Работа добавлена", "success");
    await render();
  });

  await render();
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
