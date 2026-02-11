import { apiFetch } from "../api.js";

const currentMonth = () => {
  const now = new Date();
  const mm = String(now.getUTCMonth() + 1).padStart(2, "0");
  return `${now.getUTCFullYear()}-${mm}`;
};

const render = (goal) => {
  const badge = document.getElementById("monthlyGoalStatusBadge");
  const summary = document.getElementById("monthlyGoalSummary");
  const bar = document.getElementById("monthlyGoalProgressBar");
  if (!badge || !summary || !bar) return;

  if (!goal) {
    badge.textContent = "нет цели";
    summary.textContent = "На этот месяц цель не создана.";
    bar.style.width = "0%";
    return;
  }

  const percent = Math.max(0, Math.min(100, Number(goal.percent_completed || 0)));
  badge.textContent = goal.completed_at ? "completed" : goal.is_active ? "active" : "inactive";
  badge.style.background = goal.completed_at ? "#1f8f4f" : goal.is_active ? "#4f8cff" : "#6b7280";
  badge.style.color = "#fff";
  badge.style.padding = "0.2rem 0.55rem";
  badge.style.borderRadius = "999px";

  summary.textContent = `${goal.metric_type}: ${Number(goal.progress).toFixed(2)} / ${Number(goal.target_value).toFixed(2)} (${percent.toFixed(1)}%)`;
  bar.style.width = `${percent}%`;
};

export const initMonthlyGoals = async (guildId) => {
  const form = document.getElementById("monthlyGoalForm");
  if (!form) return;

  form.elements.month.value = currentMonth();

  let currentGoal = null;

  const load = async () => {
    const month = form.elements.month.value || currentMonth();
    currentGoal = await apiFetch(`/api/guilds/${guildId}/monthly-goal?month=${encodeURIComponent(month)}`);
    if (currentGoal) {
      form.elements.metric_type.value = currentGoal.metric_type;
      form.elements.target_value.value = currentGoal.target_value;
      form.elements.reward_role_id.value = currentGoal.reward_role_id;
      form.elements.min_user_contribution.value = currentGoal.min_user_contribution;
      form.elements.is_active.checked = Boolean(currentGoal.is_active);
    }
    render(currentGoal);
  };

  form.elements.month.addEventListener("change", load);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      month: form.elements.month.value,
      metric_type: form.elements.metric_type.value,
      target_value: Number(form.elements.target_value.value),
      reward_role_id: Number(form.elements.reward_role_id.value),
      min_user_contribution: Number(form.elements.min_user_contribution.value || 0),
      is_active: form.elements.is_active.checked,
    };

    if (currentGoal?.id) {
      await apiFetch(`/api/guilds/${guildId}/monthly-goal/${currentGoal.id}`, {
        method: "PUT",
        body: JSON.stringify({
          metric_type: payload.metric_type,
          target_value: payload.target_value,
          reward_role_id: payload.reward_role_id,
          min_user_contribution: payload.min_user_contribution,
          is_active: payload.is_active,
        }),
      });
    } else {
      await apiFetch(`/api/guilds/${guildId}/monthly-goal`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }

    await load();
  });

  await load();
};
