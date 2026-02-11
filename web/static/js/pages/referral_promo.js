import { apiFetch } from "../api.js";

export const initReferralPromo = async (guildId) => {
  const form = document.getElementById("referralPromoForm");
  const statsRoot = document.getElementById("referralPromoStats");
  const body = document.getElementById("referralPromoCodesBody");
  if (!guildId || !form || !statsRoot || !body) return;

  const renderStats = async () => {
    const stats = await apiFetch(`/api/guilds/${guildId}/referral-promo/stats`);
    if (!stats) return;
    const leaderboard = (stats.top_inviters || [])
      .map((row, idx) => `#${idx + 1} <code>${row.user_id}</code> — ${row.invites} приглаш.`)
      .join("<br />");
    statsRoot.innerHTML = `
      <h4>Сводка</h4>
      <p>Всего использований: <strong>${stats.total_uses}</strong></p>
      <p>Распределено валюты: <strong>${stats.total_currency_distributed}</strong></p>
      <p>Топ инвайтеров:<br />${leaderboard || "—"}</p>
    `;
  };

  const renderCodes = async () => {
    const codes = await apiFetch(`/api/guilds/${guildId}/referral-promo/codes`);
    if (!codes) return;
    body.innerHTML = "";
    codes.forEach((item) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${item.code}</code></td>
        <td>${item.reward_amount}</td>
        <td>${item.current_uses}</td>
        <td>${item.max_uses ?? "∞"}</td>
        <td>${item.is_active ? "Активен" : "Отключён"}</td>
      `;
      body.appendChild(tr);
    });
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      code: form.code.value,
      reward_amount: Number(form.reward_amount.value),
      max_uses: form.max_uses.value ? Number(form.max_uses.value) : null,
      expires_at: form.expires_at.value || null,
      is_active: form.is_active.checked,
    };
    await apiFetch(`/api/guilds/${guildId}/referral-promo/codes`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    form.is_active.checked = true;
    await renderStats();
    await renderCodes();
  });

  await renderStats();
  await renderCodes();
};
