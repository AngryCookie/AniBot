let apiErrorHandler = null;

export const setApiErrorHandler = (handler) => {
  apiErrorHandler = typeof handler === "function" ? handler : null;
};

export const apiFetch = async (url, options = {}) => {
  const response = await fetch(url, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 401) {
    const detail = await response.json().catch(() => ({}));
    const message = detail.message || detail.detail || "Сессия истекла, войдите снова";
    const error = new Error(message);
    error.status = 401;
    if (apiErrorHandler) {
      apiErrorHandler(message, 401);
    }
    throw error;
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const message = detail.message || detail.detail || "Request failed";
    if (apiErrorHandler) {
      apiErrorHandler(message, response.status);
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return response.text();
  }

  return response.json();
};

export const getLevelingSettings = (guildId) =>
  apiFetch(`/api/guilds/${guildId}/leveling`);

export const updateLevelingSettings = (guildId, payload) =>
  apiFetch(`/api/guilds/${guildId}/leveling`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });

export const resetLevelingSettings = (guildId) =>
  apiFetch(`/api/guilds/${guildId}/leveling/reset`, {
    method: "POST",
  });

export const getEconomySettings = (guildId) =>
  apiFetch(`/api/guilds/${guildId}/economy`);

export const updateEconomySettings = (guildId, payload) =>
  apiFetch(`/api/guilds/${guildId}/economy`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });

export const resetEconomySettings = (guildId) =>
  apiFetch(`/api/guilds/${guildId}/economy/reset`, {
    method: "POST",
  });

export const getEconomyAnalytics = (guildId, period) =>
  apiFetch(`/api/guilds/${guildId}/economy/analytics?period=${period}`);

export const getEconomyInsights = (guildId, period) =>
  apiFetch(`/api/guilds/${guildId}/economy/insights?period=${period}`);


export const getEconomyRecommendations = (guildId, days) =>
  apiFetch(`/api/guilds/${guildId}/economy/recommendations?days=${days}`);
