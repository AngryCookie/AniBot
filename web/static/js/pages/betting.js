import { apiFetch } from "../api.js";
import { showToast } from "../ui.js";

const toIso = (value) => (value ? new Date(value).toISOString() : null);

export const initBetting = async (guildId) => {
  if (!guildId) return;
  const settingsForm = document.getElementById("bettingSettingsForm");
  const teamForm = document.getElementById("teamForm");
  const matchForm = document.getElementById("matchForm");
  const teamsBody = document.getElementById("teamsBody");
  const matchesBody = document.getElementById("matchesBody");

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
      });
      matchesBody.appendChild(row);
    });
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
  });

  await loadSettings();
  await loadTeams();
  await loadMatches();
};
