import {
  getLevelingSettings,
  resetLevelingSettings,
  updateLevelingSettings,
} from "../api.js";

const fieldNames = [
  "enabled",
  "xp_per_message",
  "xp_cooldown_seconds",
  "announce_level_up",
  "rewards_roles_enabled",
];

const defaults = {
  enabled: false,
  xp_per_message: 10,
  xp_cooldown_seconds: 60,
  announce_level_up: true,
  rewards_roles_enabled: false,
};

const setHidden = (element, isHidden) => {
  if (!element) return;
  element.classList.toggle("hidden", isHidden);
};

const readFormValues = (form) => {
  const values = {};
  fieldNames.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (!input) return;
    if (input.type === "checkbox") {
      values[name] = input.checked;
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
    if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else {
      input.value = value ?? "";
    }
  });
};

const isDirty = (current, initial) =>
  fieldNames.some((name) => current[name] !== initial[name]);

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

  modal?.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  await loadSettings();
};
