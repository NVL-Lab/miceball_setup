import { formatCalendarDate } from './calendar-date.mjs';
import { createAnimalCatalog, saveAnimalDemo } from './animal-demo.mjs';
import { createNavigationMenu } from './navigation-menu.mjs';
import { catalogClient, catalogId, loadCatalog, putCatalog } from './catalog-client.mjs';
import { recordLocalActivity, recordActivityTransition, recordInvalidControl } from './activity-history.mjs';

const animalCatalog = createAnimalCatalog();
const connected = document.documentElement.dataset.runtime === 'connected';
if (connected) {
  document.querySelector('.topbar__eyebrow').textContent = 'Miceball';
  animalCatalog.clear();
  for (const select of document.querySelectorAll('[data-catalog-select]')) {
    for (const option of [...select.options]) if (!option.value.startsWith('__new_')) option.remove();
    select.add(new Option('Not selected', '', true, true), select.firstElementChild);
  }
  for (const input of document.querySelectorAll('.session-identity-grid input')) input.value = '';
  document.querySelector('[aria-labelledby="notes-title"] textarea').value = '';
  document.querySelector('#catalog-save').textContent = 'Save';
  document.querySelector('.catalog-dialog__header p').textContent = 'Catalog entry';
  document.querySelector('.catalog-dialog__note').textContent = 'Save to the shared catalog of this GUI backend.';
  updateAnimalSummary({});
  for (const small of document.querySelectorAll('.session-identity-grid small')) small.textContent = 'Unsent local preparation';
}
const sectionNames = {
  setup: "Setup",
  session: "Session",
  parameters: "Parameters",
  experiment: "Experiment",
  analysis: "Analysis",
  storage: "Storage",
  services: "Services",
  "protocol-editor": "Protocol Editor",
};

const appShell = document.querySelector("#app-shell");
const sidebar = document.querySelector("#sidebar");
const navigationMenu = createNavigationMenu(sidebar, document.querySelector('#navigation-toggle'), document, () => setPinned(false));
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
      { name: "primary_experimenter", label: "Primary experimenter", type: "select", options: [] },
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
      if (field.name === 'primary_experimenter') {
        control.add(new Option('Select an existing Experimenter', ''));
        control.addEventListener('change', () => control.setCustomValidity(''));
        for (const option of document.querySelector('#experimenter-select').options) {
          if (option.value && !option.value.startsWith('__new_')) control.add(new Option(option.textContent, option.value));
        }
        const note = document.createElement('small'); note.textContent = 'Create the Experimenter first if not listed.'; label.append(note);
      } else field.options.forEach((optionText) => control.add(new Option(optionText, optionText)));
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
  if (connected && catalogType === 'animal' && !document.querySelector('#project-select').value) {
    catalogFeedback.textContent = 'Select a project before creating its animal.';
    select.value = select.dataset.previousValue; return;
  }
  activeCatalogSelect = select;
  catalogDialog.dataset.catalogType = catalogType;
  if (connected) catalogDialog.dataset.catalogRevision = String(catalogClient.snapshot?.revision);
  catalogDialogTitle.textContent = catalogForms[catalogType].title;
  catalogForm.querySelector('[data-catalog-error]')?.remove();
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
  document.querySelector("#animal-dob").textContent = formatCalendarDate(data.date_of_birth) || "Not provided";
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

// Older acknowledged fixtures exercise the scrollable history without changing
// the existing three unacknowledged examples or implying new live notifications.
demonstrationNotifications.push(...Array.from({ length: 10 }, (_, index) => ({
  id: `historical-example-${index + 1}`,
  severity: index % 3 === 0 ? 'error' : 'warning',
  source: ['Controller', 'AcquisitionNode', 'StorageManager'][index % 3],
  occurredAt: `2026-10-23T10:${String(index).padStart(2, '0')}:00-05:00`,
  displayTime: `Oct 23, 2026 · 10:${String(index).padStart(2, '0')} AM`,
  description: `Historical demonstration ${index + 1}: an earlier fictional operational warning. Acknowledgment does not establish resolution.`,
  acknowledged: true,
})));
if (document.documentElement.dataset.runtime === 'connected') demonstrationNotifications.length = 0;
let notifications = demonstrationNotifications.filter(item => !item.acknowledged).map((notification) => ({ ...notification }));
let acknowledgedNotifications = new Set(demonstrationNotifications.filter(item => item.acknowledged).map(item => item.id));

export function notificationHistory() {
  return demonstrationNotifications.map(item => ({ ...item, acknowledged: acknowledgedNotifications.has(item.id) }));
}

export function acknowledgeNotification(id) {
  if (!demonstrationNotifications.some(item => item.id === id)) return;
  acknowledgedNotifications.add(id);
  notifications = notifications.filter(item => item.id !== id);
  renderNotifications();
  document.dispatchEvent(new CustomEvent('gui-notifications-changed'));
}

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
    empty.innerHTML = connected ? '<div><strong>Warnings and errors unavailable</strong><p>Authoritative notification integration is not connected.</p></div>' : "<div><strong>No unacknowledged alerts</strong><p>Restore the fictional entries to repeat the visual test.</p></div>";
    if (connected) { alertsBadge.hidden = true; alertsTrigger.setAttribute('aria-label', 'Warnings and errors unavailable'); restoreAlerts.disabled = true; }
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
  if (!sidebar.classList.contains('is-pinned')) {
    navigationMenu.close();
  }

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
  document.dispatchEvent(new CustomEvent('gui-section-changed', { detail: sectionId }));
}

function setPinned(pinned) {
  sidebar.classList.toggle("is-pinned", pinned);
  navigationMenu.syncPinned();
  appShell.classList.toggle("is-pinned", pinned);
  pinButton.setAttribute("aria-pressed", String(pinned));
  pinButton.title = pinned ? "Unpin sidebar" : "Pin sidebar";
  pinLabel.textContent = pinned ? "Unpin sidebar" : "Pin sidebar";

  if (!pinned && document.activeElement === pinButton) {
    workspace.focus({ preventScroll: true });
  }
}

function focusAdjacentItem(currentIndex, key) {
  const items = navItems.filter(item => !item.hidden);
  currentIndex = items.indexOf(navItems[currentIndex]);
  const lastIndex = items.length - 1;
  const targetIndex = key === "Home" ? 0
    : key === "End" ? lastIndex
    : key === "ArrowDown" ? (currentIndex + 1) % items.length
    : key === "ArrowUp" ? (currentIndex - 1 + items.length) % items.length
    : currentIndex;
  items[targetIndex].focus();
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

document.addEventListener("pointerdown", (event) => {
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
  acknowledgeNotification(button.dataset.notificationId);
  const nextButton = alertsList.querySelector(".acknowledge-alert");
  (nextButton ?? restoreAlerts).focus();
});

restoreAlerts.addEventListener("click", () => {
  acknowledgedNotifications = new Set(demonstrationNotifications.filter(item => item.acknowledged).map(item => item.id));
  notifications = demonstrationNotifications.filter(item => !item.acknowledged).map((notification) => ({ ...notification }));
  renderNotifications();
  document.dispatchEvent(new CustomEvent('gui-notifications-changed'));
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
    else {
      select.dataset.previousValue = select.value;
      if (select.dataset.catalogSelect === 'animal') updateAnimalSummary(animalCatalog.get(select.value) || {});
    }
  });
});

catalogDismissButtons.forEach((button) => {
  button.addEventListener("click", () => catalogDialog.close("cancel"));
});

catalogForm.addEventListener('invalid', event => recordInvalidControl('save_catalog', event.target), true);
catalogForm.addEventListener("submit", async (event) => {
  if (event.submitter?.value !== "save") return;
  event.preventDefault();
  if (!catalogForm.reportValidity()) return;

  const catalogType = catalogDialog.dataset.catalogType;
  const values = Object.fromEntries(new FormData(catalogForm));
  if (catalogType === 'project' && ![...document.querySelector('#experimenter-select').options]
      .some(option => option.value && !option.value.startsWith('__new_') && option.value === values.primary_experimenter)) {
    const primary = catalogForm.elements.primary_experimenter;
    primary.setCustomValidity('Select an existing Experimenter.'); primary.reportValidity(); return;
  }
  const displayValue = values[catalogForms[catalogType].valueField].trim();
  if (connected) {
    const record = {id: catalogId(), ...values};
    if (catalogType === 'experimenter') record.name = displayValue;
    if (catalogType === 'project') { record.name = displayValue; delete record.project_name; }
    if (catalogType === 'animal') record.projectId = document.querySelector('#project-select').value;
    const controls = [...catalogForm.elements].map(control => [control, control.disabled]);
    for (const [control] of controls) control.disabled = true;
    try {
      await putCatalog({experimenter: 'experimenters', project: 'projects', animal: 'animals'}[catalogType], record,
        document.querySelector('#experimenter-select').value || record.id, Number(catalogDialog.dataset.catalogRevision));
      activeCatalogSelect.value = record.id;
      activeCatalogSelect.dataset.previousValue = record.id;
      if (catalogType === 'animal') updateAnimalSummary(record);
      activeCatalogSelect.dispatchEvent(new Event('change', {bubbles: true}));
      catalogFeedback.textContent = 'Catalog entry saved.';
      recordLocalActivity('save_catalog');
      catalogDialog.close('save');
    } catch (error) {
      catalogFeedback.textContent = error.message;
      let feedback = catalogForm.querySelector('[data-catalog-error]');
      if (!feedback) { feedback = document.createElement('p'); feedback.dataset.catalogError = ''; feedback.setAttribute('role', 'status'); catalogFields.after(feedback); }
      feedback.textContent = error.message;
      recordLocalActivity('save_catalog', error.message, error.catalogStatus);
    } finally { for (const [control, disabled] of controls) control.disabled = disabled; }
    return;
  }
  // An ephemeral option key keeps same-label examples independent without catalog identity rules.
  const optionValue = catalogType === 'animal' ? saveAnimalDemo(animalCatalog, values) : displayValue;
  const newOption = new Option(displayValue, optionValue, true, true);
  if (catalogType === 'project') newOption.dataset.primaryExperimenter = values.primary_experimenter;
  activeCatalogSelect.add(newOption, activeCatalogSelect.lastElementChild);
  activeCatalogSelect.dataset.previousValue = optionValue;
  if (catalogType === "animal") {
    updateAnimalSummary(animalCatalog.get(optionValue));
  }
  catalogDialog.close("save");
});

catalogDialog.addEventListener("close", () => {
  // A queued close event must not clear a newly reopened catalog dialog.
  if (catalogDialog.open) return;
  if (catalogDialog.returnValue !== "save" && activeCatalogSelect) {
    activeCatalogSelect.value = activeCatalogSelect.dataset.previousValue;
  }
  catalogForm.reset();
  activeCatalogSelect?.focus();
  activeCatalogSelect = null;
});
catalogDialog.addEventListener('cancel', event => {
  if (connected && document.querySelector('#catalog-save').disabled) event.preventDefault();
});

setTheme(document.documentElement.dataset.theme, false);
document.addEventListener("gui-section", event => setSection(event.detail));
setPinned(false);
setSection("setup");
renderNotifications();

const catalogFeedback = document.createElement('p');
catalogFeedback.className = 'prototype-caption';
catalogFeedback.setAttribute('role', 'status');
if (connected) {
  document.querySelector('.identity-card').append(catalogFeedback);
  const refresh = async () => {
    try {
      await loadCatalog(); catalogFeedback.textContent = 'Catalogs loaded.';
      recordActivityTransition('load_catalog', 'succeeded');
    } catch (error) {
      catalogFeedback.textContent = 'Catalog unavailable. See Activity History in Services.';
      recordActivityTransition('load_catalog', 'failed', error.message);
    }
  };
  const renderCatalogSelects = () => {
    const catalog = catalogClient.snapshot.catalog;
    animalCatalog.clear();
    const projectId = document.querySelector('#project-select').value;
    for (const record of catalog.animals) if (record.projectId === projectId) animalCatalog.set(record.id, record);
    for (const select of catalogSelects) {
      const previous = select.value.startsWith('__new_') ? select.dataset.previousValue : select.value;
      const kind = select.dataset.catalogSelect;
      const records = kind === 'experimenter' ? catalog.experimenters : kind === 'project' ? catalog.projects : catalog.animals.filter(item => item.projectId === document.querySelector('#project-select').value);
      for (const option of [...select.options]) if (!option.value.startsWith('__new_')) option.remove();
      select.add(new Option('Not selected', ''), select.firstElementChild);
      for (const record of records) {
        const option = new Option(kind === 'animal' ? record.animal_id : record.name, record.id);
        if (kind === 'project') option.dataset.primaryExperimenter = record.primary_experimenter;
        select.add(option, select.lastElementChild);
      }
      select.value = records.some(item => item.id === previous) ? previous : '';
      select.dataset.previousValue = select.value;
    }
    updateAnimalSummary(animalCatalog.get(document.querySelector('#animal-select').value) || {});
  };
  document.addEventListener('gui-catalog-changed', renderCatalogSelects);
  document.querySelector('#project-select').addEventListener('change', () => { if (catalogClient.snapshot) renderCatalogSelects(); });
  document.addEventListener('gui-section-changed', event => { if (['setup', 'session', 'parameters'].includes(event.detail) && !catalogDialog.open) refresh(); });
  document.addEventListener('gui-control-acquired', refresh);
  refresh();
}
