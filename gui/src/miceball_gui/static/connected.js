// Framework snapshots are display inputs, never a browser-owned lifecycle.
import { confirmStop } from './stop-confirmation.mjs';
const $ = selector => document.querySelector(selector);
const pretty = value => JSON.stringify(value, null, 2);
let socket, browserId, current = null, confirmed = false, refreshing = false, busy = false;
const waiting = new Map();
let outcomes = [];
try { const stored = JSON.parse(sessionStorage.getItem('miceball-pending') || '[]');
  if (Array.isArray(stored)) outcomes = stored.filter(o => o && typeof o.request_id === 'string' && typeof o.instance_id === 'string');
} catch (_) {}
const save = () => sessionStorage.setItem('miceball-pending', pretty(outcomes));

$('.topbar__eyebrow').textContent = 'Miceball';
$('.topbar').insertAdjacentHTML('beforeend', `<div><span id="connection-state" role="status">Connecting</span>
  <button id="view-only" type="button">View Only</button><button id="take-over" type="button">Take Over</button></div>`);
$('.alerts').hidden = true;
$('.setup-demo-note').textContent = 'Controller connection unconfirmed';
$('.identity-selects').innerHTML = ['Experimenter', 'Project', 'Animal'].map(name =>
  `<label>${name}<input id="working-${name.toLowerCase()}" type="text"></label>`).join('');
$('#animal-summary').remove();
for (const input of $('.session-identity-grid').querySelectorAll('input')) input.value = '';
for (const small of $('.session-identity-grid').querySelectorAll('small')) small.textContent = '';
$('.setup-card[aria-labelledby="template-title"]').innerHTML = '<h3>Protocol</h3><label>Protocol name (optional)<input id="working-protocol" type="text"></label>';
$('[aria-labelledby="notes-title"] textarea').value = '';
$('.device-card .demo-chip').textContent = 'Unconfirmed';
$('.device-list').innerHTML = `<select id="inventory-node" aria-label="Configured AcquisitionNode"></select>
  <button id="load-inventory" type="button">Refresh inventory</button><div id="device-selection"></div>
  <details><summary>Device declarations</summary><pre id="inventory-result"></pre></details>`;
$('[aria-labelledby="storage-title"]').innerHTML = `<h3>Deployment configuration</h3>
  <label>Session configuration (JSON)<textarea id="launch-configuration" rows="9" spellcheck="false"></textarea></label>
  <details><summary>Scientific outputs</summary><label>Scientific outputs (JSON)<textarea id="launch-outputs" rows="5" spellcheck="false">[]</textarea></label></details>`;
$('.readiness-card').innerHTML = '<h3>Accepted Session configuration</h3><pre id="accepted-configuration"></pre>';
$('.launch-session-demo').id = 'launch-session';
$('#launch-session').innerHTML = '<strong>Launch Session</strong><span>Controller connection unconfirmed</span>';
$('#launch-demo-note').textContent = '';
$('#panel-session').innerHTML = `<h2>Session</h2><dl id="session-status"></dl>
  <div class="session-context-links"><button id="start-session" type="button">Start Session</button>
  <button id="normal-stop" type="button">Stop Session</button><button id="release-session" type="button">Release Session</button></div>
  <h3>Operations</h3><div id="operation-results" role="status"></div><h3>Lifecycle</h3><pre id="session-lifecycle"></pre>`;
$('#panel-experiment').innerHTML = `<h2>Experiment</h2><p id="active-experiment"></p>
  <label>Experiment ID<input id="experiment-id" type="text"></label>
  <label>Experiment configuration (JSON)<textarea id="experiment-configuration" rows="10" spellcheck="false"></textarea></label>
  <label>Scientific outputs (JSON)<textarea id="experiment-outputs" rows="5" spellcheck="false">[]</textarea></label>
  <button id="start-experiment" type="button">Start Experiment</button><button id="stop-experiment" type="button">Stop Experiment</button>
  <button id="reconcile-expiry" type="button">Check expiry</button><pre id="experiment-state"></pre>`;
for (const section of ['analysis', 'storage', 'services', 'parameters']) {
  $(`#panel-${section}`).replaceChildren(Object.assign(document.createElement('p'), {textContent: `${section[0].toUpperCase()+section.slice(1)} integration unavailable in this unit.`}));
}
const selections = new Map();
let inventory = null;

function controls() {
  const status = current?.status;
  const can = confirmed && current?.control?.controlling && !busy
    && !outcomes.some(o => ['pending', 'uncertain'].includes(o.status));
  $('#launch-session').disabled = !can || Boolean(status?.session_id);
  $('#launch-configuration').readOnly = Boolean(status?.session_id);
  $('#launch-outputs').readOnly = Boolean(status?.session_id);
  for (const input of $('#panel-setup').querySelectorAll('input, textarea')) input.disabled = Boolean(status?.session_id) || !confirmed || !current?.control?.controlling;
  $('#start-session').disabled = !can || status?.session_state !== 'initialized';
  $('#normal-stop').disabled = !can || !status?.session_id;
  $('#release-session').disabled = !can || !['completed', 'failed', 'aborted'].includes(status?.session_state);
  $('#start-experiment').disabled = !can || status?.session_state !== 'running' || Boolean(status?.active_experiment_id);
  $('#stop-experiment').disabled = !can || !status?.active_experiment_id;
  $('#reconcile-expiry').disabled = !can || !status?.active_experiment_id;
  $('#take-over').disabled = !confirmed || busy;
  $('#view-only').disabled = !confirmed || busy;
  $('#load-inventory').disabled = !confirmed || busy;
  $('#experiment-configuration').readOnly = Boolean(status?.active_experiment_id);
  $('#experiment-outputs').readOnly = Boolean(status?.active_experiment_id);
  for (const input of $('#device-selection').querySelectorAll('input')) input.disabled = !can || Boolean(status?.session_id);
}

function request(operation, parameters = {}, session_id = null) {
  if (socket?.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Backend disconnected; outcome unconfirmed'));
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const uncertain = reason => Object.assign(new Error(reason), {request_id: `${browserId}-${id}`, instance_id: current?.instance_id});
    const timer = setTimeout(() => { waiting.delete(id); reject(uncertain('Response timeout; outcome unconfirmed')); }, 30000);
    waiting.set(id, {resolve, reject, timer, uncertain});
    socket.send(JSON.stringify({id, operation, session_id, parameters}));
  });
}

function requireResult(reply) {
  const result = reply.result;
  if (!result || result.status !== 'succeeded') throw new Error(result?.error || reply.error || result?.status || reply.status);
  return result.outcome.details;
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    current = requireResult(await request('read_controller_state'));
    confirmed = true;
    for (const operation of current.pending_operations) {
      if (!outcomes.some(o => o.request_id === operation.request_id && o.instance_id === current.instance_id)) {
        outcomes.push({operation: operation.operation, request_id: operation.request_id,
          instance_id: current.instance_id, status: 'pending'});
      }
    }
    $('#connection-state').textContent = `${current.controller_id} · ${current.control.controlling ? 'Controlling' : 'View Only'}`;
    $('.setup-demo-note').textContent = current.status.session_id ? 'Accepted Session configuration is fixed' : current.control.controlling ? 'Session preparation' : 'View Only';
    $('#launch-session span').textContent = current.control.controlling ? 'Controller launch' : 'View Only';
    $('#accepted-configuration').textContent = pretty(current.configuration);
    $('#session-status').textContent = `${current.status.session_id || 'No active Session'} · ${current.status.session_state || 'No Session'}`;
    $('#session-lifecycle').textContent = pretty(current.session_lifecycle);
    $('#active-experiment').textContent = current.status.active_experiment_id || 'No active Experiment';
    $('#experiment-state').textContent = pretty(current.experiments);
    const choice = $('#inventory-node');
    if (pretty([...choice.options].map(o => o.value)) !== pretty(current.configured_nodes)) {
      choice.replaceChildren(...current.configured_nodes.map(id => Object.assign(document.createElement('option'), {value: id, textContent: id})));
    }
    for (const entry of outcomes.filter(o => ['pending', 'uncertain'].includes(o.status))) {
      const result = requireResult(await request('read_operation_outcome', {target_request_id: entry.request_id, instance_id: entry.instance_id}));
      entry.status = result.status;
      entry.result = result.result;
    }
    save();
    $('#operation-results').replaceChildren(...outcomes.map(entry => {
      const details = document.createElement('details'), summary = document.createElement('summary'), data = document.createElement('pre');
      summary.textContent = `${entry.operation} · ${entry.status}`;
      data.textContent = pretty(entry); details.append(summary, data); return details;
    }));
  } catch (error) {
    confirmed = false;
    $('#connection-state').textContent = `Unconfirmed · ${error.message}`;
  } finally { refreshing = false; controls(); }
}

async function command(operation, parameters = {}, session_id = current?.status?.session_id || null) {
  if (!confirmed || busy || (!current.control.controlling && !['view_only', 'take_browser_control'].includes(operation))) return;
  busy = true; controls();
  try {
    const reply = await request(operation, parameters, session_id);
    const result = reply.result;
    outcomes.push({operation, instance_id: reply.instance_id, request_id: result?.request_id,
      status: result?.status || reply.status, result: result || reply});
    save();
  } catch (error) {
    if (error.request_id && error.instance_id) { outcomes.push({operation, status: 'uncertain', request_id: error.request_id, instance_id: error.instance_id}); save(); }
    $('#operation-results').textContent = `Uncertain: ${error.message}. No automatic replay.`;
  } finally { busy = false; controls(); await refresh(); }
}

function parse(selector) { return JSON.parse($(selector).value); }
function run(action) {
  return () => { try { action(); } catch (error) { $('#operation-results').textContent = error.message; } };
}
$('#take-over').onclick = () => command('take_browser_control', {}, null);
$('#view-only').onclick = () => command('view_only', {}, null);
$('#launch-session').onclick = run(() => {
  const config = parse('#launch-configuration'), metadata = {...(config.session_parameters || {})};
  for (const field of ['experimenter', 'project', 'animal']) {
    const value = $(`#working-${field}`).value.trim(); if (value) metadata[field] = value;
  }
  const notes = $('[aria-labelledby="notes-title"] textarea').value.trim();
  if (notes) metadata.notes = notes;
  const name = $('.session-identity-grid input[type="text"]').value.trim();
  if (name) metadata.name = name;
  const date = $('.session-identity-grid input[type="date"]').value;
  if (date) metadata.date = date;
  const number = $('.session-identity-grid input[type="number"]').value;
  if (number) metadata.number = Number(number);
  if (Object.keys(metadata).length) config.session_parameters = metadata;
  const protocol = $('#working-protocol').value.trim();
  if (protocol) config.protocol_reference = protocol;
  return command('launch_session', {selections: Object.fromEntries(selections),
    config_parameters: config, scientific_outputs: parse('#launch-outputs')}, null);
});
$('#start-session').onclick = () => command('start_launched_session');
$('#normal-stop').onclick = () => {
  const sid = current.status.session_id;
  confirmStop('Session', () => command('normal_stop_session', {}, sid), 'Request Normal Stop and preservation of acquired data. Confirmation does not establish cleanup or durable completion.');
};
$('#release-session').onclick = () => {
  if ($('#release-confirmation')) return;
  const sid = current.status.session_id;
  const dialog = document.createElement('dialog'); dialog.className = 'catalog-dialog';
  dialog.id = 'release-confirmation'; dialog.setAttribute('aria-labelledby', 'release-confirmation-title');
  dialog.innerHTML = '<form method="dialog"><h2 id="release-confirmation-title">Release Session?</h2><p>Controller will verify terminal preservation and cleanup before releasing the Session binding.</p><div class="catalog-dialog__actions"><button value="cancel">Cancel</button><button value="release">Release Session</button></div></form>';
  dialog.onclose = () => { if (dialog.returnValue === 'release') command('release_session', {}, sid); dialog.remove(); };
  document.body.append(dialog); dialog.showModal();
};
$('#start-experiment').onclick = run(() => command('start_launched_experiment', {experiment_id: $('#experiment-id').value,
  configuration: parse('#experiment-configuration'), scientific_outputs: parse('#experiment-outputs')}));
$('#stop-experiment').onclick = () => {
  const id = current.status.active_experiment_id;
  const sid = current.status.session_id;
  confirmStop('Experiment', () => command('stop_launched_experiment', {experiment_id: id}, sid), 'Request early Stop and preservation of acquired data. The Session remains active.');
};
$('#reconcile-expiry').onclick = () => command('reconcile_launched_experiment_expiry', {experiment_id: current.status.active_experiment_id});
$('#load-inventory').onclick = async () => {
  const node = $('#inventory-node').value;
  try {
    inventory = requireResult(await request('get_node_inventory', {node_id: node}));
    $('#inventory-result').textContent = pretty(inventory);
    $('#device-selection').replaceChildren(...inventory.devices.map(device => {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.checked = (selections.get(node) || []).some(d => d.device_id === device.device_id);
      input.onchange = () => { const ids = new Set(selections.get(node)?.map(d => d.device_id));
        input.checked ? ids.add(device.device_id) : ids.delete(device.device_id);
        const values = inventory.devices.filter(d => ids.has(d.device_id));
        values.length ? selections.set(node, values) : selections.delete(node); };
      label.append(input, document.createTextNode(device.device_id)); return label;
    }));
    controls();
  } catch (error) { $('#inventory-result').textContent = `Inventory unconfirmed: ${error.message}`; }
};

function connect() {
  confirmed = false; controls();
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === 'connected') { browserId = message.browser_id; refresh(); return; }
    const pending = waiting.get(message.id);
    if (pending) { clearTimeout(pending.timer); waiting.delete(message.id); pending.resolve(message); }
  };
  socket.onclose = () => {
    confirmed = false; controls(); $('#connection-state').textContent = 'Backend disconnected · last-known state';
    for (const pending of waiting.values()) { clearTimeout(pending.timer); pending.reject(pending.uncertain('Connection lost; outcome uncertain')); }
    waiting.clear(); setTimeout(connect, 2000);
  };
}
connect();
setInterval(() => { if (socket?.readyState === WebSocket.OPEN) refresh(); }, 2000);
