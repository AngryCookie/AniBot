import { apiFetch } from "../api.js";
import { showToast } from "../ui.js";

const toIso = (value) => (value ? new Date(value).toISOString() : null);
const num = (v) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v) || 0);

let analyticsChart = null;

const renderIdWithCopy = (id) => `
  <span>${id}</span>
  <button type="button" class="secondary" data-copy-id="${id}" style="margin-left:8px">Copy</button>
`;

const bindCopyButtons = (root) => {
  root?.querySelectorAll("[data-copy-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copyId || "");
        showToast("ID скопирован", "success");
      } catch {
        showToast("Не удалось скопировать ID", "error");
      }
    });
  });
};

const drawAnalyticsChart = (timeseries = []) => {
  const canvas = document.getElementById("bettingAnalyticsChart");
  const fallback = document.getElementById("bettingAnalyticsFallback");
  if (!canvas) return;

  const labels = timeseries.map((d) => d.day);
  const volume = timeseries.map((d) => Number(d.volume) || 0);
  const payout = timeseries.map((d) => Number(d.payout) || 0);
  const net = timeseries.map((d) => Number(d.net) || 0);

  if (!window.Chart) {
    if (fallback) {
      fallback.innerHTML = labels
        .map((label, i) => `<tr><td>${label}</td><td>${num(volume[i])}</td><td>${num(payout[i])}</td><td>${num(net[i])}</td></tr>`)
        .join("");
      fallback.closest("table")?.classList.remove("hidden");
    }
    return;
  }

  fallback?.closest("table")?.classList.add("hidden");
  analyticsChart?.destroy();
  analyticsChart = new window.Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Volume", data: volume, borderColor: "#7da8ff", tension: 0.25 },
        { label: "Payout", data: payout, borderColor: "#69d48c", tension: 0.25 },
        { label: "Net", data: net, borderColor: "#f08b8b", tension: 0.25 },
      ],
    },
    options: { responsive: true, maintainAspectRatio: false },
  });
};

export const initBetting = async (guildId) => {
  if (!guildId) return;
  const settingsForm = document.getElementById("bettingSettingsForm");
  const teamForm = document.getElementById("teamForm");
  const schedulingForm = document.getElementById("bettingSchedulingForm");
  const scheduleGenerateForm = document.getElementById("bettingScheduleGenerateForm");
  const schedulePreviewBody = document.getElementById("schedulePreviewBody");
  const schedulePreviewBtn = document.getElementById("schedulePreviewBtn");
  const scheduleApplyBtn = document.getElementById("scheduleApplyBtn");
  const matchForm = document.getElementById("matchForm");
  const teamsBody = document.getElementById("teamsBody");
  const matchesBody = document.getElementById("matchesBody");
  const periodButtons = document.querySelectorAll("#bettingAnalyticsPeriod [data-period]");
  const analyticsLoading = document.getElementById("bettingAnalyticsLoading");
  const powerDriftLogsBody = document.getElementById("bettingPowerDriftLogsBody");
  const powerDriftDayLabel = document.getElementById("bettingPowerDriftDayLabel");
  const powerDriftPeriodButtons = document.querySelectorAll("#bettingPowerDriftLogsPeriod [data-days]");

  const loadSettings = async () => {
    const data = await apiFetch(`/api/guilds/${guildId}/betting/settings`);
    settingsForm.elements.namedItem("enabled").checked = Boolean(data.enabled);
    settingsForm.elements.namedItem("announce_channel_id").value = data.announce_channel_id || "";
    settingsForm.elements.namedItem("min_bet_default").value = data.min_bet_default;
    settingsForm.elements.namedItem("max_bet_default").value = data.max_bet_default;
    settingsForm.elements.namedItem("odds_min").value = data.odds?.min;
    settingsForm.elements.namedItem("odds_max").value = data.odds?.max;
    settingsForm.elements.namedItem("odds_randomness").value = data.odds?.randomness;
    settingsForm.elements.namedItem("odds_power_influence").value = data.odds?.power_influence;
    settingsForm.elements.namedItem("resolve_power_weight").value = data.resolve?.power_weight;

    const pd = data.power_drift || {};
    settingsForm.elements.namedItem("power_drift_enabled").checked = Boolean(pd.enabled);
    settingsForm.elements.namedItem("power_drift_timezone").value = pd.timezone || "UTC";
    settingsForm.elements.namedItem("power_drift_tick").value = pd.tick || "daily";
    settingsForm.elements.namedItem("power_drift_max_deviation_percent").value = pd.max_deviation_percent ?? 15;
    settingsForm.elements.namedItem("power_drift_daily_noise_percent").value = pd.daily_noise_percent ?? 3;
    settingsForm.elements.namedItem("power_drift_mean_reversion").value = pd.mean_reversion ?? 0.2;
    settingsForm.elements.namedItem("power_drift_momentum_enabled").checked = Boolean(pd.momentum?.enabled);
    settingsForm.elements.namedItem("power_drift_momentum_window_matches").value = pd.momentum?.window_matches ?? 10;
    settingsForm.elements.namedItem("power_drift_momentum_win_influence_percent").value = pd.momentum?.win_influence_percent ?? 2;

    const sc = data.scheduling || {};
    const mt = sc.month_template || {};
    const pr = sc.pairing_rules || {};
    if (schedulingForm) {
      schedulingForm.elements.namedItem("enabled").checked = Boolean(sc.enabled);
      schedulingForm.elements.namedItem("timezone").value = sc.timezone || "UTC";
      schedulingForm.elements.namedItem("days_of_week").value = (mt.days_of_week || [1,2,3,4,5,6,7]).join(",");
      schedulingForm.elements.namedItem("matches_per_day").value = mt.matches_per_day ?? 1;
      schedulingForm.elements.namedItem("start_hour").value = mt.start_hour ?? 18;
      schedulingForm.elements.namedItem("betting_open_minutes_before").value = mt.betting_open_minutes_before ?? 120;
      schedulingForm.elements.namedItem("betting_close_minutes_before").value = mt.betting_close_minutes_before ?? 10;
      schedulingForm.elements.namedItem("avoid_same_pair_days").value = pr.avoid_same_pair_days ?? 14;
      schedulingForm.elements.namedItem("prefer_active_teams").checked = Boolean(pr.prefer_active_teams ?? true);
      schedulingForm.elements.namedItem("min_active_teams").value = pr.min_active_teams ?? 4;
    }
  };


  const renderSchedulePreview = (matches = []) => {
    if (!schedulePreviewBody) return;
    schedulePreviewBody.innerHTML = matches
      .map((m) => `<tr><td>${new Date(m.date_time_local).toLocaleString()}</td><td>${m.team_a_id}</td><td>${m.team_b_id}</td><td>${new Date(m.betting_open_at_utc).toLocaleString()}</td><td>${new Date(m.betting_close_at_utc).toLocaleString()}</td><td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${m.seed_key}</td></tr>`)
      .join("");
  };

  const loadTeams = async () => {
    const teams = await apiFetch(`/api/guilds/${guildId}/betting/teams`);
    teamsBody.innerHTML = "";
    teams.forEach((team) => {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${team.id}</td><td>${team.name}</td><td>${team.current_power}</td><td>${team.active ? "Да" : "Нет"}</td><td><button type="button" class="danger" data-id="${team.id}">Удалить</button></td>`;
      row.querySelector("button")?.addEventListener("click", async () => {
        await apiFetch(`/api/guilds/${guildId}/betting/teams/${team.id}`, { method: "DELETE" });
        showToast("Команда удалена", "success");
        await loadTeams();
      });
      teamsBody.appendChild(row);
    });
  };

  const loadMatches = async () => {
    const matches = await apiFetch(`/api/guilds/${guildId}/betting/matches`);
    matchesBody.innerHTML = "";
    matches.forEach((match) => {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${match.id}</td><td>${match.team_a_id} vs ${match.team_b_id}</td><td>${Number(match.odds_a).toFixed(2)} / ${Number(match.odds_b).toFixed(2)}</td><td>${new Date(match.betting_open_at).toLocaleString()} - ${new Date(match.betting_close_at).toLocaleString()}</td><td>${match.status}</td><td><button type="button" ${match.status === "resolved" ? "disabled" : ""}>Resolve</button></td>`;
      row.querySelector("button")?.addEventListener("click", async () => {
        await apiFetch(`/api/guilds/${guildId}/betting/matches/${match.id}/resolve`, { method: "POST" });
        showToast("Матч рассчитан", "success");
        await loadMatches();
        await loadAnalytics(currentPeriod);
  await loadPowerDriftLogs(currentDriftDays);
      });
      matchesBody.appendChild(row);
    });
  };


  const loadPowerDriftLogs = async (days) => {
    if (!powerDriftLogsBody) return;
    const data = await apiFetch(`/api/guilds/${guildId}/betting/power-drift/logs?days=${days}`);
    powerDriftDayLabel.textContent = `День: ${data.day || "-"}`;
    powerDriftLogsBody.innerHTML = (data.teams || []).map((row) => `
      <tr>
        <td>${row.team_name}</td>
        <td>${num(row.base_power)}</td>
        <td>${num(row.current_power)}</td>
        <td>${num(row.deviation_percent)}</td>
        <td>${num(row.last_delta)}</td>
      </tr>
    `).join("");
  };

  const loadAnalytics = async (days) => {
    analyticsLoading?.classList.remove("hidden");
    try {
      const [overview, leaderboards] = await Promise.all([
        apiFetch(`/api/guilds/${guildId}/betting/analytics/overview?days=${days}`),
        apiFetch(`/api/guilds/${guildId}/betting/analytics/leaderboards?days=${days}`),
      ]);
      const k = overview?.kpis || {};
      document.getElementById("betKpiBets").textContent = num(k.bets_count);
      document.getElementById("betKpiUsers").textContent = num(k.unique_bettors);
      document.getElementById("betKpiVolume").textContent = num(k.total_volume);
      document.getElementById("betKpiPayout").textContent = num(k.total_payout);
      document.getElementById("betKpiNet").textContent = num(k.net_sink);
      document.getElementById("betKpiAvgBet").textContent = num(k.avg_bet);
      document.getElementById("betKpiAvgOdds").textContent = num(k.avg_odds);

      drawAnalyticsChart(overview?.timeseries || []);

      const volBody = document.getElementById("betLbVolume");
      volBody.innerHTML = (leaderboards.top_by_volume || []).map((row) => `<tr><td>${renderIdWithCopy(row.user_id)}</td><td>${num(row.volume)}</td><td>${num(row.bets)}</td></tr>`).join("");

      const profitBody = document.getElementById("betLbProfit");
      profitBody.innerHTML = (leaderboards.top_by_profit || []).map((row) => `<tr><td>${renderIdWithCopy(row.user_id)}</td><td>${num(row.profit)}</td><td>${num(row.bets)}</td></tr>`).join("");

      const winsBody = document.getElementById("betLbWins");
      winsBody.innerHTML = (leaderboards.biggest_wins || []).map((row) => `<tr><td>${renderIdWithCopy(row.user_id)}</td><td>${row.match_id}</td><td>${num(row.payout)}</td><td>${num(row.bet_amount)}</td><td>${num(row.odds)}</td></tr>`).join("");

      const matchesBodyEl = document.getElementById("betLbMatches");
      matchesBodyEl.innerHTML = (leaderboards.top_matches || []).map((row) => `<tr><td>${row.match_id}</td><td>${num(row.volume)}</td><td>${num(row.bets)}</td></tr>`).join("");

      bindCopyButtons(document);
    } catch (error) {
      showToast(error?.message || "Ошибка загрузки analytics", "error");
    } finally {
      analyticsLoading?.classList.add("hidden");
    }
  };

  settingsForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await apiFetch(`/api/guilds/${guildId}/betting/settings`, {
      method: "PUT",
      body: JSON.stringify({
        enabled: settingsForm.elements.namedItem("enabled").checked,
        announce_channel_id: Number(settingsForm.elements.namedItem("announce_channel_id").value) || null,
        min_bet_default: Number(settingsForm.elements.namedItem("min_bet_default").value),
        max_bet_default: Number(settingsForm.elements.namedItem("max_bet_default").value),
        odds: {
          min: Number(settingsForm.elements.namedItem("odds_min").value),
          max: Number(settingsForm.elements.namedItem("odds_max").value),
          randomness: Number(settingsForm.elements.namedItem("odds_randomness").value),
          power_influence: Number(settingsForm.elements.namedItem("odds_power_influence").value),
        },
        resolve: { power_weight: Number(settingsForm.elements.namedItem("resolve_power_weight").value) },
        power_drift: {
          enabled: settingsForm.elements.namedItem("power_drift_enabled").checked,
          timezone: settingsForm.elements.namedItem("power_drift_timezone").value.trim() || "UTC",
          tick: "daily",
          max_deviation_percent: Number(settingsForm.elements.namedItem("power_drift_max_deviation_percent").value),
          daily_noise_percent: Number(settingsForm.elements.namedItem("power_drift_daily_noise_percent").value),
          mean_reversion: Number(settingsForm.elements.namedItem("power_drift_mean_reversion").value),
          momentum: {
            enabled: settingsForm.elements.namedItem("power_drift_momentum_enabled").checked,
            window_matches: Number(settingsForm.elements.namedItem("power_drift_momentum_window_matches").value),
            win_influence_percent: Number(settingsForm.elements.namedItem("power_drift_momentum_win_influence_percent").value),
          },
        },
      }),
    });
    showToast("Настройки сохранены", "success");
  });

  teamForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await apiFetch(`/api/guilds/${guildId}/betting/teams`, {
      method: "POST",
      body: JSON.stringify({
        name: teamForm.elements.namedItem("name").value,
        description: teamForm.elements.namedItem("description").value,
        base_power: Number(teamForm.elements.namedItem("base_power").value),
        active: teamForm.elements.namedItem("active").checked,
      }),
    });
    teamForm.reset();
    showToast("Команда добавлена", "success");
    await loadTeams();
  });

  matchForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await apiFetch(`/api/guilds/${guildId}/betting/matches`, {
      method: "POST",
      body: JSON.stringify({
        team_a_id: Number(matchForm.elements.namedItem("team_a_id").value),
        team_b_id: Number(matchForm.elements.namedItem("team_b_id").value),
        betting_open_at: toIso(matchForm.elements.namedItem("betting_open_at").value),
        betting_close_at: toIso(matchForm.elements.namedItem("betting_close_at").value),
        min_bet: Number(matchForm.elements.namedItem("min_bet").value) || null,
        max_bet: Number(matchForm.elements.namedItem("max_bet").value) || null,
        announce_channel_id: Number(matchForm.elements.namedItem("announce_channel_id").value) || null,
      }),
    });
    matchForm.reset();
    showToast("Матч создан", "success");
    await loadMatches();
    await loadAnalytics(currentPeriod);
  await loadPowerDriftLogs(currentDriftDays);
  });


  schedulingForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const days = String(schedulingForm.elements.namedItem("days_of_week").value || "")
      .split(",")
      .map((v) => Number(v.trim()))
      .filter((v) => Number.isInteger(v) && v >= 1 && v <= 7);
    await apiFetch(`/api/guilds/${guildId}/betting/scheduling`, {
      method: "PUT",
      body: JSON.stringify({
        enabled: schedulingForm.elements.namedItem("enabled").checked,
        timezone: schedulingForm.elements.namedItem("timezone").value.trim() || "UTC",
        month_template: {
          days_of_week: days.length ? days : [1, 2, 3, 4, 5, 6, 7],
          matches_per_day: Number(schedulingForm.elements.namedItem("matches_per_day").value),
          start_hour: Number(schedulingForm.elements.namedItem("start_hour").value),
          betting_open_minutes_before: Number(schedulingForm.elements.namedItem("betting_open_minutes_before").value),
          betting_close_minutes_before: Number(schedulingForm.elements.namedItem("betting_close_minutes_before").value),
        },
        pairing_rules: {
          avoid_same_pair_days: Number(schedulingForm.elements.namedItem("avoid_same_pair_days").value),
          prefer_active_teams: schedulingForm.elements.namedItem("prefer_active_teams").checked,
          min_active_teams: Number(schedulingForm.elements.namedItem("min_active_teams").value),
        },
      }),
    });
    showToast("Scheduling настройки сохранены", "success");
  });

  schedulePreviewBtn?.addEventListener("click", async () => {
    const year = Number(scheduleGenerateForm?.elements.namedItem("year")?.value);
    const month = Number(scheduleGenerateForm?.elements.namedItem("month")?.value);
    const preview = await apiFetch(`/api/guilds/${guildId}/betting/scheduling/generate?year=${year}&month=${month}`, { method: "POST" });
    renderSchedulePreview(preview || []);
    showToast(`Сгенерировано: ${(preview || []).length}`, "success");
  });

  scheduleApplyBtn?.addEventListener("click", async () => {
    const year = Number(scheduleGenerateForm?.elements.namedItem("year")?.value);
    const month = Number(scheduleGenerateForm?.elements.namedItem("month")?.value);
    const res = await apiFetch(`/api/guilds/${guildId}/betting/scheduling/apply?year=${year}&month=${month}`, { method: "POST" });
    showToast(`Apply: +${res.inserted}, skip ${res.skipped_existing}`, "success");
    const preview = await apiFetch(`/api/guilds/${guildId}/betting/scheduling/generate?year=${year}&month=${month}`, { method: "POST" });
    renderSchedulePreview(preview || []);
    await loadMatches();
    await loadAnalytics(currentPeriod);
  await loadPowerDriftLogs(currentDriftDays);
  });

  let currentPeriod = 7;
  periodButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      currentPeriod = Number(button.dataset.period || 7);
      periodButtons.forEach((b) => b.classList.toggle("is-active", b === button));
      await loadAnalytics(currentPeriod);
  await loadPowerDriftLogs(currentDriftDays);
    });
  });

  let currentDriftDays = 7;
  powerDriftPeriodButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      currentDriftDays = Number(button.dataset.days || 7);
      powerDriftPeriodButtons.forEach((b) => b.classList.toggle("is-active", b === button));
      await loadPowerDriftLogs(currentDriftDays);
    });
  });

  await loadSettings();
  const now = new Date();
  if (scheduleGenerateForm) {
    scheduleGenerateForm.elements.namedItem("year").value = now.getUTCFullYear();
    scheduleGenerateForm.elements.namedItem("month").value = now.getUTCMonth() + 1;
  }
  await loadTeams();
  await loadMatches();
  await loadAnalytics(currentPeriod);
  await loadPowerDriftLogs(currentDriftDays);
};
