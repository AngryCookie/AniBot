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
    window.location.href = "/login.html";
    return null;
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .catch(() => ({ detail: "Request failed" }));
    throw new Error(detail.detail || "Request failed");
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
