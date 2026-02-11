export const showToast = (message, type = "success") => {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  window.setTimeout(() => {
    toast.classList.add("toast-hide");
    window.setTimeout(() => toast.remove(), 220);
  }, 2600);
};

export const confirmModal = (title, text) =>
  new Promise((resolve) => {
    const root = document.getElementById("confirmModalRoot");
    if (!root) {
      resolve(window.confirm(`${title}\n\n${text}`));
      return;
    }

    root.innerHTML = `
      <div class="modal-backdrop" role="dialog" aria-modal="true">
        <div class="modal-card">
          <h4>${title}</h4>
          <p class="field-hint">${text}</p>
          <div class="modal-actions">
            <button type="button" class="secondary" data-confirm="cancel">Отмена</button>
            <button type="button" class="danger" data-confirm="ok">Подтвердить</button>
          </div>
        </div>
      </div>
    `;

    const close = (value) => {
      root.innerHTML = "";
      resolve(value);
    };

    root.querySelector('[data-confirm="cancel"]')?.addEventListener("click", () => close(false));
    root.querySelector('[data-confirm="ok"]')?.addEventListener("click", () => close(true));
    root.querySelector(".modal-backdrop")?.addEventListener("click", (event) => {
      if (event.target.classList.contains("modal-backdrop")) close(false);
    });
  });

export const setLoading = (target, isLoading = true) => {
  if (!target) return;
  if (typeof target === "string") {
    const node = document.querySelector(target);
    if (!node) return;
    node.classList.toggle("hidden", !isLoading);
    return;
  }

  if (target instanceof HTMLElement) {
    if (target.matches("button")) {
      target.disabled = isLoading;
      if (!target.dataset.defaultText) {
        target.dataset.defaultText = target.textContent || "";
      }
      target.textContent = isLoading ? "Сохранение..." : target.dataset.defaultText;
      return;
    }
    target.classList.toggle("hidden", !isLoading);
  }
};

export const validateForm = (form) => {
  if (!(form instanceof HTMLFormElement)) return false;
  let valid = true;
  Array.from(form.elements).forEach((field) => {
    if (!(field instanceof HTMLInputElement || field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement)) {
      return;
    }
    field.setCustomValidity("");
    if (field.willValidate && !field.checkValidity()) {
      valid = false;
    }
  });
  if (!valid) form.reportValidity();
  return valid;
};

export const withErrorBoundary = async (handler, onError) => {
  try {
    await handler();
  } catch (error) {
    const message = error?.message || "Произошла ошибка интерфейса";
    if (typeof onError === "function") {
      onError(message);
      return;
    }
    showToast(message, "error");
  }
};
