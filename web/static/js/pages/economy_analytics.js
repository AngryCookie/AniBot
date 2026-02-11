import { getEconomyAnalytics, getEconomyInsights } from "../api.js";

let mintBurnChart = null;

const setHidden = (element, isHidden) => {
  if (!element) return;
  element.classList.toggle("hidden", isHidden);
};

const formatNumber = (value) => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
};

const formatPercent = (value) => {
  if (value === null || value === undefined) return "—";
  const percentValue = Number(value) * 100;
  if (Number.isNaN(percentValue)) return "—";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(percentValue)}%`;
};

const setActivePeriod = (buttons, period) => {
  buttons.forEach((button) => {
    button.classList.toggle("is-active", Number(button.dataset.period) === period);
  });
};

const buildMetricMap = (data) => ({
  total_created: { value: data?.created },
  total_spent: { value: data?.spent },
  net_flow: { value: data?.net_flow },
  active_users_percent: { value: data?.activity?.active_users_percent, format: "percent" },
  average_balance: { value: data?.distribution?.average_balance },
  median_balance: { value: data?.distribution?.median_balance },
  top_10_percent_share: { value: data?.distribution?.top_10_percent_share, format: "percent" },
});

const renderMetricCards = (container, data) => {
  if (!container) return;
  const map = buildMetricMap(data);
  container.querySelectorAll("[data-metric]").forEach((card) => {
    const key = card.dataset.metric;
    const entry = map[key];
    const valueNode = card.querySelector("[data-value]");
    if (!valueNode) return;
    if (!entry) {
      valueNode.textContent = "—";
      return;
    }
    valueNode.textContent = (entry.format === "percent" ? formatPercent : formatNumber)(entry.value);
  });
};

const renderCreatedSpentChart = (container, createdValue, spentValue) => {
  if (!container) return;
  container.innerHTML = "";
  const maxValue = Math.max(createdValue, spentValue, 1);
  [
    { label: "Создано", value: createdValue, className: "bar-created" },
    { label: "Потрачено", value: spentValue, className: "bar-spent" },
  ].forEach((row) => {
    const line = document.createElement("div");
    line.className = "bar-row";
    line.innerHTML = `
      <span class="bar-label">${row.label}</span>
      <div class="bar-track"><span class="bar-fill ${row.className}" style="width: ${Math.max(0, (row.value / maxValue) * 100)}%"></span></div>
      <span class="bar-value">${formatNumber(row.value)}</span>
    `;
    container.appendChild(line);
  });
};

const renderMintBurnChart = (canvas, fallbackTable, createdValue, spentValue) => {
  const fallbackBody = fallbackTable?.querySelector("tbody");
  const showFallback = () => {
    if (!fallbackBody) return;
    fallbackBody.innerHTML = `<tr><td>Создано</td><td>${formatNumber(createdValue)}</td></tr><tr><td>Сожжено</td><td>${formatNumber(spentValue)}</td></tr>`;
    fallbackTable?.classList.remove("hidden");
  };

  if (!canvas || !window.Chart) {
    showFallback();
    return;
  }

  try {
    fallbackTable?.classList.add("hidden");
    mintBurnChart?.destroy();
    mintBurnChart = new window.Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["Minted", "Burned"],
        datasets: [{ data: [createdValue || 0, spentValue || 0], backgroundColor: ["#4c7ef3", "#d64545"] }],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });
  } catch {
    showFallback();
  }
};

const renderNetFlowChart = (container, netFlow, createdValue, spentValue, labelNode) => {
  if (!container) return;
  container.innerHTML = "";
  const maxRange = Math.max(Math.abs(netFlow), Math.abs(createdValue), Math.abs(spentValue), 1);
  const width = Math.min(1, Math.abs(netFlow) / maxRange) * 50;
  const track = document.createElement("div");
  track.className = "net-flow-track";
  track.innerHTML = '<span class="net-flow-zero"></span>';
  const bar = document.createElement("span");
  bar.className = `net-flow-bar ${netFlow >= 0 ? "positive" : "negative"}`;
  bar.style.width = `${width}%`;
  track.appendChild(bar);
  container.appendChild(track);
  if (labelNode) labelNode.textContent = `${netFlow >= 0 ? "Рост" : "Снижение"}: ${formatNumber(netFlow)}`;
};

const renderDistributionChart = (container, legend, topShare) => {
  if (!container) return;
  const safeTop = Math.max(0, Math.min(1, topShare ?? 0));
  const restPercent = 100 - safeTop * 100;
  container.innerHTML = `<div class="distribution-bar"><span class="distribution-segment distribution-top" style="width:${safeTop * 100}%"></span><span class="distribution-segment distribution-rest" style="width:${restPercent}%"></span></div>`;
  if (legend) legend.innerHTML = `<span class="legend-item">Топ 10% — ${formatPercent(safeTop)}</span><span class="legend-item">Остальные — ${formatPercent(restPercent / 100)}</span>`;
};

const renderHealth = (data, ratioNode, statusNode) => {
  if (ratioNode) ratioNode.textContent = formatNumber(data?.health?.sink_ratio);
  if (!statusNode) return;
  const sinkRatio = data?.health?.sink_ratio ?? 0;
  const inflationFlag = Boolean(data?.health?.inflation_flag);
  let status = "healthy";
  let label = "Зелёный";
  if (inflationFlag) {
    status = "risk"; label = "Красный";
  } else if (sinkRatio < 0.7 || sinkRatio > 1.1) {
    status = "watch"; label = "Жёлтый";
  }
  statusNode.textContent = label;
  statusNode.className = `status-pill status-${status}`;
};

const renderInsights = (insights, container) => {
  if (!container) return;
  if (!Array.isArray(insights) || insights.length === 0) {
    container.innerHTML = "<p>Критичных сигналов не обнаружено.</p>";
    return;
  }
  container.innerHTML = `<ul class="insights-list">${insights.map((insight) => `<li class="insight-item insight-${insight.severity || "info"}">${insight.title}: ${insight.description}</li>`).join("")}</ul>`;
};

const isValidAnalytics = (data) => data && typeof data.created === "number" && typeof data.spent === "number" && data.distribution && data.activity && data.health;

export const initEconomyAnalytics = async (guildId) => {
  const loading = document.getElementById("economyAnalyticsLoading");
  const error = document.getElementById("economyAnalyticsError");
  const empty = document.getElementById("economyAnalyticsEmpty");
  const content = document.getElementById("economyAnalyticsContent");
  const periodButtons = Array.from(document.querySelectorAll("[data-period]"));
  const metricsGrid = document.querySelector(".analytics-metrics");
  const createdSpentChart = document.getElementById("economyCreatedSpentChart");
  const mintBurnCanvas = document.getElementById("economyMintBurnChart");
  const mintBurnFallback = document.getElementById("economyMintBurnFallback");
  const netFlowChart = document.getElementById("economyNetFlowChart");
  const netFlowLabel = document.getElementById("economyNetFlowLabel");
  const distributionChart = document.getElementById("economyDistributionChart");
  const distributionLegend = document.getElementById("economyDistributionLegend");
  const sinkRatioNode = document.getElementById("economySinkRatio");
  const inflationStatus = document.getElementById("economyInflationStatus");
  const insightsNode = document.getElementById("economyAnalyticsInsights");

  if (!guildId) return;
  let currentPeriod = 7;
  const showError = (message) => { if (error) { error.textContent = message; setHidden(error, !message); } };

  const loadInsights = async (period) => {
    try { renderInsights(await getEconomyInsights(guildId, period), insightsNode); }
    catch { renderInsights([], insightsNode); }
  };

  const loadAnalytics = async (period) => {
    setHidden(loading, false); setHidden(empty, true); setHidden(content, true); showError("");
    try {
      const data = await getEconomyAnalytics(guildId, period);
      setHidden(loading, true);
      await loadInsights(period);
      if (!isValidAnalytics(data)) { setHidden(empty, false); return; }
      renderMetricCards(metricsGrid, data);
      renderCreatedSpentChart(createdSpentChart, data.created, data.spent);
      renderMintBurnChart(mintBurnCanvas, mintBurnFallback, data.created, data.spent);
      renderNetFlowChart(netFlowChart, data.net_flow, data.created, data.spent, netFlowLabel);
      renderDistributionChart(distributionChart, distributionLegend, data.distribution?.top_10_percent_share);
      renderHealth(data, sinkRatioNode, inflationStatus);
      setHidden(content, false);
    } catch (err) {
      setHidden(loading, true);
      showError(err?.message || "Не удалось загрузить аналитику");
    }
  };

  periodButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const nextPeriod = Number(button.dataset.period);
      if (!nextPeriod || nextPeriod === currentPeriod) return;
      currentPeriod = nextPeriod;
      setActivePeriod(periodButtons, currentPeriod);
      loadAnalytics(currentPeriod);
    });
  });

  setActivePeriod(periodButtons, currentPeriod);
  await loadAnalytics(currentPeriod);
};
