import { apiFetch } from "../api.js";

const integerFormatter = new Intl.NumberFormat("ru-RU");
const decimalFormatter = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const formatValue = (value, formatter = integerFormatter) => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return formatter.format(value);
};

const setHidden = (element, isHidden) => {
  if (!element) return;
  element.classList.toggle("hidden", isHidden);
};

const resetValues = (statsGrid) => {
  if (!statsGrid) return;
  statsGrid.querySelectorAll("[data-stat-value]").forEach((node) => {
    node.textContent = "—";
  });
};

export const initOverview = async (guildId) => {
  const statsGrid = document.getElementById("overviewStats");
  const loading = document.getElementById("overviewLoading");
  const error = document.getElementById("overviewError");
  const empty = document.getElementById("overviewEmpty");

  resetValues(statsGrid);
  setHidden(error, true);
  setHidden(empty, true);
  setHidden(loading, false);
  setHidden(statsGrid, true);

  if (!guildId) {
    setHidden(loading, true);
    setHidden(empty, false);
    return;
  }

  try {
    const stats = await apiFetch(`/api/guilds/${guildId}/overview`);
    if (!stats || Object.keys(stats).length === 0) {
      setHidden(empty, false);
      return;
    }

    const values = {
      member_count: formatValue(stats.member_count),
      total_balance: formatValue(stats.total_balance),
      average_level: formatValue(stats.average_level, decimalFormatter),
      total_warnings: formatValue(stats.total_warnings),
      total_shop_items: formatValue(stats.total_shop_items),
    };

    Object.entries(values).forEach(([key, value]) => {
      const node = statsGrid?.querySelector(`[data-stat="${key}"] [data-stat-value]`);
      if (node) {
        node.textContent = value;
      }
    });

    setHidden(statsGrid, false);
  } catch (err) {
    if (error) {
      error.textContent = err?.message || "Не удалось загрузить статистику";
    }
    setHidden(error, false);
  } finally {
    setHidden(loading, true);
  }
};
