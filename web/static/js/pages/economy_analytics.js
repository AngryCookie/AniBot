import { getEconomyAnalytics } from "../api.js";

const setHidden = (element, isHidden) => {
  if (!element) return;
  element.classList.toggle("hidden", isHidden);
};

const formatNumber = (value) => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 2,
  }).format(value);
};

const formatPercent = (value) => {
  if (value === null || value === undefined) return "—";
  const percentValue = Number(value) * 100;
  if (Number.isNaN(percentValue)) return "—";
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 1,
  }).format(percentValue) + "%";
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
  top_10_percent_share: {
    value: data?.distribution?.top_10_percent_share,
    format: "percent",
  },
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
    const formatter = entry.format === "percent" ? formatPercent : formatNumber;
    valueNode.textContent = formatter(entry.value);
  });
};

const renderCreatedSpentChart = (container, createdValue, spentValue) => {
  if (!container) return;
  container.innerHTML = "";
  const maxValue = Math.max(createdValue, spentValue, 1);
  const rows = [
    { label: "Создано", value: createdValue, className: "bar-created" },
    { label: "Потрачено", value: spentValue, className: "bar-spent" },
  ];
  rows.forEach((row) => {
    const line = document.createElement("div");
    line.className = "bar-row";
    const width = Math.max(0, (row.value / maxValue) * 100);
    line.innerHTML = `
      <span class="bar-label">${row.label}</span>
      <div class="bar-track">
        <span class="bar-fill ${row.className}" style="width: ${width}%"></span>
      </div>
      <span class="bar-value">${formatNumber(row.value)}</span>
    `;
    container.appendChild(line);
  });
};

const renderNetFlowChart = (container, netFlow, createdValue, spentValue, labelNode) => {
  if (!container) return;
  container.innerHTML = "";
  const maxRange = Math.max(
    Math.abs(netFlow),
    Math.abs(createdValue),
    Math.abs(spentValue),
    1
  );
  const ratio = Math.min(1, Math.abs(netFlow) / maxRange);
  const width = ratio * 50;
  const track = document.createElement("div");
  track.className = "net-flow-track";
  track.innerHTML = '<span class="net-flow-zero"></span>';
  const bar = document.createElement("span");
  bar.className = `net-flow-bar ${netFlow >= 0 ? "positive" : "negative"}`;
  bar.style.width = `${width}%`;
  track.appendChild(bar);
  container.appendChild(track);
  if (labelNode) {
    const label = netFlow >= 0 ? "Рост" : "Снижение";
    labelNode.textContent = `${label}: ${formatNumber(netFlow)}`;
  }
};

const renderDistributionChart = (container, legend, topShare) => {
  if (!container) return;
  const safeTop = Math.max(0, Math.min(1, topShare ?? 0));
  const topPercent = safeTop * 100;
  const restPercent = 100 - topPercent;
  container.innerHTML = `
    <div class="distribution-bar">
      <span class="distribution-segment distribution-top" style="width: ${topPercent}%"></span>
      <span class="distribution-segment distribution-rest" style="width: ${restPercent}%"></span>
    </div>
  `;
  if (legend) {
    legend.innerHTML = `
      <span class="legend-item"><span class="legend-swatch top"></span>Топ 10% — ${formatPercent(
        safeTop
      )}</span>
      <span class="legend-item"><span class="legend-swatch rest"></span>Остальные — ${formatPercent(
        restPercent / 100
      )}</span>
    `;
  }
};

const renderHealth = (data, ratioNode, statusNode) => {
  if (ratioNode) {
    ratioNode.textContent = formatNumber(data?.health?.sink_ratio);
  }
  if (!statusNode) return;

  const sinkRatio = data?.health?.sink_ratio ?? 0;
  const inflationFlag = Boolean(data?.health?.inflation_flag);

  let status = "healthy";
  let label = "Зелёный";

  if (inflationFlag) {
    status = "risk";
    label = "Красный";
  } else if (sinkRatio < 0.7 || sinkRatio > 1.1) {
    status = "watch";
    label = "Жёлтый";
  }

  statusNode.textContent = label;
  statusNode.className = `status-pill status-${status}`;
};

const renderInsights = (data, container) => {
  if (!container) return;
  const created = data?.created ?? 0;
  const spent = data?.spent ?? 0;
  const net = data?.net_flow ?? 0;
  const activePercent = data?.activity?.active_users_percent ?? 0;
  const topShare = data?.distribution?.top_10_percent_share ?? 0;
  const sinkRatio = data?.health?.sink_ratio ?? 0;
  const inflationFlag = Boolean(data?.health?.inflation_flag);

  container.innerHTML = `
    <ul class="insights-list">
      <li>Создано ${formatNumber(created)}, потрачено ${formatNumber(spent)} (чистый поток: ${
        formatNumber(net)
      }).</li>
      <li>Активные пользователи: ${formatPercent(activePercent)} от базы с балансом.</li>
      <li>Доля топ-10% по богатству: ${formatPercent(topShare)}.</li>
      <li>Sink ratio: ${formatNumber(sinkRatio)} — чем ближе к 1, тем лучше баланс источников и списаний.</li>
      <li>Флаг инфляции: ${inflationFlag ? "есть риск" : "нет риска"}.</li>
    </ul>
  `;
};

const isValidAnalytics = (data) =>
  data &&
  typeof data.created === "number" &&
  typeof data.spent === "number" &&
  data.distribution &&
  data.activity &&
  data.health;

export const initEconomyAnalytics = async (guildId) => {
  const loading = document.getElementById("economyAnalyticsLoading");
  const error = document.getElementById("economyAnalyticsError");
  const empty = document.getElementById("economyAnalyticsEmpty");
  const content = document.getElementById("economyAnalyticsContent");
  const periodButtons = Array.from(document.querySelectorAll("[data-period]"));
  const metricsGrid = document.querySelector(".analytics-metrics");
  const createdSpentChart = document.getElementById("economyCreatedSpentChart");
  const netFlowChart = document.getElementById("economyNetFlowChart");
  const netFlowLabel = document.getElementById("economyNetFlowLabel");
  const distributionChart = document.getElementById("economyDistributionChart");
  const distributionLegend = document.getElementById("economyDistributionLegend");
  const sinkRatioNode = document.getElementById("economySinkRatio");
  const inflationStatus = document.getElementById("economyInflationStatus");
  const insightsNode = document.getElementById("economyAnalyticsInsights");

  if (!guildId) return;

  let currentPeriod = 7;

  const showError = (message) => {
    if (!error) return;
    error.textContent = message;
    setHidden(error, !message);
  };

  const loadAnalytics = async (period) => {
    setHidden(loading, false);
    setHidden(empty, true);
    setHidden(content, true);
    showError("");

    try {
      const data = await getEconomyAnalytics(guildId, period);
      setHidden(loading, true);

      if (!isValidAnalytics(data)) {
        setHidden(empty, false);
        return;
      }

      renderMetricCards(metricsGrid, data);
      renderCreatedSpentChart(createdSpentChart, data.created, data.spent);
      renderNetFlowChart(
        netFlowChart,
        data.net_flow,
        data.created,
        data.spent,
        netFlowLabel
      );
      renderDistributionChart(
        distributionChart,
        distributionLegend,
        data.distribution?.top_10_percent_share
      );
      renderHealth(data, sinkRatioNode, inflationStatus);
      renderInsights(data, insightsNode);

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
