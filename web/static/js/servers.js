import { apiFetch } from "./api.js";

const list = document.getElementById("guildList");
const loading = document.getElementById("serversLoading");

const setLoading = (isLoading) => {
  if (!loading) return;
  loading.classList.toggle("hidden", !isLoading);
};

const setupServers = async () => {
  if (!list) return;
  setLoading(true);
  try {
    const data = await apiFetch("/api/guilds");
    if (!data) return;
    list.innerHTML = "";
    data.guilds.forEach((guild) => {
      const item = document.createElement("div");
      item.className = "card";
      item.innerHTML = `
        <strong>${guild.name}</strong>
        <div class="footer-actions">
          <a href="/app.html?guild_id=${guild.id}#/overview">Открыть панель</a>
          <a href="/analytics.html?guild_id=${guild.id}">Analytics</a>
        </div>
      `;
      list.appendChild(item);
    });
  } catch (error) {
    list.innerHTML = `<div class="alert error">${error.message}</div>`;
  } finally {
    setLoading(false);
  }
};

document.addEventListener("DOMContentLoaded", setupServers);
