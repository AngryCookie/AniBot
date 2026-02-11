import { apiFetch } from "../api.js";

let chart = null;
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
};
