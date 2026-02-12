import { apiFetch } from "../api.js";
import { showToast } from "../ui.js";

const rowTemplate = (item = { type: "playing", text: "" }) => {
  const row = document.createElement("div");
  row.className = "row gap-sm";
  row.innerHTML = `
    <select data-field="type">
      <option value="playing">playing</option>
      <option value="watching">watching</option>
      <option value="listening">listening</option>
    </select>
    <input data-field="text" type="text" maxlength="128" placeholder="Текст activity" style="min-width:320px;" />
    <button type="button" class="danger" data-action="remove">×</button>
  `;
  row.querySelector('[data-field="type"]').value = item.type || "playing";
  row.querySelector('[data-field="text"]').value = item.text || "";
  row.querySelector('[data-action="remove"]').addEventListener("click", () => row.remove());
  return row;
};

export const initPresence = async () => {
  const form = document.getElementById("presenceForm");
  if (!form) return;

  const templatesHost = document.getElementById("presenceTemplates");
  const addBtn = document.getElementById("presenceAddTemplate");
  const previewBtn = document.getElementById("presencePreviewBtn");
  const previewOut = document.getElementById("presencePreviewOut");

  const fill = (data) => {
    form.elements.namedItem("enabled").checked = Boolean(data.enabled);
    form.elements.namedItem("interval_seconds").value = Number(data.interval_seconds || 300);
    form.elements.namedItem("mode").value = data.mode || "primary_guild";
    form.elements.namedItem("primary_guild_id").value = data.primary_guild_id || "";
    templatesHost.innerHTML = "";
    (data.templates || []).forEach((item) => templatesHost.appendChild(rowTemplate(item)));
  };

  const toPayload = () => ({
    enabled: form.elements.namedItem("enabled").checked,
    interval_seconds: Number(form.elements.namedItem("interval_seconds").value || 300),
    mode: form.elements.namedItem("mode").value,
    primary_guild_id: form.elements.namedItem("primary_guild_id").value
      ? Number(form.elements.namedItem("primary_guild_id").value)
      : null,
    templates: Array.from(templatesHost.children)
      .map((row) => ({
        type: row.querySelector('[data-field="type"]').value,
        text: row.querySelector('[data-field="text"]').value.trim(),
      }))
      .filter((item) => item.text.length > 0),
  });

  fill(await apiFetch("/api/presence/settings"));

  addBtn.addEventListener("click", () => templatesHost.appendChild(rowTemplate()));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await apiFetch("/api/presence/settings", { method: "PUT", body: JSON.stringify(toPayload()) });
    showToast("Presence настройки сохранены", "success");
  });

  previewBtn.addEventListener("click", async () => {
    const guildId = form.elements.namedItem("primary_guild_id").value;
    const qs = guildId ? `?guild_id=${Number(guildId)}` : "";
    const data = await apiFetch(`/api/presence/preview${qs}`, { method: "POST" });
    previewOut.classList.remove("hidden");
    previewOut.textContent = (data.rendered || []).join("\n") || "Нет шаблонов для рендера";
  });
};
