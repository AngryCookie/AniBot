import { apiFetch } from "../api.js";

const renderCurrent = (goal) => {
  const summary = document.getElementById("monthlyGoalSummary");
  const bar = document.getElementById("monthlyGoalProgressBar");
  const status = document.getElementById("monthlyGoalStatusBadge");
  if (!summary || !bar || !status) return;
  if (!goal) {
    summary.textContent = "Текущая цель отсутствует";
    bar.style.width = "0%";
    status.textContent = "—";
    return;
  }
  status.textContent = goal.status;
  summary.textContent = `${goal.goal_type}: ${goal.progress_value}/${goal.target_value}, участников: ${goal.eligible_count}, дней осталось: ${goal.days_left}`;
  bar.style.width = `${Math.max(0, Math.min(100, Number(goal.percent_completed || 0)))}%`;
};

const renderTemplates = (templates) => {
  const box = document.getElementById("goalTemplatesList");
  if (!box) return;
  box.innerHTML = templates.map(t => `<div class="notice">#${t.id} <b>${t.name}</b> (${t.goal_type}) → ${t.target_value}; eligibility: ${t.eligibility_type} >= ${t.eligibility_min_value}</div>`).join("") || "<div class='notice'>Нет шаблонов</div>";
};

export const initMonthlyGoals = async (guildId) => {
  const settingsForm = document.getElementById("monthlyGoalsSettingsForm");
  const templateForm = document.getElementById("monthlyGoalTemplateForm");
  const dryRunBtn = document.getElementById("monthlyGoalsDryRun");
  const forceCloseBtn = document.getElementById("monthlyGoalsForceClose");

  const load = async () => {
    const [settings, templates, current] = await Promise.all([
      apiFetch(`/api/guilds/${guildId}/monthly-goals/settings`),
      apiFetch(`/api/guilds/${guildId}/monthly-goals/templates`),
      apiFetch(`/api/guilds/${guildId}/monthly-goals/current`),
    ]);
    if (settingsForm && settings) {
      settingsForm.elements.enabled.checked = !!settings.enabled;
      settingsForm.elements.auto_generate.checked = !!settings.auto_generate;
      settingsForm.elements.announce_channel_id.value = settings.announce_channel_id || "";
      settingsForm.elements.reward_role_id.value = settings.reward_role_id || "";
      settingsForm.elements.close_day.value = settings.close_day;
      settingsForm.elements.close_hour.value = settings.close_hour;
      settingsForm.elements.timezone.value = settings.timezone || "UTC";
      settingsForm.elements.default_template_id.value = settings.default_template_id || "";
    }
    renderTemplates(templates || []);
    renderCurrent(current);
  };

  settingsForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      enabled: settingsForm.elements.enabled.checked,
      auto_generate: settingsForm.elements.auto_generate.checked,
      announce_channel_id: settingsForm.elements.announce_channel_id.value ? Number(settingsForm.elements.announce_channel_id.value) : null,
      reward_role_id: settingsForm.elements.reward_role_id.value ? Number(settingsForm.elements.reward_role_id.value) : null,
      close_day: Number(settingsForm.elements.close_day.value),
      close_hour: Number(settingsForm.elements.close_hour.value),
      timezone: settingsForm.elements.timezone.value || "UTC",
      default_template_id: settingsForm.elements.default_template_id.value ? Number(settingsForm.elements.default_template_id.value) : null,
    };
    await apiFetch(`/api/guilds/${guildId}/monthly-goals/settings`, { method: "PUT", body: JSON.stringify(payload) });
    await load();
  });

  templateForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      name: templateForm.elements.name.value,
      description: templateForm.elements.description.value || "",
      goal_type: templateForm.elements.goal_type.value,
      target_value: Number(templateForm.elements.target_value.value),
      eligibility_type: templateForm.elements.eligibility_type.value,
      eligibility_min_value: Number(templateForm.elements.eligibility_min_value.value),
      enabled: templateForm.elements.enabled.checked,
    };
    await apiFetch(`/api/guilds/${guildId}/monthly-goals/templates`, { method: "POST", body: JSON.stringify(payload) });
    templateForm.reset();
    await load();
  });

  dryRunBtn?.addEventListener("click", async () => {
    const current = await apiFetch(`/api/guilds/${guildId}/monthly-goals/current`);
    alert(`Dry-run: eligible=${current?.eligible_count || 0}, progress=${current?.progress_value || 0}/${current?.target_value || 0}`);
  });

  forceCloseBtn?.addEventListener("click", async () => {
    const result = await apiFetch(`/api/guilds/${guildId}/monthly-goals/current/force-close`, { method: "POST" });
    alert(`force-close: ${JSON.stringify(result)}`);
    await load();
  });

  await load();
};
