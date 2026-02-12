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

export const initReports = async (guildId) => {
  const form = document.getElementById("reportsForm");
  if (!form || !guildId) return;

  const data = await apiFetch(`/api/guilds/${guildId}/reports`);

  form.querySelectorAll("input").forEach((input) => {
    const path = input.dataset.path || input.name;
    if (!path) return;
    const value = getByPath(data, path);
    if (input.type === "checkbox") input.checked = Boolean(value);
    else input.value = value ?? "";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    form.querySelectorAll("input").forEach((input) => {
      const path = input.dataset.path || input.name;
      if (!path) return;
      const value = input.type === "checkbox" ? Boolean(input.checked) : input.value === "" ? null : Number.isNaN(Number(input.value)) ? input.value : Number(input.value);
      setByPath(payload, path, value);
    });

    await apiFetch(`/api/guilds/${guildId}/reports`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    showToast("Reports настройки сохранены", "success");
  });

  const dryRunBtn = document.getElementById("reportsDryRunBtn");
  const output = document.getElementById("reportsDryRunOut");
  dryRunBtn?.addEventListener("click", async () => {
    const result = await apiFetch(`/api/guilds/${guildId}/reports/monthly/dry-run?range=prev_month`, { method: "POST" });
    if (output) {
      output.classList.remove("hidden");
      output.textContent = JSON.stringify(result.payload, null, 2);
    }
  });

  const quarterlyDryRunBtn = document.getElementById("reportsQuarterlyDryRunBtn");
  const quarterlyOutput = document.getElementById("reportsQuarterlyDryRunOut");
  quarterlyDryRunBtn?.addEventListener("click", async () => {
    const result = await apiFetch(`/api/guilds/${guildId}/reports/quarterly/dry-run?quarter=prev`, { method: "POST" });
    if (quarterlyOutput) {
      quarterlyOutput.classList.remove("hidden");
      quarterlyOutput.textContent = JSON.stringify(result.payload, null, 2);
    }
  });

  const yearlyDryRunBtn = document.getElementById("reportsYearlyDryRunBtn");
  const yearlyOutput = document.getElementById("reportsYearlyDryRunOut");
  yearlyDryRunBtn?.addEventListener("click", async () => {
    const result = await apiFetch(`/api/guilds/${guildId}/reports/yearly/dry-run?range=prev_year`, { method: "POST" });
    if (yearlyOutput) {
      yearlyOutput.classList.remove("hidden");
      yearlyOutput.textContent = JSON.stringify(result.payload, null, 2);
    }
  });

};
