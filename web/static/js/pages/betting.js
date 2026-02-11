import { apiFetch } from "../api.js";

let chart = null;
const fmt = (v) => new Intl.NumberFormat("ru-RU").format(Number(v) || 0);

const seriesMap = (series = [], key) => new Map((series || []).map((x) => [x.date, Number(x[key]) || 0]));

const renderFallback = (table, labels, volumes, payouts) => {
  const body = table?.querySelector("tbody");
  if (!body) return;
  body.innerHTML = labels.map((d, i) => `<tr><td>${d}</td><td>${fmt(volumes[i])}</td><td>${fmt(payouts[i])}</td></tr>`).join("");
  table.classList.remove("hidden");
};

const render = async (guildId, period) => {
  const timeseries = await apiFetch(`/api/guilds/${guildId}/analytics/timeseries?period=${period}`);
  const volumeMap = seriesMap(timeseries?.betting?.daily_volume, "amount");
  const houseMap = seriesMap(timeseries?.betting?.daily_house_net, "amount");
  const labels = [...new Set([...volumeMap.keys(), ...houseMap.keys()])].sort();
  const volumes = labels.map((d) => volumeMap.get(d) || 0);
  const payouts = labels.map((d) => Math.max(0, (volumeMap.get(d) || 0) - (houseMap.get(d) || 0)));

  const canvas = document.getElementById("bettingChart");
  const fallback = document.getElementById("bettingFallback");
  if (!canvas || !window.Chart) {
    renderFallback(fallback, labels, volumes, payouts);
    return;
  }

  try {
    fallback?.classList.add("hidden");
    chart?.destroy();
    chart = new window.Chart(canvas, {
      type: "bar",
      data: { labels, datasets: [
        { label: "Объем ставок", data: volumes, backgroundColor: "rgba(125,168,255,0.7)" },
        { label: "Выплаты", data: payouts, backgroundColor: "rgba(76,195,138,0.65)" },
      ] },
      options: { responsive: true, maintainAspectRatio: false },
    });
  } catch {
    renderFallback(fallback, labels, volumes, payouts);
  }
};

export const initBetting = async (guildId) => {
  let period = 7;
  const buttons = document.querySelectorAll("#bettingPeriod [data-period]");
  const update = async () => render(guildId, period);
  buttons.forEach((button) => button.addEventListener("click", async () => {
    period = Number(button.dataset.period || 7);
    buttons.forEach((b) => b.classList.toggle("is-active", b === button));
    await update();
  }));
  await update();
};
