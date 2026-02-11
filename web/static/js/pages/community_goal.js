import { apiFetch } from "../api.js";

const toLocalInputValue = (date) => {
  const pad = (v) => String(v).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const toIsoUtc = (localValue) => {
  const date = new Date(localValue);
  return date.toISOString();
};

const setMonthDefaults = (form) => {
  const now = new Date();
  const starts = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1, 0, 0, 0));
  const ends = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0, 23, 59, 59));
  form.elements.starts_at.value = toLocalInputValue(new Date(starts));
  form.elements.ends_at.value = toLocalInputValue(new Date(ends));
};

const renderGoal = (goal) => {
  const status = document.getElementById("communityGoalStatus");
  const panel = document.getElementById("communityGoalProgress");
  if (!status || !panel) return;

  if (!goal) {
    status.textContent = "Цель сообщества пока не создана.";
    panel.classList.add("hidden");
    return;
  }

  status.textContent = `Goal #${goal.id} (${goal.metric_type})`;
  panel.classList.remove("hidden");

  const target = Number(goal.target_value || 0);
  const current = Number(goal.current_value || 0);
  const remaining = Math.max(0, target - current);
  const percent = target > 0 ? Math.min(100, Math.round((current / target) * 100)) : 0;

  const endsAt = new Date(goal.ends_at);
  const now = new Date();
  const daysLeft = Math.max(0, Math.ceil((endsAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)));

  document.getElementById("communityGoalTarget").textContent = String(target);
  document.getElementById("communityGoalCurrent").textContent = String(current);
  document.getElementById("communityGoalRemaining").textContent = String(remaining);
  document.getElementById("communityGoalDaysLeft").textContent = String(daysLeft);

  const badge = document.getElementById("communityGoalBadge");
  if (badge) {
    badge.textContent = goal.status;
    badge.style.background = goal.status === "completed" ? "#1f8f4f" : goal.status === "failed" ? "#9a2d2d" : "#4f8cff";
    badge.style.color = "#fff";
    badge.style.padding = "0.15rem 0.5rem";
    badge.style.borderRadius = "999px";
    badge.style.fontSize = "0.8rem";
  }

  const bar = document.getElementById("communityGoalProgressBar");
  if (bar) {
    bar.style.width = `${percent}%`;
  }
};

export const initCommunityGoal = async (guildId) => {
  const form = document.getElementById("communityGoalForm");
  const evaluateBtn = document.getElementById("communityGoalEvaluateBtn");
  if (!form) return;

  setMonthDefaults(form);

  const load = async () => {
    const goal = await apiFetch(`/api/guilds/${guildId}/community-goal`);
    if (goal) {
      form.elements.metric_type.value = goal.metric_type;
      form.elements.target_value.value = goal.target_value;
      form.elements.starts_at.value = toLocalInputValue(new Date(goal.starts_at));
      form.elements.ends_at.value = toLocalInputValue(new Date(goal.ends_at));
      form.elements.min_participation_threshold.value = goal.min_participation_threshold;
      form.elements.reward_role_id.value = goal.reward_role_id || "";
    }
    renderGoal(goal);
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      metric_type: form.elements.metric_type.value,
      target_value: Number(form.elements.target_value.value),
      starts_at: toIsoUtc(form.elements.starts_at.value),
      ends_at: toIsoUtc(form.elements.ends_at.value),
      min_participation_threshold: Number(form.elements.min_participation_threshold.value || 0),
      reward_role_id: form.elements.reward_role_id.value ? Number(form.elements.reward_role_id.value) : null,
    };

    try {
      await apiFetch(`/api/guilds/${guildId}/community-goal`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    } catch {
      await apiFetch(`/api/guilds/${guildId}/community-goal`, {
        method: "PUT",
        body: JSON.stringify({ ...payload, status: "active" }),
      });
    }
    await load();
  });

  if (evaluateBtn) {
    evaluateBtn.addEventListener("click", async () => {
      await apiFetch(`/api/guilds/${guildId}/community-goal/evaluate`, { method: "POST" });
      await load();
    });
  }

  await load();
};
