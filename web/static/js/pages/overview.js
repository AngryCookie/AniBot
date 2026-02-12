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


const renderRows = (tbody, rows) => {
  if (!tbody) return;
  tbody.innerHTML = "";
  const items = Array.isArray(rows) ? rows : [];
  if (!items.length) {
    tbody.innerHTML = "<tr><td>Нет данных</td><td>—</td></tr>";
    return;
  }
  items.slice(0, 10).forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${item.key}</td><td>${formatValue(item.count)}</td>`;
    tbody.appendChild(tr);
  });
};

const renderEmojiSeries = (container, series) => {
  if (!container) return;
  const points = Array.isArray(series) ? series : [];
  if (!points.length) {
    container.innerHTML = "<p>Нет данных</p>";
    return;
  }
  const max = Math.max(...points.map((p) => Number(p.count || 0)), 1);
  container.innerHTML = "";
  points.forEach((point) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    const width = Math.max(0, (Number(point.count || 0) / max) * 100);
    row.innerHTML = `<span class="bar-label">${point.day.slice(5)}</span><div class="bar-track"><span class="bar-fill bar-created" style="width:${width}%"></span></div><span class="bar-value">${formatValue(point.count)}</span>`;
    container.appendChild(row);
  });
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

    const daysSelect = document.getElementById("wordEmojiDays");
    const wordsBody = document.getElementById("topWordsBody");
    const emojisBody = document.getElementById("topEmojisBody");
    const emojiSeriesChart = document.getElementById("emojiSeriesChart");

    const loadWordEmoji = async () => {
      const days = Number(daysSelect?.value || 30);
      const words = await apiFetch(`/api/guilds/${guildId}/stats/words?days=${days}`);
      const emojis = await apiFetch(`/api/guilds/${guildId}/stats/emojis?days=${days}`);
      renderRows(wordsBody, words?.top || []);
      renderRows(emojisBody, emojis?.top || []);
      renderEmojiSeries(emojiSeriesChart, emojis?.series || []);
    };

    daysSelect?.addEventListener("change", loadWordEmoji);
    await loadWordEmoji();

  } catch (err) {
    if (error) {
      error.textContent = err?.message || "Не удалось загрузить статистику";
    }
    setHidden(error, false);
  } finally {
    setHidden(loading, true);
  }
};
