import { createDemo, operations, devices, clone, selectProtocol, selectTemplate, coverage, saveProtocol, moveStep, assignCapability, preparedSteps, savedOccurrence, copyStepToEdit, saveReusableStep } from './protocol-demo.mjs';

const state = createDemo();
const $ = selector => document.querySelector(selector);
const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const option = (value, text) => `<option value="${escape(value)}">${escape(text)}</option>`;
const identity = $('[aria-labelledby="session-identity-title"]');
$('.identity-card').after(identity);
const oldTemplate = $('[aria-labelledby="template-title"]');
const protocolCard = document.createElement('section');
protocolCard.className = 'setup-card';
protocolCard.innerHTML = `<h3>▤ &nbsp; Scientific protocol</h3><div class="protocol-toolbar"><label>Protocol<select id="protocol-select"></select></label><button type="button" id="new-protocol" class="proto-primary">+ New Protocol</button><button type="button" id="edit-protocol">Edit Protocol</button><button type="button" id="copy-protocol">Copy Protocol</button></div><p class="protocol-description" id="protocol-description"></p>`;
oldTemplate.before(protocolCard);
oldTemplate.innerHTML = `<h3 id="template-title">◇ &nbsp; Session template (optional)</h3><div class="template-grid"><label>Session template<select id="session-template"></select></label><div class="template-description"><span>Template description</span><p id="template-description"></p></div></div><p class="prototype-hint">Templates prefill optional steps and preferred devices. You can change these choices before launch.</p>`;
const stepsCard = document.createElement('section');
stepsCard.className = 'setup-card';
stepsCard.innerHTML = `<h3>☷ &nbsp; Steps for this Session</h3><p class="prototype-caption">Maintain protocol order. Choose which optional steps to include today.</p><div class="prototype-table-wrap"><table class="prototype-table"><thead><tr><th>#</th><th>Step</th><th>Include</th><th>Required</th><th>Description</th></tr></thead><tbody id="session-steps"></tbody></table></div>`;
oldTemplate.after(stepsCard);
const deviceCard = $('.device-card');
deviceCard.innerHTML = `<h3>▣ &nbsp; Session devices &amp; capabilities</h3><p class="prototype-caption">Demonstration declarations only. Coverage means a selected device declares the identifier; it does not establish hardware readiness.</p><h4>Required capabilities <small>(based on included steps)</small></h4><div class="prototype-table-wrap"><table class="prototype-table"><thead><tr><th>Capability</th><th>Status</th><th>Provided by selected device(s)</th></tr></thead><tbody id="capability-rows"></tbody></table></div><details class="optional-capabilities"><summary>Optional capabilities</summary><p id="optional-capabilities"></p></details><h4>Select Session devices</h4><p class="prototype-caption">Select independently, including extra devices and multiple providers.</p><div id="session-device-list"></div>`;
const readiness = $('.readiness-card ul');
let draft = null;
let originalDraft = '';
let selectedStep = 0;
let sequence = 0;
const editorTab = document.createElement('button');
editorTab.type = 'button';
editorTab.className = 'nav-item editor-tab';
editorTab.dataset.section = 'protocol-editor';
editorTab.title = 'Protocol Editor';
editorTab.setAttribute('aria-controls', 'panel-protocol-editor');
editorTab.innerHTML = '<svg aria-hidden="true"><use href="#icon-session"></use></svg><span>Protocol Editor<small id="editor-dirty-label"></small></span>';
editorTab.hidden = true;
$('.section-nav').append(editorTab);
const editor = document.createElement('section');
editor.className = 'section-panel protocol-editor';
editor.id = 'panel-protocol-editor';
editor.dataset.panel = 'protocol-editor';
editor.setAttribute('aria-label', 'Protocol Editor');
editor.hidden = true;
editor.innerHTML = `<div class="editor-heading"><div><label>Protocol name<input id="protocol-name" required></label><p class="prototype-caption">Personal demonstration protocol · browser memory only</p></div><div class="editor-actions"><button id="cancel-protocol" type="button">Cancel</button><button id="save-protocol" type="button" class="proto-primary">Save Protocol</button></div></div><label class="protocol-description-field">Protocol description<textarea id="protocol-summary" rows="2"></textarea></label><div class="editor-layout"><section class="setup-card"><div class="editor-step-heading"><h3>Protocol steps</h3><div class="add-step"><label class="visually-hidden" for="add-operation">Application-supported operation</label><select id="add-operation">${operations.map(op => option(op.id, op.name)).join('')}</select><button id="add-step" type="button">+ Add step</button></div></div><ol id="editor-steps"></ol></section><section class="setup-card"><h3>Step configuration</h3><form id="step-form"><label>Step name<input name="name" required></label><div class="step-fields-row"><label>Application-supplied operation<select name="operation">${operations.map(op => option(op.id, `${op.name} (${op.type})`)).join('')}</select></label><label>Required / optional<select name="mandatory"><option value="true">Required</option><option value="false">Optional</option></select></label></div><label>Description<textarea name="description" rows="3"></textarea></label><label>Required capabilities<input name="required" placeholder="imaging_camera, visual_stimulation"></label><label>Optional capabilities<input name="optional" placeholder="behavior_video"></label><p class="prototype-caption">Illustrative exact identifiers, separated by commas. Optional capabilities do not block coverage.</p><label>Demonstration configuration / notes<textarea name="configuration" rows="3" placeholder="Example settings for this operation"></textarea></label></form><p id="no-step" hidden>Add an application-supported operation to begin.</p></section></div><p id="editor-message" role="status"></p>`;
$('#workspace-content').append(editor);
// Reuse the existing controls and selector; no separate step library.
const footer = document.createElement('footer');
footer.className = 'editor-footer';
footer.append($('.editor-actions'));
editor.append(footer);
const stepActions = document.createElement('div');
stepActions.className = 'reusable-step-actions';
stepActions.innerHTML = '<p id="step-definition-status" class="prototype-caption"></p><button type="button" id="copy-step">Copy to edit</button><button type="button" id="save-reusable-step">Save as reusable step</button><p class="prototype-caption">Reusable definitions are saved separately from this protocol, in demonstration memory only.</p>';
$('#step-form').before(stepActions);
const currentExperimenter = () => $('#experimenter-select').value;
function renderPreparedSteps() {
  const select = $('#add-operation');
  const previous = select.value;
  select.innerHTML = option('blank', 'Blank step') + preparedSteps(state, currentExperimenter()).map(step => option(step.id, `${step.name} · ${step.owner === null ? 'Lab / application' : 'Personal'}`)).join('');
  if ([...select.options].some(item => item.value === previous)) select.value = previous;
}
$('#experimenter-select').addEventListener('change', renderPreparedSteps);
const optionalTable = document.createElement('div');
optionalTable.className = 'prototype-table-wrap';
optionalTable.innerHTML = '<table class="prototype-table"><thead><tr><th>Capability</th><th>Status</th><th>Provided by selected device(s)</th></tr></thead><tbody id="optional-capabilities"></tbody></table>';
$('#optional-capabilities').replaceWith(optionalTable);
const capabilityNames = [...new Set(devices.flatMap(device => device.capabilities))];
const capabilityLabel = id => id.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase());
for (const kind of ['required', 'optional']) {
  const old = $('#step-form').elements[kind].closest('label');
  const group = document.createElement('fieldset');
  group.className = 'capability-picker';
  group.dataset.kind = kind;
  group.innerHTML = `<legend>${kind === 'required' ? 'Required' : 'Optional'} capabilities</legend><p class="prototype-caption">${kind === 'required' ? 'Functionality needed when this step is included in a Session.' : 'Additional functionality that can be enabled for this step during Session preparation.'}</p><div class="capability-chips"></div><details><summary>Select capabilities</summary><div class="capability-options"></div></details>`;
  old.replaceWith(group);
}
$('#step-form > .prototype-caption').textContent = 'Selecting a capability here moves it out of the other list. Optional capabilities do not block coverage.';
for (const [name, text] of [
  ['operation', 'Choose an operation provided by the scientific application. This does not create a new scientific algorithm.'],
  ['mandatory', 'Optional steps can be skipped when preparing a Session. Required steps remain included.'],
]) {
  const help = document.createElement('small');
  help.className = 'prototype-caption';
  help.textContent = text;
  $('#step-form').elements[name].after(help);
}

function renderCapabilityPickers(step) {
  for (const kind of ['required', 'optional']) {
    const group = $(`.capability-picker[data-kind="${kind}"]`);
    group.querySelector('.capability-chips').innerHTML = step[kind].map(id => `<button type="button" class="capability-chip" data-remove-capability="${escape(id)}" data-kind="${kind}" aria-label="Remove ${escape(capabilityLabel(id))} from ${kind}">${escape(capabilityLabel(id))} <span aria-hidden="true">×</span></button>`).join('') || '<span class="prototype-caption">None selected</span>';
    group.querySelector('.capability-options').innerHTML = [...new Set([...capabilityNames, ...step.required, ...step.optional])].map(id => `<label><input type="checkbox" data-capability="${escape(id)}" data-kind="${kind}" ${step[kind].includes(id) ? 'checked' : ''}><span>${escape(capabilityLabel(id))}<small>${escape(id)}</small></span></label>`).join('');
    group.disabled = !!step.definitionId;
  }
}
const discardDialog = document.createElement('dialog');
discardDialog.className = 'catalog-dialog';
discardDialog.setAttribute('aria-labelledby', 'discard-title');
discardDialog.innerHTML = `<form method="dialog"><h2 id="discard-title">Discard protocol changes?</h2><p>Your unsaved demonstration edits will be lost.</p><div class="catalog-dialog__actions"><button value="keep" class="dialog-button">Keep editing</button><button value="discard" class="dialog-button dialog-button--primary">Discard changes</button></div></form>`;
document.body.append(discardDialog);

function showSection(section) {
  document.dispatchEvent(new CustomEvent('gui-section', { detail: section }));
}
function currentProtocol() { return state.protocols.find(p => p.id === state.protocolId); }
function coverageRows(rows, empty) {
  return rows.length ? rows.map(row => `<tr><td>${escape(row.capability)}</td><td class="${row.providers.length ? 'coverage-good' : 'coverage-missing'}">${row.providers.length ? '✓ Covered' : '○ Missing'}</td><td>${row.providers.map(device => escape(device.name)).join(', ') || '—'}</td></tr>`).join('') : `<tr><td colspan="3">${empty}</td></tr>`;
}
function renderSetup() {
  const protocol = currentProtocol();
  $('#protocol-select').innerHTML = state.protocols.map(p => option(p.id, p.name + (p.protected ? ' · Lab reference' : ''))).join('');
  $('#protocol-select').value = protocol.id;
  $('#protocol-description').textContent = protocol.description;
  $('#edit-protocol').disabled = protocol.protected;
  $('#edit-protocol').title = protocol.protected ? 'Protected reference: use Copy Protocol to create a personal copy.' : 'Edit personal protocol';
  $('#session-template').innerHTML = option('', 'None / Custom') + state.templates.filter(t => t.protocol === protocol.id).map(t => option(t.id, t.name)).join('');
  $('#session-template').value = state.templateId;
  $('#template-description').textContent = state.templates.find(t => t.id === state.templateId)?.description || 'Configure this Session manually. No template selected.';
  $('#session-steps').innerHTML = protocol.steps.map((s, i) => `<tr><td>${i + 1}</td><td>${escape(s.name)}</td><td><input type="checkbox" data-step="${escape(s.id)}" aria-label="Include ${escape(s.name)}" ${s.mandatory || state.included.includes(s.id) ? 'checked' : ''} ${s.mandatory ? 'disabled' : ''}></td><td>${s.mandatory ? 'Yes' : 'No'}</td><td class="step-description-cell">${escape(s.description)}</td></tr>`).join('');
  const result = coverage(state);
  $('#capability-rows').innerHTML = coverageRows(result.required, 'No required hardware capabilities for these steps.');
  $('#optional-capabilities').innerHTML = coverageRows(result.optional, 'No additional optional capabilities.');
  $('#session-device-list').innerHTML = devices.map(d => `<label class="session-device"><input type="checkbox" data-device="${d.id}" aria-label="Select ${escape(d.name)}" ${state.selectedDevices.includes(d.id) ? 'checked' : ''}><span><strong>${escape(d.name)}</strong><small>${escape(d.detail)} · ${d.capabilities.map(escape).join(', ')}</small></span><span class="device-state ${d.available ? 'is-ready' : ''}">${d.available ? 'Connected (demo)' : 'Unavailable (demo)'}</span></label>`).join('');
  const missing = result.required.filter(r => !r.providers.length).length;
  readiness.innerHTML = `<li><span class="${missing ? 'missing-dot' : ''}">${missing ? '!' : '✓'}</span> Capability coverage <strong>${missing ? `${missing} missing` : 'All covered'}</strong></li><li><span class="${result.unavailable.length ? 'missing-dot' : ''}">·</span> Selected device availability <strong>${result.unavailable.length ? `${result.unavailable.length} unavailable` : 'Available (demo)'}</strong></li><li><span>·</span> Optional steps intentionally skipped <strong>${result.skipped}</strong></li><li><span>·</span> Runtime readiness <strong>Not checked — visual demo</strong></li>`;
}
function updateDirty() {
  $('#editor-dirty-label').textContent = JSON.stringify(draft) !== originalDraft ? 'Unsaved changes' : 'Draft';
}
function renderEditor() {
  $('#protocol-name').value = draft.name;
  $('#protocol-summary').value = draft.description;
  $('#editor-steps').innerHTML = draft.steps.map((s, i) => `<li data-step-id="${escape(s.id)}" class="${i === selectedStep ? 'selected' : ''}"><button type="button" class="step-drag-handle" data-drag-step="${escape(s.id)}" aria-label="Drag ${escape(s.name)} to reorder" title="Drag to reorder; or use Move Up / Move Down"><svg viewBox="0 0 12 18" aria-hidden="true"><circle cx="3" cy="3" r="1.3"/><circle cx="9" cy="3" r="1.3"/><circle cx="3" cy="9" r="1.3"/><circle cx="9" cy="9" r="1.3"/><circle cx="3" cy="15" r="1.3"/><circle cx="9" cy="15" r="1.3"/></svg></button><button type="button" data-select-step="${i}" aria-pressed="${i === selectedStep}"><span>${i + 1}</span><strong>${escape(s.name)}</strong><small>${escape(operations.find(o => o.id === s.operation)?.type || 'Operation')}</small><em>${s.mandatory ? 'Required' : 'Optional'}</em></button><div class="step-reorder"><button type="button" data-move="${i}" data-delta="-1" aria-label="Move ${escape(s.name)} up" ${i === 0 ? 'disabled' : ''}>↑</button><button type="button" data-move="${i}" data-delta="1" aria-label="Move ${escape(s.name)} down" ${i === draft.steps.length - 1 ? 'disabled' : ''}>↓</button><button type="button" data-remove="${i}" aria-label="Remove ${escape(s.name)}">×</button></div></li>`).join('');
  const step = draft.steps[selectedStep];
  stepActions.hidden = !step;
  $('#step-form').hidden = !step;
  $('#no-step').hidden = !!step;
  if (step) {
    for (const name of ['name', 'operation', 'description', 'configuration']) $('#step-form').elements[name].value = step[name];
    $('#step-form').elements.mandatory.value = String(step.mandatory);
    renderCapabilityPickers(step);
    for (const name of ['name', 'operation', 'description', 'configuration', 'mandatory']) $('#step-form').elements[name].disabled = !!step.definitionId;
    $('#copy-step').hidden = !step.definitionId;
    $('#save-reusable-step').hidden = !!step.definitionId;
    $('#step-definition-status').textContent = step.definitionId ? 'Saved reusable definition · read-only. Copy to edit.' : 'Editable working step · not saved as reusable.';
  }
  updateDirty();
}
function openEditor(mode) {
  if (draft) { showSection('protocol-editor'); return; }
  const source = currentProtocol();
  if (mode === 'edit' && source.protected) return;
  draft = mode === 'new' ? { id: `personal-${++sequence}`, name: 'New personal protocol', description: '', protected: false, steps: [] } : clone(source);
  if (mode === 'copy') { draft.id = `personal-${++sequence}`; draft.name += ' (copy)'; draft.protected = false; }
  selectedStep = 0;
  originalDraft = JSON.stringify(draft);
  $('#editor-message').textContent = '';
  editorTab.hidden = false;
  renderPreparedSteps();
  renderEditor();
  showSection('protocol-editor');
}
function closeEditor() {
  draft = null;
  editorTab.hidden = true;
  showSection('setup');
}
$('#protocol-select').addEventListener('change', event => { selectProtocol(state, event.target.value); renderSetup(); });
$('#session-template').addEventListener('change', event => { selectTemplate(state, event.target.value); renderSetup(); });
$('#session-steps').addEventListener('change', event => {
  const step = currentProtocol().steps.find(s => s.id === event.target.dataset.step);
  if (!step || step.mandatory) return;
  state.included = state.included.filter(id => id !== step.id);
  if (event.target.checked) state.included.push(step.id);
  renderSetup();
});
$('#session-device-list').addEventListener('change', event => {
  const id = event.target.dataset.device;
  if (!id) return;
  state.selectedDevices = state.selectedDevices.filter(value => value !== id);
  if (event.target.checked) state.selectedDevices.push(id);
  renderSetup();
});
for (const mode of ['new', 'edit', 'copy']) $(`#${mode}-protocol`).addEventListener('click', () => openEditor(mode));
editorTab.addEventListener('click', () => showSection('protocol-editor'));
$('#protocol-name').addEventListener('input', event => { draft.name = event.target.value; updateDirty(); });
$('#protocol-summary').addEventListener('input', event => { draft.description = event.target.value; updateDirty(); });
$('#step-form').addEventListener('submit', event => event.preventDefault());
$('#step-form').addEventListener('change', event => {
  const control = event.target;
  if (!control.dataset.capability || draft.steps[selectedStep]?.definitionId) return;
  assignCapability(draft.steps[selectedStep], control.dataset.kind, control.dataset.capability, control.checked);
  const kind = control.dataset.kind, id = control.dataset.capability;
  const scroll = control.closest('.capability-options').scrollTop;
  renderCapabilityPickers(draft.steps[selectedStep]);
  const replacement = $(`.capability-picker[data-kind="${kind}"] input[data-capability="${id}"]`);
  replacement.closest('.capability-options').scrollTop = scroll;
  replacement.focus({ preventScroll: true });
  updateDirty();
});
$('#step-form').addEventListener('click', event => {
  const button = event.target.closest('[data-remove-capability]');
  if (!button || draft.steps[selectedStep]?.definitionId) return;
  const kind = button.dataset.kind;
  assignCapability(draft.steps[selectedStep], kind, button.dataset.removeCapability, false);
  renderCapabilityPickers(draft.steps[selectedStep]);
  $(`.capability-picker[data-kind="${kind}"] summary`).focus();
  updateDirty();
});
$('#step-form').addEventListener('input', event => {
  const control = event.target;
  if (control.dataset.capability) return;
  const step = draft.steps[selectedStep];
  if (!step || step.definitionId) return;
  if (control.name === 'mandatory') step.mandatory = control.value === 'true';
  else if (control.name === 'operation') {
    const op = operations.find(o => o.id === control.value);
    Object.assign(step, { operation: op.id, required: [...op.required], optional: [...op.optional], description: op.description });
  } else step[control.name] = control.value;
  // Keep typing focus/caret; refresh only the ordered list, not the form.
  const active = control.name;
  const start = control.selectionStart;
  const end = control.selectionEnd;
  renderEditor();
  const replacement = $('#step-form').elements[active];
  replacement.focus();
  if (start !== null && ['text', 'textarea'].includes(replacement.type)) replacement.setSelectionRange(start, end);
});
$('#add-step').addEventListener('click', () => {
  const definitionId = $('#add-operation').value;
  const id = `added-${++sequence}`;
  draft.steps.push(definitionId === 'blank' ? { id, name: '', operation: operations[0].id, description: '', mandatory: true, required: [], optional: [], configuration: '' } : savedOccurrence(state, definitionId, id));
  selectedStep = draft.steps.length - 1;
  renderEditor();
});
$('#copy-step').addEventListener('click', () => {
  draft.steps[selectedStep] = copyStepToEdit(state, draft.steps[selectedStep], draft.steps);
  $('#editor-message').textContent = 'Editable copy created. The saved definition is unchanged.';
  renderEditor();
});
$('#save-reusable-step').addEventListener('click', () => {
  try {
    draft.steps[selectedStep] = saveReusableStep(state, draft.steps[selectedStep], currentExperimenter());
    renderPreparedSteps();
    renderEditor();
    $('#editor-message').textContent = 'Reusable step saved for the current demonstration experimenter. Protocol changes are not yet saved.';
  } catch (error) { $('#editor-message').textContent = error.message; }
});
$('#editor-steps').addEventListener('click', event => {
  if (event.target.closest('[data-drag-step]')) return;
  const select = event.target.closest('[data-select-step]');
  const move = event.target.closest('[data-move]');
  const remove = event.target.closest('[data-remove]');
  if (select) selectedStep = Number(select.dataset.selectStep);
  if (move) {
    const from = Number(move.dataset.move), to = from + Number(move.dataset.delta);
    const selectedId = draft.steps[selectedStep]?.id;
    moveStep(draft.steps, draft.steps[from].id, draft.steps[to].id, to > from);
    selectedStep = draft.steps.findIndex(step => step.id === selectedId);
  }
  if (remove) { draft.steps.splice(Number(remove.dataset.remove), 1); selectedStep = Math.max(0, Math.min(selectedStep, draft.steps.length - 1)); }
  renderEditor();
});

// Pointer dragging starts only on a handle. Step identity carries all configuration.
let stepDrag = null;
$('#editor-steps').addEventListener('pointerdown', event => {
  const handle = event.target.closest('[data-drag-step]');
  if (!handle || event.button !== 0) return;
  event.preventDefault();
  stepDrag = { id: handle.dataset.dragStep, pointerId: event.pointerId, startY: event.clientY, active: false, targetId: null, after: false };
  handle.setPointerCapture(event.pointerId);
});
document.addEventListener('pointermove', event => {
  if (!stepDrag || stepDrag.pointerId !== event.pointerId) return;
  if (!stepDrag.active && Math.abs(event.clientY - stepDrag.startY) < 4) return;
  stepDrag.active = true;
  const rows = [...$('#editor-steps').children];
  rows.forEach(row => row.classList.remove('drop-before', 'drop-after'));
  rows.find(row => row.dataset.stepId === stepDrag.id)?.classList.add('is-dragging');
  const bounds = $('#editor-steps').getBoundingClientRect();
  if (event.clientX < bounds.left - 20 || event.clientX > bounds.right + 20) { stepDrag.targetId = null; return; }
  const target = rows.find(row => event.clientY < row.getBoundingClientRect().bottom) || rows.at(-1);
  const rect = target.getBoundingClientRect();
  stepDrag.targetId = target.dataset.stepId;
  stepDrag.after = event.clientY > rect.top + rect.height / 2;
  target.classList.add(stepDrag.after ? 'drop-after' : 'drop-before');
  // Permit dragging through a list taller than its scrolling editor viewport.
  const viewport = editor.getBoundingClientRect();
  if (event.clientY > viewport.bottom - 35) editor.scrollTop += 16;
  else if (event.clientY < viewport.top + 35) editor.scrollTop -= 16;
});
function finishStepDrag(event) {
  if (!stepDrag || event.pointerId !== stepDrag.pointerId) return;
  if (event.type === 'pointerup' && stepDrag.active && stepDrag.targetId) {
    const selectedId = draft.steps[selectedStep]?.id;
    moveStep(draft.steps, stepDrag.id, stepDrag.targetId, stepDrag.after);
    selectedStep = draft.steps.findIndex(step => step.id === selectedId);
  }
  stepDrag = null;
  renderEditor();
}
document.addEventListener('pointerup', finishStepDrag);
document.addEventListener('pointercancel', finishStepDrag);
$('#save-protocol').addEventListener('click', () => {
  if (!draft.name.trim() || draft.steps.some(s => !s.name.trim())) { $('#editor-message').textContent = 'Provide a protocol name and a name for every step.'; return; }
  saveProtocol(state, draft);
  renderSetup();
  closeEditor();
});
$('#cancel-protocol').addEventListener('click', () => {
  if (JSON.stringify(draft) === originalDraft) closeEditor();
  else discardDialog.showModal();
});
discardDialog.addEventListener('close', () => { if (discardDialog.returnValue === 'discard') closeEditor(); discardDialog.returnValue = ''; });
renderSetup();
