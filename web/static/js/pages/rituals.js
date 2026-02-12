import { apiFetch } from "../api.js";
import { showToast } from "../ui.js";

const setByPath = (obj, path, value) => {
  const parts = path.split(".");
  let ref = obj;
  for (let i = 0; i < parts.length - 1; i += 1) {
    if (!ref[parts[i]] || typeof ref[parts[i]] !== "object") ref[parts[i]] = {};
    ref = ref[parts[i]];
  }
  ref[parts[parts.length - 1]] = value;
};

const getByPath = (obj, path) => path.split(".").reduce((acc, key) => (acc ? acc[key] : undefined), obj);

export const initRituals = async (guildId) => {
  const form = document.getElementById("ritualsForm");
  if (!form || !guildId) return;

  const data = await apiFetch(`/api/guilds/${guildId}/rituals`);
  form.querySelectorAll("input").forEach((input) => {
    const path = input.dataset.path;
    if (!path) return;
    const value = getByPath(data, path);
    if (input.type === "checkbox") input.checked = Boolean(value);
    else input.value = value ?? "";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    form.querySelectorAll("input").forEach((input) => {
      const path = input.dataset.path;
      if (!path) return;
      const value = input.type === "checkbox"
        ? Boolean(input.checked)
        : input.value === ""
          ? null
          : Number.isNaN(Number(input.value))
            ? input.value
            : Number(input.value);
      setByPath(payload, path, value);
    });
    await apiFetch(`/api/guilds/${guildId}/rituals`, { method: "PUT", body: JSON.stringify(payload) });
    showToast("Rituals настройки сохранены", "success");
  });
};
