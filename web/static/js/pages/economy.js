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
  const scale = period === 7 ? 1 : period === 30 ? 1.6 : 2.4;
  const generated = Math.round(42000 * scale);
  const removed = Math.round(36000 * scale);
  return {
    period,
    is_mocked: true,
    overview: {
      total_currency: Math.round(120000 * scale),
      average_balance: Math.round(750 * scale),
      median_balance: Math.round(430 * scale),
      active_users: Math.round(180 * scale),
    },
    flow: {
      generated,
      removed,
      net_flow: generated - removed,
      series: Array.from({ length: period === 7 ? 7 : 8 }).map((_, index) => ({
        label: period === 7 ? `День ${index + 1}` : `Неделя ${index + 1}`,
        generated: Math.round(generated / 8),
        removed: Math.round(removed / 8),
        net: Math.round((generated - removed) / 8),
      })),
    },
    top_activity: {
      earners: [
        { user_id: 1, user_name: "Neo", amount: Math.round(8200 * scale) },
        { user_id: 2, user_name: "Luna", amount: Math.round(7600 * scale) },
        { user_id: 3, user_name: "Kira", amount: Math.round(7100 * scale) },
        { user_id: 4, user_name: "Rin", amount: Math.round(6900 * scale) },
        { user_id: 5, user_name: "Mira", amount: Math.round(6600 * scale) },
      ],
      spenders: [
        { user_id: 6, user_name: "Dex", amount: Math.round(7900 * scale) },
        { user_id: 7, user_name: "Aki", amount: Math.round(7400 * scale) },
        { user_id: 8, user_name: "Zoe", amount: Math.round(7000 * scale) },
        { user_id: 9, user_name: "Kai", amount: Math.round(6700 * scale) },
        { user_id: 10, user_name: "Noa", amount: Math.round(6400 * scale) },
      ],
    },
    health: {
      inflation_indicator: "stable",
      sink_source_ratio: 0.86,
      warnings: [],
      interpretation:
        "Баланс между начислениями и списаниями выглядит стабильным.",
    },
  };
};

const formatNumber = (value) => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ru-RU").format(value);
};

const formatRatio = (value) => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
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
  const analyticsContent = document.getElementById("economyAnalyticsContent");
  const healthStatus = document.getElementById("economyHealthStatus");
  const interpretation = document.getElementById("economyInterpretation");
  const periodButtons = Array.from(document.querySelectorAll("[data-period]"));
  const overviewGrid = document.getElementById("economyOverview");
  const flowKpis = document.getElementById("economyFlowKpis");
  const flowChart = document.getElementById("economyFlowChart");
  const topEarners = document.getElementById("economyTopEarners");
  const topSpenders = document.getElementById("economyTopSpenders");
  const healthMetrics = document.getElementById("economyHealthMetrics");
  const warningsList = document.getElementById("economyWarnings");

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

  const renderCards = (container, data, formatter = formatNumber) => {
    if (!container) return;
    container.querySelectorAll("[data-value]").forEach((valueElement) => {
      const parent = valueElement.closest("[data-overview],[data-flow],[data-health]");
      if (!parent) return;
      const key =
        parent.dataset.overview || parent.dataset.flow || parent.dataset.health;
      valueElement.textContent = formatter(data?.[key]);
    });
  };

  const renderTopList = (container, entries) => {
    if (!container) return;
    container.innerHTML = "";
    if (!entries?.length) {
      const empty = document.createElement("li");
      empty.textContent = "Нет данных";
      container.appendChild(empty);
      return;
    }
    entries.forEach((entry) => {
      const item = document.createElement("li");
      item.innerHTML = `
        <span class="activity-name">${entry.user_name}</span>
        <span class="activity-amount">${formatNumber(entry.amount)}</span>
      `;
      container.appendChild(item);
    });
  };

  const renderFlowChart = (series) => {
    if (!flowChart) return;
    flowChart.innerHTML = "";
    if (!series?.length) {
      flowChart.textContent = "Нет данных для графика.";
      return;
    }
    const maxValue = Math.max(
      ...series.flatMap((point) => [point.generated, point.removed])
    );
    series.forEach((point) => {
      const row = document.createElement("div");
      row.className = "flow-row";
      const generatedWidth = maxValue
        ? Math.max(2, Math.round((point.generated / maxValue) * 100))
        : 0;
      const removedWidth = maxValue
        ? Math.max(2, Math.round((point.removed / maxValue) * 100))
        : 0;
      row.innerHTML = `
        <span class="flow-label">${point.label}</span>
        <div class="flow-bars">
          <span class="flow-bar flow-generated" style="width: ${generatedWidth}%"></span>
          <span class="flow-bar flow-removed" style="width: ${removedWidth}%"></span>
        </div>
        <span class="flow-value">${formatNumber(point.net)}</span>
      `;
      flowChart.appendChild(row);
    });
  };

  const renderWarnings = (warnings) => {
    if (!warningsList) return;
    warningsList.innerHTML = "";
    if (!warnings?.length) {
      const empty = document.createElement("div");
      empty.className = "warning-flag is-ok";
      empty.textContent = "Риски не обнаружены";
      warningsList.appendChild(empty);
      return;
    }
    warnings.forEach((warning) => {
      const item = document.createElement("div");
      item.className = `warning-flag severity-${warning.severity || "info"}`;
      item.textContent = warning.message;
      warningsList.appendChild(item);
    });
  };

  const renderAnalytics = (data) => {
    renderCards(overviewGrid, data?.overview);
    renderCards(flowKpis, data?.flow);
    renderCards(healthMetrics, data?.health, formatRatio);
    renderFlowChart(data?.flow?.series);
    renderTopList(topEarners, data?.top_activity?.earners);
    renderTopList(topSpenders, data?.top_activity?.spenders);
    renderWarnings(data?.health?.warnings);

    const status = data?.health?.inflation_indicator || "stable";
    const label = healthLabels[status] || healthLabels.stable;
    if (healthStatus) {
      healthStatus.textContent = label;
      healthStatus.className = `status-pill status-${status}`;
    }
    if (interpretation) {
      interpretation.textContent =
        data?.health?.interpretation ||
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
    setHidden(analyticsContent, true);
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
    setHidden(analyticsContent, false);
    setHidden(analyticsMock, !(isMock || data?.is_mocked));
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
