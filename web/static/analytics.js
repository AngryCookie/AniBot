const CHART_COLORS = {
  earned: "#4cc38a",
  spent: "#f56c6c",
  volume: "#7da8ff",
  house: "#f8c555",
  messages: "#8cd3ff",
  voice: "#bb86fc",
};

const state = {
  guildId: null,
  period: 30,
  charts: {
    economy: null,
    betting: null,
    activity: null,
  },
};

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

  return response.status === 204 ? null : response.json();
};

const formatNumber = (value) =>
  new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
  }).format(Number(value) || 0);

const getGuildId = () => {
  const params = new URLSearchParams(window.location.search);
  return params.get("guild_id");
};

const updateNavLinks = (guildId) => {
  if (!guildId) return;
  document.querySelectorAll("nav a").forEach((link) => {
    const url = new URL(link.getAttribute("href"), window.location.origin);
    url.searchParams.set("guild_id", guildId);
    link.setAttribute("href", url.toString().replace(window.location.origin, ""));
  });
};

const setActivePeriodButton = (period) => {
  document.querySelectorAll("[data-period]").forEach((button) => {
    button.classList.toggle("is-active", Number(button.dataset.period) === period);
  });
};

const setVisibility = (element, visible) => {
  if (!element) return;
  element.classList.toggle("hidden", !visible);
};

const showError = (message = "") => {
  const errorNode = document.getElementById("analyticsError");
  if (!errorNode) return;
  errorNode.textContent = message;
  setVisibility(errorNode, Boolean(message));
};

const setLoading = (isLoading) => {
  setVisibility(document.getElementById("analyticsLoading"), isLoading);
};

const setEmpty = (isEmpty) => {
  setVisibility(document.getElementById("analyticsEmpty"), isEmpty);
};

const updatePeriodTitle = () => {
  const titleNode = document.getElementById("guildTitle");
  if (!titleNode) return;
  titleNode.textContent = `Аналитика сервера · период ${state.period} дней`;
};

const destroyChart = (key) => {
  if (!state.charts[key]) return;
  state.charts[key].destroy();
  state.charts[key] = null;
};

const safeSeriesMap = (series = [], valueKey) => {
  const map = new Map();
  series.forEach((entry) => {
    if (!entry?.date) return;
    const value = Number(entry[valueKey]) || 0;
    map.set(entry.date, value);
  });
  return map;
};

const mergeDates = (...maps) => {
  const dates = new Set();
  maps.forEach((map) => {
    map.forEach((_, date) => dates.add(date));
  });
  return Array.from(dates).sort((a, b) => new Date(a) - new Date(b));
};

const chartBaseOptions = () => ({
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      labels: {
        color: "#e9edf4",
      },
    },
  },
  scales: {
    x: {
      ticks: {
        color: "#b8c0cc",
      },
      grid: {
        color: "rgba(255, 255, 255, 0.06)",
      },
    },
    y: {
      beginAtZero: true,
      ticks: {
        color: "#b8c0cc",
      },
      grid: {
        color: "rgba(255, 255, 255, 0.08)",
      },
    },
  },
});

const renderKpis = (overview) => {
  const economy = overview?.economy || {};
  const betting = overview?.betting || {};
  const activity = overview?.activity || {};

  const values = {
    kpiCirculation: economy.total_currency_in_circulation,
    kpiEarned: economy.total_earned,
    kpiSpent: economy.total_spent,
    kpiBets: betting.total_bets_amount,
    kpiHouse: betting.house_net,
    kpiMessages: activity.total_messages,
  };

  Object.entries(values).forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = formatNumber(value);
  });
};

const renderEconomyChart = (timeseries) => {
  destroyChart("economy");
  const ctx = document.getElementById("economyChart");
  if (!ctx) return;

  const earnedMap = safeSeriesMap(timeseries?.economy?.daily_earned, "amount");
  const spentMap = safeSeriesMap(timeseries?.economy?.daily_spent, "amount");
  const labels = mergeDates(earnedMap, spentMap);

  state.charts.economy = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Daily earned",
          data: labels.map((date) => earnedMap.get(date) || 0),
          borderColor: CHART_COLORS.earned,
          backgroundColor: "rgba(76, 195, 138, 0.2)",
          tension: 0.3,
        },
        {
          label: "Daily spent",
          data: labels.map((date) => spentMap.get(date) || 0),
          borderColor: CHART_COLORS.spent,
          backgroundColor: "rgba(245, 108, 108, 0.2)",
          tension: 0.3,
        },
      ],
    },
    options: chartBaseOptions(),
  });
};

const renderBettingChart = (timeseries) => {
  destroyChart("betting");
  const ctx = document.getElementById("bettingChart");
  if (!ctx) return;

  const volumeMap = safeSeriesMap(timeseries?.betting?.daily_volume, "amount");
  const houseMap = safeSeriesMap(timeseries?.betting?.daily_house_net, "amount");
  const labels = mergeDates(volumeMap, houseMap);

  state.charts.betting = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Daily volume",
          data: labels.map((date) => volumeMap.get(date) || 0),
          backgroundColor: "rgba(125, 168, 255, 0.7)",
          borderColor: CHART_COLORS.volume,
          borderWidth: 1,
        },
        {
          label: "Daily house net",
          data: labels.map((date) => houseMap.get(date) || 0),
          backgroundColor: "rgba(248, 197, 85, 0.7)",
          borderColor: CHART_COLORS.house,
          borderWidth: 1,
        },
      ],
    },
    options: chartBaseOptions(),
  });
};

const renderActivityChart = (timeseries) => {
  destroyChart("activity");
  const ctx = document.getElementById("activityChart");
  if (!ctx) return;

  const messagesMap = safeSeriesMap(timeseries?.activity?.daily_messages, "count");
  const voiceMap = safeSeriesMap(timeseries?.activity?.daily_voice_minutes, "count");
  const labels = mergeDates(messagesMap, voiceMap);

  state.charts.activity = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Daily messages",
          data: labels.map((date) => messagesMap.get(date) || 0),
          borderColor: CHART_COLORS.messages,
          backgroundColor: "rgba(140, 211, 255, 0.2)",
          tension: 0.3,
        },
        {
          label: "Daily voice minutes",
          data: labels.map((date) => voiceMap.get(date) || 0),
          borderColor: CHART_COLORS.voice,
          backgroundColor: "rgba(187, 134, 252, 0.2)",
          tension: 0.3,
        },
      ],
    },
    options: chartBaseOptions(),
  });
};

const hasTimeseriesData = (timeseries) => {
  const sources = [
    timeseries?.economy?.daily_earned,
    timeseries?.economy?.daily_spent,
    timeseries?.betting?.daily_volume,
    timeseries?.betting?.daily_house_net,
    timeseries?.activity?.daily_messages,
    timeseries?.activity?.daily_voice_minutes,
  ];
  return sources.some((series) => Array.isArray(series) && series.length > 0);
};

const loadAnalytics = async () => {
  setLoading(true);
  setEmpty(false);
  showError("");

  try {
    const [overview, timeseries] = await Promise.all([
      apiFetch(`/api/guilds/${state.guildId}/analytics/overview?period=${state.period}`),
      apiFetch(`/api/guilds/${state.guildId}/analytics/timeseries?period=${state.period}`),
    ]);

    renderKpis(overview);

    if (!hasTimeseriesData(timeseries)) {
      destroyChart("economy");
      destroyChart("betting");
      destroyChart("activity");
      setEmpty(true);
      return;
    }

    renderEconomyChart(timeseries);
    renderBettingChart(timeseries);
    renderActivityChart(timeseries);
  } catch (error) {
    showError(error.message || "Не удалось загрузить аналитику");
  } finally {
    setLoading(false);
  }
};

const setupPeriodButtons = () => {
  document.querySelectorAll("[data-period]").forEach((button) => {
    button.addEventListener("click", () => {
      const period = Number(button.dataset.period);
      if (!period || period === state.period) return;
      state.period = period;
      setActivePeriodButton(period);
      updatePeriodTitle();
      loadAnalytics();
    });
  });
};

const init = async () => {
  state.guildId = getGuildId();
  if (!state.guildId) {
    window.location.href = "/servers.html";
    return;
  }

  updateNavLinks(state.guildId);
  setActivePeriodButton(state.period);

  updatePeriodTitle();

  setupPeriodButtons();
  await loadAnalytics();
};

document.addEventListener("DOMContentLoaded", init);
