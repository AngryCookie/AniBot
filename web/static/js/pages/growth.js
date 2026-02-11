import { apiFetch } from "../api.js";

const formToPayload = (form) => {
  const payload = {};
  Array.from(form.elements).forEach((field) => {
    if (!field.name) return;
    if (field.type === "checkbox") {
      payload[field.name] = field.checked;
      return;
    }
    if (field.type === "number") {
      payload[field.name] = field.value === "" ? null : Number(field.value);
      return;
    }
    payload[field.name] = field.value || null;
  });
  return payload;
};

const fillForm = (form, data) => {
  Object.entries(data).forEach(([key, value]) => {
    const field = form.elements.namedItem(key);
    if (!field) return;
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
    } else {
      field.value = value ?? "";
    }
  });
};

export const initGrowth = async (guildId) => {
  if (!guildId) return;

  const referralForm = document.getElementById("growthReferralForm");
  const promoBody = document.getElementById("growthPromoBody");
  const overviewRoot = document.getElementById("growthOverview");
  const topReferrersRoot = document.getElementById("growthTopReferrers");
  const mostUsedPromoRoot = document.getElementById("growthMostUsedPromo");

  const promoModal = document.getElementById("growthPromoModal");
  const promoForm = document.getElementById("growthPromoForm");
  const openPromoModalButton = document.getElementById("growthOpenPromoModal");
  const cancelPromoModalButton = document.getElementById("growthPromoCancel");

  if (!referralForm || !promoBody || !overviewRoot || !topReferrersRoot || !mostUsedPromoRoot) {
    return;
  }

  const openModal = () => promoModal?.classList.remove("hidden");
  const closeModal = () => promoModal?.classList.add("hidden");

  const loadReferralSettings = async () => {
    const data = await apiFetch(`/api/growth/referral/settings?guild_id=${guildId}`);
    if (!data) return;
    fillForm(referralForm, data);
  };

  const loadPromoCodes = async () => {
    const items = await apiFetch(`/api/growth/promo?guild_id=${guildId}`);
    if (!items) return;

    promoBody.innerHTML = "";
    items.forEach((item) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td><code>${item.code}</code></td>
        <td>${item.reward_type}</td>
        <td>${item.reward_value}</td>
        <td>${item.max_uses ?? "∞"}</td>
        <td>${item.per_user_limit ?? "∞"}</td>
        <td>${item.total_uses}</td>
        <td>${item.enabled ? "Включён" : "Выключен"}</td>
        <td>
          <button class="secondary" data-action="edit">Изменить</button>
          <button class="danger" data-action="delete">Удалить</button>
        </td>
      `;

      row.querySelector('[data-action="edit"]').addEventListener("click", async () => {
        const payload = {
          code: prompt("Код", item.code) ?? item.code,
          reward_type: prompt("Тип (fixed|percent|multiplier)", item.reward_type) ?? item.reward_type,
          reward_value: Number(prompt("Значение", String(item.reward_value)) ?? item.reward_value),
          max_uses: prompt("Макс. использований (пусто = без лимита)", item.max_uses ?? "") || null,
          per_user_limit:
            prompt("Лимит на пользователя (пусто = без лимита)", item.per_user_limit ?? "") || null,
          expires_at: prompt("Expires ISO (пусто = нет)", item.expires_at ?? "") || null,
          enabled: confirm("Промо-код должен быть включён?")
        };
        await apiFetch(`/api/growth/promo/${item.id}?guild_id=${guildId}`, {
          method: "PUT",
          body: JSON.stringify({
            ...payload,
            max_uses: payload.max_uses === null ? null : Number(payload.max_uses),
            per_user_limit: payload.per_user_limit === null ? null : Number(payload.per_user_limit),
          }),
        });
        await loadPromoCodes();
        await loadOverview();
      });

      row.querySelector('[data-action="delete"]').addEventListener("click", async () => {
        if (!confirm("Удалить промо-код?")) return;
        await apiFetch(`/api/growth/promo/${item.id}?guild_id=${guildId}`, { method: "DELETE" });
        await loadPromoCodes();
        await loadOverview();
      });

      promoBody.appendChild(row);
    });
  };

  const loadOverview = async () => {
    const overview = await apiFetch(`/api/growth/overview?guild_id=${guildId}`);
    if (!overview) return;

    overviewRoot.innerHTML = `
      <div class="stat"><strong>${overview.total_referrals}</strong><span>Всего рефералов</span></div>
      <div class="stat"><strong>${overview.active_referrals}</strong><span>Активных рефералов</span></div>
      <div class="stat"><strong>${overview.total_rewards_paid}</strong><span>Всего наград выплачено</span></div>
      <div class="stat"><strong>${overview.total_promo_redemptions}</strong><span>Активаций промо</span></div>
    `;

    topReferrersRoot.innerHTML = `
      <h5>Топ рефереров</h5>
      <ol>
        ${(overview.top_referrers || [])
          .map(
            (row) =>
              `<li><code>${row.user_id}</code> — ${row.total_referrals} / активных: ${row.active_referrals} / награды: ${row.total_rewards_paid}</li>`
          )
          .join("") || "<li>Нет данных</li>"}
      </ol>
    `;

    const most = overview.most_used_promo;
    mostUsedPromoRoot.innerHTML = `
      <h5>Самый используемый промо</h5>
      ${
        most
          ? `<p><code>${most.code}</code> — использований: <strong>${most.total_uses}</strong></p>`
          : "<p>Нет данных</p>"
      }
    `;
  };

  referralForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(referralForm);
    await apiFetch(`/api/growth/referral/settings?guild_id=${guildId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    alert("Настройки реферальной кампании сохранены");
  });

  promoForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToPayload(promoForm);
    await apiFetch(`/api/growth/promo?guild_id=${guildId}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    promoForm.reset();
    promoForm.enabled.checked = true;
    closeModal();
    await loadPromoCodes();
    await loadOverview();
  });

  openPromoModalButton?.addEventListener("click", openModal);
  cancelPromoModalButton?.addEventListener("click", closeModal);
  promoModal?.addEventListener("click", (event) => {
    if (event.target === promoModal) closeModal();
  });

  await loadReferralSettings();
  await loadPromoCodes();
  await loadOverview();
};
