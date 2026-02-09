import {
  getEconomyAnalytics,
  getEconomySettings,
  resetEconomySettings,
  updateEconomySettings,
} from "../api.js";

const fieldNames = [
  "enabled",
  "daily_amount",
  "max_daily_claims",
  "allow_transfers",
  "tax_rate_percent",
];

const defaults = {
  enabled: false,
  daily_amount: 100,
  max_daily_claims: 1,
  allow_transfers: true,
  tax_rate_percent: 5,
};

const healthLabels = {
  stable: "Стабильная",
  inflating: "Инфляция",
  deflating: "Дефляция",
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

const getMockAnalytics = (period) => {
  // TODO: заменить мок-данные на реальные значения с backend эндпоинта аналитики.
  const base = period === 7 ? 1 : period === 30 ? 4 : 9;
  return {
    total_currency: 125000 * base,
    minted: 42000 * base,
    sunk: 36000 * base,
    net_flow: 6000 * base,
    active_users: 180 * base,
    health_status: base > 4 ? "inflating" : "stable",
    interpretation:
      base > 4
        ? "Рост эмиссии опережает списания. Рассмотрите усиление валютных sink-механик."
        : "Баланс между начислениями и списаниями выглядит стабильным.",
  };
};

const formatNumber = (value) => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ru-RU").format(value);
};

const setActiveTab = (tabButtons, panels, target) => {
  tabButtons.forEach((button) => {
    const isActive = button.dataset.economyTab === target;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
  });
  panels.forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.economyPanel !== target);
  });
};

const setActivePeriod = (periodButtons, period) => {
  periodButtons.forEach((button) => {
    button.classList.toggle("is-active", Number(button.dataset.period) === period);
  });
};

export const initEconomy = async (guildId) => {
  const form = document.getElementById("economyForm");
  if (!form) return;

  const loading = document.getElementById("economyLoading");
  const error = document.getElementById("economyError");
  const success = document.getElementById("economySuccess");
  const empty = document.getElementById("economyEmpty");
  const dependentGroup = document.getElementById("economyDependent");
  const transferGroup = document.getElementById("economyTransfersGroup");
  const dirtyNotice = document.getElementById("economyDirty");
  const saveButton = document.getElementById("economySave");
  const resetButton = document.getElementById("economyReset");
  const modal = document.getElementById("economyResetModal");
  const modalCancel = modal?.querySelector("[data-action='cancel']");
  const modalConfirm = modal?.querySelector("[data-action='confirm']");

  const tabButtons = Array.from(document.querySelectorAll("[data-economy-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-economy-panel]"));

  const analyticsLoading = document.getElementById("economyAnalyticsLoading");
  const analyticsError = document.getElementById("economyAnalyticsError");
  const analyticsEmpty = document.getElementById("economyAnalyticsEmpty");
  const analyticsMock = document.getElementById("economyAnalyticsMock");
  const analyticsKpis = document.getElementById("economyAnalyticsKpis");
  const healthStatus = document.getElementById("economyHealthStatus");
  const interpretation = document.getElementById("economyInterpretation");
  const periodButtons = Array.from(document.querySelectorAll("[data-period]"));

  let initialValues = readFormValues(form);
  let isSubmitting = false;
  let analyticsLoaded = false;
  let currentPeriod = 7;

  const setDependentState = (isEnabled) => {
    if (!dependentGroup) return;
    dependentGroup.disabled = !isEnabled;
    dependentGroup.classList.toggle("is-disabled", !isEnabled);
  };

  const setTransferState = (isEnabled) => {
    if (!transferGroup) return;
    transferGroup.disabled = !isEnabled;
    transferGroup.classList.toggle("is-disabled", !isEnabled);
  };

  const setFormDisabled = (disabled) => {
    Array.from(form.elements).forEach((element) => {
      element.disabled = disabled;
    });
    if (!disabled) {
      const enabledInput = form.elements.namedItem("enabled");
      const transfersInput = form.elements.namedItem("allow_transfers");
      if (enabledInput) {
        setDependentState(enabledInput.checked);
      }
      if (transfersInput) {
        setTransferState(enabledInput?.checked && transfersInput.checked);
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
      const data = await getEconomySettings(guildId);
      if (!data) {
        setHidden(empty, false);
        return;
      }
      fillForm(form, data);
      initialValues = readFormValues(form);
      updateDirtyState();
      setDependentState(Boolean(initialValues.enabled));
      setTransferState(Boolean(initialValues.enabled && initialValues.allow_transfers));
    } catch (err) {
      showError(err?.message || "Не удалось загрузить настройки");
    } finally {
      setLoading(false);
      setFormDisabled(false);
    }
  };

  const renderAnalytics = (data) => {
    if (!analyticsKpis) return;
    analyticsKpis.querySelectorAll("[data-kpi]").forEach((card) => {
      const key = card.dataset.kpi;
      const valueElement = card.querySelector("[data-kpi-value]");
      if (!valueElement) return;
      valueElement.textContent = formatNumber(data?.[key]);
    });

    const status = data?.health_status || "stable";
    const label = healthLabels[status] || healthLabels.stable;
    if (healthStatus) {
      healthStatus.textContent = label;
      healthStatus.className = `status-pill status-${status}`;
    }
    if (interpretation) {
      interpretation.textContent =
        data?.interpretation ||
        "Добавьте анализ поведения валюты и распределения активных пользователей.";
    }
  };

  const loadAnalytics = async (period) => {
    if (!guildId) {
      setHidden(analyticsError, false);
      if (analyticsError) {
        analyticsError.textContent = "Не выбран сервер.";
      }
      return;
    }

    setHidden(analyticsError, true);
    setHidden(analyticsEmpty, true);
    setHidden(analyticsKpis, true);
    setHidden(analyticsMock, true);
    setHidden(analyticsLoading, false);

    let data = null;
    let isMock = false;

    try {
      data = await getEconomyAnalytics(guildId, period);
    } catch (err) {
      data = getMockAnalytics(period);
      isMock = true;
    }

    setHidden(analyticsLoading, true);

    if (!data) {
      setHidden(analyticsEmpty, false);
      return;
    }

    renderAnalytics(data);
    setHidden(analyticsKpis, false);
    setHidden(analyticsMock, !isMock);
  };

  form.addEventListener("input", (event) => {
    if (event.target?.name === "enabled") {
      setDependentState(event.target.checked);
      const transferToggle = form.elements.namedItem("allow_transfers");
      setTransferState(event.target.checked && Boolean(transferToggle?.checked));
    }
    if (event.target?.name === "allow_transfers") {
      const enabledInput = form.elements.namedItem("enabled");
      setTransferState(Boolean(enabledInput?.checked) && event.target.checked);
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
      await updateEconomySettings(guildId, current);
      await loadSettings();
      showSuccess("Настройки экономики сохранены.");
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
      await resetEconomySettings(guildId);
      await loadSettings();
      showSuccess("Настройки экономики сброшены.");
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

  tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.economyTab;
      if (!tab) return;
      setActiveTab(tabButtons, panels, tab);
      if (tab === "analytics" && !analyticsLoaded) {
        analyticsLoaded = true;
        loadAnalytics(currentPeriod);
      }
    });
  });

  periodButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const nextPeriod = Number(button.dataset.period);
      if (!nextPeriod || nextPeriod === currentPeriod) return;
      currentPeriod = nextPeriod;
      setActivePeriod(periodButtons, currentPeriod);
      loadAnalytics(currentPeriod);
    });
  });

  setActivePeriod(periodButtons, currentPeriod);
  await loadSettings();
};
