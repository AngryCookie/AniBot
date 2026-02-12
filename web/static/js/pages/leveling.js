import {
  getLevelingSettings,
  resetLevelingSettings,
  updateLevelingSettings,
} from "../api.js";

const fieldNames = [
  "enabled",
  "message_xp_enabled",
  "message_xp_min_length",
  "message_xp_cooldown_seconds",
  "message_xp_min",
  "message_xp_max",
  "message_ignore_channels",
  "voice_xp_enabled",
  "voice_xp_per_minute",
  "voice_ignore_channels",
  "voice_ignore_self_deaf",
  "voice_ignore_self_mute",
  "level_curve_type",
  "level_curve_a",
  "level_curve_b",
  "role_rewards_enabled",
  "announce_level_up",
  "level_up_channel_id",
  "announce_cooldown_seconds",
];

const defaults = {
  enabled: true,
  message_xp_enabled: true,
  message_xp_min_length: 6,
  message_xp_cooldown_seconds: 45,
  message_xp_min: 5,
  message_xp_max: 10,
  message_ignore_channels: "",
  voice_xp_enabled: true,
  voice_xp_per_minute: 1,
  voice_ignore_channels: "",
  voice_ignore_self_deaf: true,
  voice_ignore_self_mute: false,
  level_curve_type: "quadratic",
  level_curve_a: 50,
  level_curve_b: 50,
  role_rewards_enabled: true,
  announce_level_up: true,
  level_up_channel_id: null,
  announce_cooldown_seconds: 60,
};

const listFields = new Set(["message_ignore_channels", "voice_ignore_channels"]);

const setHidden = (element, isHidden) => {
  if (!element) return;
  element.classList.toggle("hidden", isHidden);
};

const parseChannels = (value) =>
  String(value || "")
    .split(",")
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => Number(chunk))
    .filter((num) => Number.isInteger(num) && num > 0);

const readFormValues = (form) => {
  const values = {};
  fieldNames.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (!input) return;
    if (listFields.has(name)) {
      values[name] = parseChannels(input.value);
      return;
    }
    if (input.type === "checkbox") {
      values[name] = input.checked;
      return;
    }
    if (name === "level_curve_type") {
      values[name] = input.value || "quadratic";
      return;
    }
    const parsed = input.value === "" ? null : Number(input.value);
    values[name] = Number.isNaN(parsed) ? null : parsed;
  });
  return values;
};

const fillForm = (form, data) => {
  const merged = { ...defaults, ...(data || {}) };
  fieldNames.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (!input) return;
    const value = merged[name];
    if (listFields.has(name)) {
      input.value = Array.isArray(value) ? value.join(",") : "";
    } else if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else {
      input.value = value ?? "";
    }
  });
};

const isDirty = (current, initial) =>
  fieldNames.some((name) => JSON.stringify(current[name]) !== JSON.stringify(initial[name]));

export const initLeveling = async (guildId) => {
  const form = document.getElementById("levelingForm");
  if (!form) return;

  const loading = document.getElementById("levelingLoading");
  const error = document.getElementById("levelingError");
  const success = document.getElementById("levelingSuccess");
  const empty = document.getElementById("levelingEmpty");
  const dependentGroup = document.getElementById("levelingDependent");
  const dirtyNotice = document.getElementById("levelingDirty");
  const saveButton = document.getElementById("levelingSave");
  const resetButton = document.getElementById("levelingReset");
  const modal = document.getElementById("levelingResetModal");
  const modalCancel = modal?.querySelector("[data-action='cancel']");
  const modalConfirm = modal?.querySelector("[data-action='confirm']");

  let initialValues = readFormValues(form);
  let isSubmitting = false;

  const setDependentState = (isEnabled) => {
    if (!dependentGroup) return;
    dependentGroup.disabled = !isEnabled;
    dependentGroup.classList.toggle("is-disabled", !isEnabled);
  };

  const setFormDisabled = (disabled) => {
    Array.from(form.elements).forEach((element) => {
      element.disabled = disabled;
    });
    if (!disabled) {
      const enabledInput = form.elements.namedItem("enabled");
      if (enabledInput) {
        setDependentState(enabledInput.checked);
      }
    }
    if (resetButton) {
      resetButton.disabled = disabled || isSubmitting;
    }
  };

  const updateDirtyState = () => {
    const current = readFormValues(form);
    const dirty = isDirty(current, initialValues);
    setHidden(dirtyNotice, !dirty);
    if (saveButton) {
      saveButton.disabled = !dirty || isSubmitting;
    }
  };

  const showError = (message) => {
    if (!error) return;
    error.textContent = message;
    setHidden(error, !message);
  };

  const showSuccess = (message) => {
    if (!success) return;
    success.textContent = message;
    setHidden(success, !message);
  };

  const setLoading = (isLoading) => {
    setHidden(loading, !isLoading);
    if (isLoading) {
      setFormDisabled(true);
    }
  };

  const closeModal = () => {
    if (!modal) return;
    modal.classList.add("hidden");
  };

  const openModal = () => {
    if (!modal) return;
    modal.classList.remove("hidden");
  };

  const loadSettings = async () => {
    if (!guildId) {
      showError("Не выбран сервер.");
      setHidden(empty, true);
      return;
    }

    showError("");
    showSuccess("");
    setHidden(empty, true);
    setLoading(true);

    try {
      const data = await getLevelingSettings(guildId);
      if (!data) {
        setHidden(empty, false);
        return;
      }
      fillForm(form, data);
      initialValues = readFormValues(form);
      updateDirtyState();
      setDependentState(Boolean(initialValues.enabled));
    } catch (err) {
      showError(err?.message || "Не удалось загрузить настройки");
    } finally {
      setLoading(false);
      setFormDisabled(false);
    }
  };

  form.addEventListener("input", (event) => {
    if (event.target?.name === "enabled") {
      setDependentState(event.target.checked);
    }
    showSuccess("");
    updateDirtyState();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isSubmitting) return;
    const current = readFormValues(form);
    if (!isDirty(current, initialValues)) return;

    isSubmitting = true;
    updateDirtyState();
    setFormDisabled(true);
    showError("");
    showSuccess("");

    try {
      await updateLevelingSettings(guildId, current);
      await loadSettings();
      showSuccess("Настройки уровней сохранены.");
    } catch (err) {
      showError(err?.message || "Не удалось сохранить настройки");
    } finally {
      isSubmitting = false;
      updateDirtyState();
      setFormDisabled(false);
    }
  });

  if (resetButton) {
    resetButton.addEventListener("click", () => {
      showSuccess("");
      openModal();
    });
  }

  modalCancel?.addEventListener("click", closeModal);
  modalConfirm?.addEventListener("click", async () => {
    if (isSubmitting) return;
    isSubmitting = true;
    closeModal();
    updateDirtyState();
    setFormDisabled(true);
    showError("");
    showSuccess("");

    try {
      await resetLevelingSettings(guildId);
      await loadSettings();
      showSuccess("Настройки уровней сброшены.");
    } catch (err) {
      showError(err?.message || "Не удалось сбросить настройки");
    } finally {
      isSubmitting = false;
      updateDirtyState();
      setFormDisabled(false);
    }
  });

  await loadSettings();
};
