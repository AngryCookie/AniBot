import { getEconomyRecommendations } from "../api.js";
import { showToast } from "../ui.js";

const formatNumber = (v) => new Intl.NumberFormat("ru-RU").format(Number(v || 0));

export const initEconomyRecommendations = async (guildId) => {
  const loading = document.getElementById("economyRecommendationsLoading");
  const error = document.getElementById("economyRecommendationsError");
  const content = document.getElementById("economyRecommendationsContent");
  const mintedNode = document.getElementById("recMinted");
  const burnedNode = document.getElementById("recBurned");
  const netNode = document.getElementById("recNet");
  const warningsNode = document.getElementById("recWarnings");
  const buffRows = document.getElementById("recBuffRows");
  const percentWarnings = document.getElementById("recPercentWarnings");
  const buttons = Array.from(document.querySelectorAll("button[data-days]"));

  if (!guildId || !loading || !content) return;

  const setState = ({ isLoading = false, message = "" } = {}) => {
    loading.classList.toggle("hidden", !isLoading);
    error.classList.toggle("hidden", !message);
    error.textContent = message;
    content.classList.toggle("hidden", isLoading || !!message);
  };

  const render = async (days) => {
    setState({ isLoading: true, message: "" });
    buttons.forEach((btn) => btn.classList.toggle("is-active", Number(btn.dataset.days) === days));
    try {
      const data = await getEconomyRecommendations(guildId, days);
      mintedNode.textContent = formatNumber(data.kpis.minted_total);
      burnedNode.textContent = formatNumber(data.kpis.burned_total);
      netNode.textContent = formatNumber(data.kpis.net);

      if (data.warnings.length) {
        warningsNode.className = "alert error";
        warningsNode.innerHTML = data.warnings.map((w) => `• ${w.message}`).join("<br>");
      } else {
        warningsNode.className = "notice";
        warningsNode.textContent = "Предупреждений нет.";
      }

      buffRows.innerHTML = "";
      data.suggestions.buff_price_ranges.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.name}</td>
          <td>${formatNumber(row.current_price)}</td>
          <td>${row.current_percent}%</td>
          <td>${formatNumber(row.suggested_min)}–${formatNumber(row.suggested_max)}</td>
          <td>≈ ${formatNumber(row.projected_weekly_sink)}</td>
          <td><button class="secondary">Copy suggestion</button></td>
        `;
        tr.querySelector("button")?.addEventListener("click", async () => {
          await navigator.clipboard.writeText(String(row.suggested_min));
          showToast(`Скопировано: ${row.suggested_min}`, "success");
        });
        buffRows.appendChild(tr);
      });
      if (!data.suggestions.buff_price_ranges.length) {
        buffRows.innerHTML = '<tr><td colspan="6">Нет buff/jobs_bonus для расчёта диапазона.</td></tr>';
      }

      percentWarnings.innerHTML = "";
      data.suggestions.buff_percent_warnings.forEach((w) => {
        const li = document.createElement("li");
        li.textContent = `${w.name}: ${w.value_percent}% (реком. cap ${w.recommended_cap}%)`;
        percentWarnings.appendChild(li);
      });
      if (!data.suggestions.buff_percent_warnings.length) {
        percentWarnings.innerHTML = "<li>Значения процентов в рекомендуемых пределах.</li>";
      }

      setState({ isLoading: false, message: "" });
    } catch (e) {
      setState({ isLoading: false, message: e.message || "Не удалось загрузить рекомендации." });
    }
  };

  buttons.forEach((btn) => btn.addEventListener("click", () => render(Number(btn.dataset.days || 7))));
  await render(7);
};
