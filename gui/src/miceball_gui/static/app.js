const sectionNames = {
  setup: "Setup",
  session: "Session",
  parameters: "Parameters",
  experiment: "Experiment",
  analysis: "Analysis",
  services: "Services",
  "protocol-editor": "Protocol Editor",
};

const appShell = document.querySelector("#app-shell");
const sidebar = document.querySelector("#sidebar");
const pinButton = document.querySelector("#pin-button");
const pinLabel = pinButton.querySelector(".pin-button__label");
const sectionTitle = document.querySelector("#section-title");
const navItems = [...document.querySelectorAll(".nav-item")];
const workspace = document.querySelector(".workspace");
const alerts = document.querySelector("#alerts");
const alertsTrigger = document.querySelector("#alerts-trigger");
const alertsPanel = document.querySelector("#alerts-panel");
const alertsClose = document.querySelector("#alerts-close");
const alertsBadge = document.querySelector("#alerts-badge");
const alertsList = document.querySelector("#alerts-list");
const restoreAlerts = document.querySelector("#restore-alerts");
const catalogDialog = document.querySelector("#catalog-dialog");
const catalogForm = document.querySelector("#catalog-form");
const catalogDialogTitle = document.querySelector("#catalog-dialog-title");
const catalogFields = document.querySelector("#catalog-fields");
const catalogSelects = [...document.querySelectorAll("[data-catalog-select]")];
const catalogDismissButtons = [...document.querySelectorAll("[data-dialog-dismiss]")];
const themeToggle = document.querySelector("#theme-toggle");
const themeLabel = themeToggle.querySelector(".theme-toggle__label");
const themeIconUse = document.querySelector("#theme-icon-use");

function setTheme(theme, persist = true) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  themeToggle.setAttribute("aria-pressed", String(dark));
  themeToggle.title = dark ? "Switch to light mode" : "Switch to dark mode";
  themeLabel.textContent = dark ? "Light mode" : "Dark mode";
  themeIconUse.setAttribute("href", dark ? "#icon-sun" : "#icon-moon");

  if (persist) {
    try {
      localStorage.setItem("miceball-theme", dark ? "dark" : "light");
    } catch (_) {}
  }
}

const catalogForms = {
  experimenter: {
    title: "New Experimenter",
    valueField: "name",
    fields: [{ name: "name", label: "Name", type: "text", wide: true }],
  },
  project: {
    title: "New Project",
    valueField: "project_name",
    fields: [
      { name: "project_name", label: "Project name", type: "text", wide: true },
      { name: "primary_experimenter", label: "Primary experimenter", type: "select", options: ["Taylor Kim", "Morgan Lee"] },
    ],
  },
  animal: {
    title: "New Animal",
    valueField: "animal_id",
    fields: [
      { name: "animal_id", label: "Animal ID", type: "text" },
      { name: "animal_name", label: "Animal name", type: "text" },
      { name: "species", label: "Species", type: "text" },
      { name: "strain", label: "Strain", type: "text" },
      { name: "sex", label: "Sex", type: "select", options: ["Female", "Male", "Unknown / not recorded"] },
      { name: "date_of_birth", label: "Date of birth", type: "date" },
      { name: "notes", label: "Optional notes", type: "textarea", wide: true, required: false },
    ],
  },
};

let activeCatalogSelect = null;

function buildCatalogFields(catalogType) {
  catalogFields.replaceChildren();
  catalogForms[catalogType].fields.forEach((field) => {
    const label = document.createElement("label");
    if (field.wide) label.className = "field-wide";
    label.append(document.createTextNode(field.label));

    let control;
    if (field.type === "select") {
      control = document.createElement("select");
      field.options.forEach((optionText) => control.add(new Option(optionText, optionText)));
    } else if (field.type === "textarea") {
      control = document.createElement("textarea");
      control.rows = 3;
    } else {
      control = document.createElement("input");
      control.type = field.type;
    }
    control.name = field.name;
    control.required = field.required !== false;
    label.append(control);
    catalogFields.append(label);
  });
}

function openCatalogDialog(select) {
  const catalogType = select.dataset.catalogSelect;
  activeCatalogSelect = select;
  catalogDialog.dataset.catalogType = catalogType;
  catalogDialogTitle.textContent = catalogForms[catalogType].title;
  buildCatalogFields(catalogType);
  catalogDialog.returnValue = "";
  catalogDialog.showModal();
  catalogFields.querySelector("input, select, textarea").focus();
}

function updateAnimalSummary(data) {
  document.querySelector("#animal-name").textContent = data.animal_name || "Not provided";
  document.querySelector("#animal-species").textContent = data.species || "Not provided";
  document.querySelector("#animal-strain").textContent = data.strain || "Not provided";
  document.querySelector("#animal-sex").textContent = data.sex || "Not recorded";
  document.querySelector("#animal-dob").textContent = data.date_of_birth || "Not provided";
}

const demonstrationNotifications = [
  {
    id: "storage-write",
    severity: "error",
    source: "StorageManager",
    occurredAt: "2026-10-24T14:32:18-05:00",
    displayTime: "Oct 24, 2026 · 2:32:18 PM",
    description: "The demonstration storage destination did not accept the latest write.",
  },
  {
    id: "acquisition-frame-gap",
    severity: "warning",
    source: "AcquisitionNode",
    occurredAt: "2026-10-24T14:31:42-05:00",
    displayTime: "Oct 24, 2026 · 2:31:42 PM",
    description: "A fictional camera stream reported an interval longer than expected.",
  },
  {
    id: "controller-readiness",
    severity: "warning",
    source: "Controller",
    occurredAt: "2026-10-24T14:29:07-05:00",
    displayTime: "Oct 24, 2026 · 2:29:07 PM",
    description: "A sample service readiness confirmation is older than the demonstration threshold.",
  },
];

let notifications = demonstrationNotifications.map((notification) => ({ ...notification }));

function renderNotifications() {
  const errorCount = notifications.filter(({ severity }) => severity === "error").length;
  const warningCount = notifications.filter(({ severity }) => severity === "warning").length;

  const totalCount = errorCount + warningCount;
  alertsBadge.textContent = String(totalCount);
  alertsBadge.hidden = totalCount === 0;

  alertsTrigger.setAttribute(
    "aria-label",
    errorCount === 0 && warningCount === 0
      ? "Warnings and errors: no alerts"
      : `Warnings and errors: ${errorCount} ${errorCount === 1 ? "error" : "errors"}, ${warningCount} ${warningCount === 1 ? "warning" : "warnings"}`,
  );

  alertsList.replaceChildren();
  if (notifications.length === 0) {
    const empty = document.createElement("div");
    empty.className = "alerts-empty";
    empty.innerHTML = "<div><strong>No unacknowledged alerts</strong><p>Restore the fictional entries to repeat the visual test.</p></div>";
    alertsList.append(empty);
    return;
  }

  notifications.forEach((notification) => {
    const entry = document.createElement("article");
    entry.className = `alert-entry alert-entry--${notification.severity}`;
    entry.innerHTML = `
      <div class="alert-entry__heading">
        <span class="alert-entry__severity">${notification.severity}</span>
        <span class="alert-entry__source">${notification.source}</span>
      </div>
      <time datetime="${notification.occurredAt}">${notification.displayTime}</time>
      <p class="alert-entry__description">${notification.description}</p>
      <button class="acknowledge-alert" type="button" data-notification-id="${notification.id}">
        Acknowledge
      </button>`;
    alertsList.append(entry);
  });
}

function setAlertsPanelOpen(open, returnFocus = false) {
  alertsPanel.hidden = !open;
  alertsTrigger.setAttribute("aria-expanded", String(open));
  if (open) alertsClose.focus();
  else if (returnFocus) alertsTrigger.focus();
}

function setSection(sectionId) {
  if (!sectionNames[sectionId]) return;

  document.querySelectorAll(".nav-item").forEach((item) => {
    const selected = item.dataset.section === sectionId;
    item.classList.toggle("is-selected", selected);
    if (selected) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });

  document.querySelectorAll(".section-panel").forEach((panel) => {
    const selected = panel.dataset.panel === sectionId;
    panel.hidden = !selected;
    panel.classList.toggle("is-active", selected);
  });

  sectionTitle.textContent = sectionNames[sectionId];
  document.title = `Miceball · ${sectionNames[sectionId]}`;
}

function setPinned(pinned) {
  const wasPinned = sidebar.classList.contains("is-pinned");
  sidebar.classList.toggle("is-pinned", pinned);
  sidebar.classList.remove("is-temporary-expanded");
  sidebar.classList.toggle("is-suppress-hover", wasPinned && !pinned);
  appShell.classList.toggle("is-pinned", pinned);
  pinButton.setAttribute("aria-pressed", String(pinned));
  pinButton.title = pinned ? "Unpin sidebar" : "Pin sidebar";
  pinLabel.textContent = pinned ? "Unpin sidebar" : "Pin sidebar";

  if (!pinned && document.activeElement === pinButton) {
    workspace.focus({ preventScroll: true });
  }
}

function focusAdjacentItem(currentIndex, key) {
  const lastIndex = navItems.length - 1;
  const targetIndex = key === "Home" ? 0
    : key === "End" ? lastIndex
    : key === "ArrowDown" ? (currentIndex + 1) % navItems.length
    : key === "ArrowUp" ? (currentIndex - 1 + navItems.length) % navItems.length
    : currentIndex;
  navItems[targetIndex].focus();
}

navItems.forEach((item, index) => {
  item.addEventListener("click", () => setSection(item.dataset.section));
  item.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    focusAdjacentItem(index, event.key);
  });
});

pinButton.addEventListener("click", () => {
  setPinned(pinButton.getAttribute("aria-pressed") !== "true");
});

themeToggle.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

sidebar.addEventListener("pointerenter", () => {
  if (!sidebar.classList.contains("is-pinned")) {
    sidebar.classList.add("is-temporary-expanded");
  }
});

sidebar.addEventListener("pointerleave", () => {
  sidebar.classList.remove("is-temporary-expanded");
  sidebar.classList.remove("is-suppress-hover");
});

document.addEventListener("pointerdown", (event) => {
  if (!sidebar.contains(event.target) && !sidebar.classList.contains("is-pinned")) {
    sidebar.classList.remove("is-temporary-expanded");
    workspace.focus({ preventScroll: true });
  }

  if (!alerts.contains(event.target) && !alertsPanel.hidden) {
    setAlertsPanelOpen(false);
  }
});

alertsTrigger.addEventListener("click", () => {
  setAlertsPanelOpen(alertsTrigger.getAttribute("aria-expanded") !== "true");
});

alertsClose.addEventListener("click", () => setAlertsPanelOpen(false, true));

alertsList.addEventListener("click", (event) => {
  const button = event.target.closest(".acknowledge-alert");
  if (!button) return;
  notifications = notifications.filter(({ id }) => id !== button.dataset.notificationId);
  renderNotifications();
  const nextButton = alertsList.querySelector(".acknowledge-alert");
  (nextButton ?? restoreAlerts).focus();
});

restoreAlerts.addEventListener("click", () => {
  notifications = demonstrationNotifications.map((notification) => ({ ...notification }));
  renderNotifications();
  alertsList.querySelector(".acknowledge-alert").focus();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !alertsPanel.hidden) {
    event.preventDefault();
    setAlertsPanelOpen(false, true);
  }
});

catalogSelects.forEach((select) => {
  select.dataset.previousValue = select.value;
  select.addEventListener("change", () => {
    if (select.value.startsWith("__new_")) openCatalogDialog(select);
    else select.dataset.previousValue = select.value;
  });
});

catalogDismissButtons.forEach((button) => {
  button.addEventListener("click", () => catalogDialog.close("cancel"));
});

catalogForm.addEventListener("submit", (event) => {
  if (event.submitter?.value !== "save") return;
  event.preventDefault();
  if (!catalogForm.reportValidity()) return;

  const catalogType = catalogDialog.dataset.catalogType;
  const values = Object.fromEntries(new FormData(catalogForm));
  const displayValue = values[catalogForms[catalogType].valueField].trim();
  const newOption = new Option(displayValue, displayValue, true, true);
  activeCatalogSelect.add(newOption, activeCatalogSelect.lastElementChild);
  activeCatalogSelect.dataset.previousValue = displayValue;
  if (catalogType === "animal") updateAnimalSummary(values);
  catalogDialog.close("save");
});

catalogDialog.addEventListener("close", () => {
  if (catalogDialog.returnValue !== "save" && activeCatalogSelect) {
    activeCatalogSelect.value = activeCatalogSelect.dataset.previousValue;
  }
  catalogForm.reset();
  activeCatalogSelect?.focus();
  activeCatalogSelect = null;
});

setTheme(document.documentElement.dataset.theme, false);
document.addEventListener("gui-section", event => setSection(event.detail));
setPinned(false);
setSection("setup");
renderNotifications();
