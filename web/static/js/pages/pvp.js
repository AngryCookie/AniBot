import { apiFetch } from "../api.js";

let chart = null;
let tavernChart = null;
const num = (v) => new Intl.NumberFormat("ru-RU").format(Number(v) || 0);

const mapSeries = (series = [], key) => new Map((series || []).map((x) => [x.date, Number(x[key]) || 0]));

const drawFallback = (table, labels, volume, fees) => {
  const body = table?.querySelector("tbody");
  if (!body) return;
  body.innerHTML = labels.map((d, i) => `<tr><td>${d}</td><td>${num(volume[i])}</td><td>${num(fees[i])}</td></tr>`).join("");
  table.classList.remove("hidden");
};

const loadPvp = async (guildId, period) => {
  const [overview, timeseries] = await Promise.all([
    apiFetch(`/api/guilds/${guildId}/analytics/overview?period=${period}`),
    apiFetch(`/api/guilds/${guildId}/analytics/timeseries?period=${period}`),
  ]);
  const pvp = overview?.pvp || {};
  document.getElementById("pvpDuels").textContent = num(pvp.total_duels);
  document.getElementById("pvpVolume").textContent = num(pvp.total_volume);
  document.getElementById("pvpFees").textContent = num(pvp.total_fees_burned);

  const volumeMap = mapSeries(timeseries?.pvp?.daily_volume, "amount");
  const feesMap = mapSeries(timeseries?.pvp?.daily_fees_burned, "amount");
  const labels = [...new Set([...volumeMap.keys(), ...feesMap.keys()])].sort();
  const volume = labels.map((d) => volumeMap.get(d) || 0);
  const fees = labels.map((d) => feesMap.get(d) || 0);

  const canvas = document.getElementById("pvpChart");
  const fallback = document.getElementById("pvpFallback");
  if (!canvas || !window.Chart) {
    drawFallback(fallback, labels, volume, fees);
    return;
  }

  try {
    fallback?.classList.add("hidden");
    chart?.destroy();
    chart = new window.Chart(canvas, {
      type: "line",
      data: { labels, datasets: [
        { label: "Объем", data: volume, borderColor: "#7da8ff", tension: 0.3 },
        { label: "Сожжённые комиссии", data: fees, borderColor: "#f56c6c", tension: 0.3 },
      ] },
      options: { responsive: true, maintainAspectRatio: false },
    });
  } catch {
    drawFallback(fallback, labels, volume, fees);
  }
};

const formToPayload = (form) => {
  const fd = new FormData(form);
  const out = {};
  for (const [k, v] of fd.entries()) out[k] = v;
  for (const el of form.querySelectorAll('input[type="checkbox"]')) out[el.name] = el.checked;
  ["value", "duration_seconds", "price"].forEach((k) => { if (k in out) out[k] = Number(out[k] || 0); });
  return out;
};

const renderTavernItems = (items = []) => {
  const body = document.getElementById("tavernTopItemsBody");
  if (!body) return;
  body.innerHTML = (items || []).map((x) => `<tr><td>${x.name}</td><td>${x.slot}</td><td>${num(x.purchases)}</td><td>${num(x.unique_buyers)}</td><td>${num(x.spent)}</td><td>${num(x.active_now)}</td></tr>`).join("");
};

const loadTavernAnalytics = async (guildId, days) => {
  const [overview, items, impact] = await Promise.all([
    apiFetch(`/api/guilds/${guildId}/pvp/tavern/analytics/overview?days=${days}`),
    apiFetch(`/api/guilds/${guildId}/pvp/tavern/analytics/items?days=${days}`),
    apiFetch(`/api/guilds/${guildId}/pvp/tavern/analytics/impact?days=${days}`),
  ]);
  const kpis = overview?.kpis || {};
  document.getElementById("tavernActiveLoadouts").textContent = num(kpis.active_loadouts);
  document.getElementById("tavernPurchases").textContent = num(kpis.purchases);
  document.getElementById("tavernBuyers").textContent = num(kpis.unique_buyers);
  document.getElementById("tavernSpent").textContent = num(kpis.total_spent);

  const labels = (overview?.timeseries || []).map((x) => x.day);
  const purchases = (overview?.timeseries || []).map((x) => Number(x.purchases) || 0);
  const spent = (overview?.timeseries || []).map((x) => Number(x.spent) || 0);
  const canvas = document.getElementById("tavernChart");
  if (canvas && window.Chart) {
    tavernChart?.destroy();
    tavernChart = new window.Chart(canvas, {
      type: "line",
      data: { labels, datasets: [
        { label: "Покупки", data: purchases, borderColor: "#7da8ff", tension: 0.3 },
        { label: "Потрачено", data: spent, borderColor: "#6cf5a5", tension: 0.3 },
      ] },
      options: { responsive: true, maintainAspectRatio: false },
    });
  }

  renderTavernItems(items || []);
  const impactEl = document.getElementById("tavernImpact");
  if (impactEl) {
    impactEl.textContent = impact?.available
      ? `Влияние баффов: WR buffed ${(Number(impact.winrate_buffed || 0) * 100).toFixed(1)}% vs non-buffed ${(Number(impact.winrate_non_buffed || 0) * 100).toFixed(1)}% • ΔELO ${impact.avg_elo_delta_buffed} / ${impact.avg_elo_delta_non_buffed}`
      : (impact?.message || "Влияние баффов недоступно");
  }
};

const initTavernAdmin = async (guildId) => {
  const settingsForm = document.getElementById("pvpTavernSettingsForm");
  const itemForm = document.getElementById("tavernItemForm");
  const body = document.getElementById("tavernItemsBody");
  if (!settingsForm || !itemForm || !body) return;

  const loadSettings = async () => {
    const data = await apiFetch(`/api/guilds/${guildId}/pvp/tavern`);
    if (!data) return;
    settingsForm.querySelector('[name="enabled"]').checked = !!data.enabled;
    settingsForm.querySelector('[name="season_reset_clears_loadout"]').checked = !!data.season_reset_clears_loadout;
    settingsForm.querySelector('[name="stacking_rule"]').value = data.stacking_rule || "max";
    const caps = data.max_bonus_caps || {};
    ["attack_bonus_percent", "defense_bonus_percent", "crit_chance_percent", "dodge_chance_percent", "elo_protection_percent", "win_bonus_elo_flat"].forEach((k) => {
      const field = settingsForm.querySelector(`[name="${k}"]`);
      if (field) field.value = Number(caps[k] || 0);
    });
  };

  const loadItems = async () => {
    const items = await apiFetch(`/api/guilds/${guildId}/pvp/tavern/items`);
    body.innerHTML = "";
    (items || []).forEach((item) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${item.id}</td><td>${item.name}</td><td>${item.slot_type}</td><td>${item.effect_type}</td><td>${item.value}</td><td>${item.price}</td><td>${item.enabled ? "Да" : "Нет"}</td><td><button class="secondary" data-id="${item.id}">Удалить</button></td>`;
      tr.querySelector("button")?.addEventListener("click", async () => {
        await apiFetch(`/api/guilds/${guildId}/pvp/tavern/items/${item.id}`, { method: "DELETE" });
        await loadItems();
      });
      body.appendChild(tr);
    });
  };

  settingsForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = formToPayload(settingsForm);
    payload.max_bonus_caps = {
      attack_bonus_percent: Number(payload.attack_bonus_percent || 0),
      defense_bonus_percent: Number(payload.defense_bonus_percent || 0),
      crit_chance_percent: Number(payload.crit_chance_percent || 0),
      dodge_chance_percent: Number(payload.dodge_chance_percent || 0),
      elo_protection_percent: Number(payload.elo_protection_percent || 0),
      win_bonus_elo_flat: Number(payload.win_bonus_elo_flat || 0),
    };
    delete payload.attack_bonus_percent;
    delete payload.defense_bonus_percent;
    delete payload.crit_chance_percent;
    delete payload.dodge_chance_percent;
    delete payload.elo_protection_percent;
    delete payload.win_bonus_elo_flat;
    await apiFetch(`/api/guilds/${guildId}/pvp/tavern`, { method: "PUT", body: JSON.stringify(payload) });
  });

  itemForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await apiFetch(`/api/guilds/${guildId}/pvp/tavern/items`, { method: "POST", body: JSON.stringify(formToPayload(itemForm)) });
    itemForm.reset();
    await loadItems();
  });

  let tavernPeriod = 7;
  const tavernButtons = document.querySelectorAll("#tavernPeriod [data-period]");
  tavernButtons.forEach((button) => button.addEventListener("click", async () => {
    tavernPeriod = Number(button.dataset.period || 7);
    tavernButtons.forEach((b) => b.classList.toggle("is-active", b === button));
    await loadTavernAnalytics(guildId, tavernPeriod);
  }));

  await loadSettings();
  await loadItems();
  await loadTavernAnalytics(guildId, tavernPeriod);
};

export const initPvp = async (guildId) => {
  let period = 7;
  const buttons = document.querySelectorAll("#pvpPeriod [data-period]");
  const refresh = async () => loadPvp(guildId, period);
  buttons.forEach((button) => button.addEventListener("click", async () => {
    period = Number(button.dataset.period || 7);
    buttons.forEach((b) => b.classList.toggle("is-active", b === button));
    await refresh();
  }));
  await refresh();
  await initTavernAdmin(guildId);
};
