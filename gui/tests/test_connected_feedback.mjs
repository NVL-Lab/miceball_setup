// Real shared presenters; transport responses are controlled, not live readiness.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
import {verifyConfigurationIntegrity, verifyExperimentReconnection} from './test_configuration_integrity.mjs';
import {verifyGuiUsability} from './test_gui_usability.mjs';
if (!process.env.MICEBALL_BROWSER_ORIGIN) {
  console.log('Rendered feedback checks require the disposable Python fixture.');
} else {
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
const errors = [], requests = [], inventoryRequests = [], screenshots = [];
page.on('pageerror', error => errors.push(error.message));
const directory = process.env.MICEBALL_BROWSER_EVIDENCE;
await mkdir(directory, {recursive: true});
let connection, instance = 'feedback-instance', acceptedConfiguration = null;
let reportedExperiments = [], activeExperiment = null, lifecycle = [];
const experimentRequests = [];
let serviceResponse = 'unknown';
let serviceReason = 'Current readiness is unconfirmed';
let controllerResponse = 'succeeded';
const serviceRequests = [];
const snapshot = () => ({controller_id: 'feedback', instance_id: instance,
  control: {controlling: Boolean(acceptedConfiguration), generation: 0},
  status: {session_id: acceptedConfiguration?.session_id || null, session_state: acceptedConfiguration ? 'running' : null,
    active_experiment_id: activeExperiment, experiment_lifecycle_evidence: lifecycle},
  configuration: acceptedConfiguration, experiments: reportedExperiments, configured_nodes: ['node'], pending_operations: [],
  configured_services: ['controller', 'acquisition_node', 'ingestor', 'storage_manager', 'synchronization_manager'].map(component_type => ({component_type, component_id: component_type === 'acquisition_node' ? 'node' : component_type}))});
const reply = (route, message, status, details, error) => route.send(JSON.stringify({type: 'result',
  id: message.id, instance_id: instance, result: {status, error, outcome: {details}}}));
await page.routeWebSocket('**/ws', route => {
  connection = route;
  route.onMessage(raw => {
    const message = JSON.parse(raw); requests.push(message.operation);
    if (message.operation === 'read_controller_state') reply(route, message, controllerResponse,
      controllerResponse === 'succeeded' ? snapshot() : null, controllerResponse === 'succeeded' ? null : 'Controller unavailable');
    else if (message.operation === 'read_service_status') {
      serviceRequests.push({route, message});
      if (serviceResponse !== 'held') reply(route, message, 'succeeded', {
        participant: message.parameters.participant, current: ['ready', 'not-ready'].includes(serviceResponse),
        report: ['ready', 'not-ready'].includes(serviceResponse) ? {...message.parameters.participant,
          ready: serviceResponse === 'ready', required: true, reason: serviceResponse === 'ready' ? 'ready' : 'Dependency not ready'} : null,
        reason: ['ready', 'not-ready'].includes(serviceResponse) ? null : serviceReason, details: {}});
    }
    else if (message.operation === 'read_synchronization_status') reply(route, message, 'succeeded', {current: false, timing: null, reason: 'Unavailable'});
    else if (message.operation === 'get_node_inventory') inventoryRequests.push({route, message});
    else if (message.operation === 'start_launched_experiment') {
      experimentRequests.push(message);
      reply(route, message, 'rejected', null, 'Controlled fixture: acquisition is not executed');
    }
    else throw new Error(`Unexpected operation: ${message.operation}`);
  });
  route.send(JSON.stringify({type: 'connected', browser_id: 'feedback-browser'}));
});
const section = async (target, name) => {
  await target.locator('#navigation-toggle').click();
  await target.locator(`.nav-item[data-section="${name}"]`).click();
  await target.waitForTimeout(250);
};
const shot = async name => {
  await page.screenshot({path: `${directory}/${name}.png`, fullPage: true}); screenshots.push(name);
};
const buttonStyle = locator => locator.evaluate(button => {
  const style = getComputedStyle(button);
  return {background: style.backgroundColor, color: style.color, border: style.borderColor,
    cursor: style.cursor, opacity: style.opacity, shadow: style.boxShadow, transform: style.transform};
});
const disabledStyle = async locator => {
  assert.equal(await locator.isDisabled(), true);
  const style = await buttonStyle(locator);
  assert.equal(style.cursor, 'not-allowed');
  assert.equal(style.opacity, '1'); // Muted colors retain readable contrast without fading text.
  assert.equal(style.shadow, 'none');
  assert.equal(style.transform, 'none');
  const rgb = value => value.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => {
    const s = v / 255; return s <= .04045 ? s / 12.92 : ((s + .055) / 1.055) ** 2.4;
  }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
  const a = rgb(style.color), b = rgb(style.background);
  assert.ok((Math.max(a,b) + .05) / (Math.min(a,b) + .05) >= 4.5, 'disabled text remains readable');
  await locator.hover();
  assert.deepEqual(await buttonStyle(locator), style, 'disabled hover must not look enabled');
  return style;
};
async function verifyRenderingSafety() {
  const target = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const inventory = JSON.parse(process.env.MICEBALL_RENDERING_INVENTORY);
  const node = process.env.MICEBALL_RENDERING_NODE, text = process.env.MICEBALL_RENDERING_TEXT;
  const device = inventory.devices[0], product = device.scientific_products[0];
  const definitions = inventory.session_parameter_definitions[device.device_id];
  const names = Object.keys(definitions), submitted = [];
  const metadata = {name: text, experimenter: text, project: text, animal: text, notes: text, date: '2026-10-24'};
  const configuration = {session_id: 'rendering-session', selected_devices: inventory.devices,
    expected_runtime_participants: [{component_type: 'acquisition_node', component_id: node}],
    session_parameters: metadata, protocol_reference: null, storage_location: text, error_evidence_location: text};
  let controlling = true, executed = null;
  const state = () => ({controller_id: text, instance_id: 'rendering-instance',
    control: {controlling, generation: 1}, configuration, configured_nodes: [node], pending_operations: [],
    status: {session_id: configuration.session_id, session_state: 'running',
      active_experiment_id: executed?.experiment_id || null, experiment_lifecycle_evidence: []},
    experiments: executed ? [executed] : []});
  target.on('pageerror', error => errors.push(error.message));
  await target.addInitScript(() => {window.__renderingInjected = 0;});
  await target.routeWebSocket('**/ws', route => {
    route.onMessage(raw => {
      const message = JSON.parse(raw);
      let details, status = 'succeeded';
      if (message.operation === 'read_controller_state') details = state();
      else if (message.operation === 'get_node_inventory') {
        assert.equal(message.parameters.node_id, node); details = inventory;
      } else if (message.operation === 'start_launched_experiment') {
        submitted.push(message); status = 'rejected';
      } else throw new Error(`Unexpected rendering operation: ${message.operation}`);
      route.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'rendering-instance',
        result: {status, request_id: text, error: status === 'rejected' ? text : null, outcome: {details}}}));
    });
    route.send(JSON.stringify({type: 'connected', browser_id: 'rendering-browser'}));
  });
  const inert = async () => {
    assert.equal(await target.locator('[onpointerover], [onerror], [onfocus], [data-rendering-injected]').count(), 0);
    assert.equal(await target.evaluate(() => window.__renderingInjected), 0);
  };
  try {
    await target.goto(process.env.MICEBALL_BROWSER_ORIGIN);
    await target.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    assert.equal(await target.locator('#connection-state').innerText(), `${text} · Controlling`);
    assert.equal(await target.locator('#inventory-node').inputValue(), node);
    assert.equal(await target.locator('.session-identity-grid textarea[data-configuration-string]').inputValue(), text);
    for (const id of ['experimenter-select', 'project-select', 'animal-select']) {
      assert.equal(await target.locator(`#${id} option:checked`).innerText(), text);
    }
    assert.deepEqual(JSON.parse(await target.locator('#accepted-configuration').textContent()), configuration);
    await target.locator('[data-open-setup]').click();
    await target.locator('#load-inventory').click();
    await target.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
    assert.equal(await target.locator('#session-device-list input').getAttribute('data-device'), JSON.stringify([node, device.device_id]));
    assert.ok((await target.locator('#session-device-list').innerText()).includes(device.declared_capabilities[0]));
    await inert();
    await section(target, 'session');
    assert.ok((await target.locator('.session-information').innerText()).includes(text));
    await target.locator('[data-prepare-free-operation]').click();
    await target.locator('.experiment-additional-devices').evaluate(element => element.open = true);
    const participant = target.locator('[data-session-experiment-device]');
    await participant.check(); await participant.uncheck(); await participant.check();
    assert.equal(await participant.getAttribute('data-session-experiment-device'), JSON.stringify([node, device.device_id]));
    assert.equal(await target.locator('[data-validate-device]').getAttribute('data-validate-device'), JSON.stringify([node, device.device_id]));
    await target.locator('[data-session-navigate="parameters"]').click();
    await inert(); // Regression-first: unescaped bounds create handlers/elements here.
    for (const [index, name] of names.entries()) {
      const control = target.locator('[data-example-value]').nth(index), definition = definitions[name];
      assert.equal(await control.getAttribute('data-example-value'), JSON.stringify([node, device.device_id, name]));
      assert.ok((await control.locator('..').innerText()).includes(name));
      for (const [attribute, value] of [['min', definition.minimum ?? definition.exclusive_minimum], ['max', definition.maximum]]) {
        assert.equal(await control.getAttribute(attribute), value === undefined ? null : String(value));
      }
      await control.hover(); await inert();
    }
    const field = name => target.locator('[data-example-value]').nth(names.indexOf(name));
    await field('gain').fill('0');
    assert.equal(await field('gain').evaluate(input => input.checkValidity()), true);
    await field('gain').fill('11');
    assert.equal(await field('gain').evaluate(input => input.validity.rangeOverflow), true);
    await field('gain').fill('0');
    await field('gate').check(); await field('gate').uncheck();
    await field(text).fill(text);
    await target.locator('#experiment-duration').fill('2');
    await target.locator('[data-framework-field="experimentId"]').fill('rendering-experiment');
    await target.locator('[data-framework-field="preservationBudget"]').fill('100000');
    await target.locator('[data-recording-budget]').fill('100000');
    assert.equal(await target.locator('[data-recording-budget]').getAttribute('data-recording-budget'), node);
    const output = {source_node_id: node, source_device_id: device.device_id, data_product_id: product.data_product_id};
    assert.deepEqual(JSON.parse(await target.locator('[data-scientific-output]').getAttribute('data-scientific-output')), output);
    await target.locator('[data-scientific-output]').check();
    await target.locator('[data-return-session]').click();
    const summary = `gain: 0 · gate: No · ${text}: ${JSON.stringify(text).replaceAll('\u03a9', '\\u03a9')}`;
    assert.equal(await target.locator('.experiment-parameter-summary').innerText(), summary);
    await target.locator('[data-launch-experiment]').click();
    await target.locator('#operation-results').filter({hasText: 'rejected'}).waitFor();
    assert.equal(submitted.length, 1);
    assert.deepEqual(submitted[0].parameters.configuration.participating_devices, {[node]: [device.device_id]});
    assert.deepEqual(submitted[0].parameters.configuration.device_configurations,
      {[node]: {[device.device_id]: {gain: 0, gate: false, [text]: text}}});
    assert.deepEqual(submitted[0].parameters.scientific_outputs, [output]);
    await target.locator('#operation-results summary').last().click();
    assert.ok((await target.locator('#operation-results').innerText()).includes(text));
    await inert();
    executed = {experiment_id: 'rendering-experiment', configuration: submitted[0].parameters.configuration,
      scientific_outputs: submitted[0].parameters.scientific_outputs};
    await target.locator('.experiment-current-card h4').filter({hasText: 'executed'}).waitFor();
    assert.equal(await target.locator('.experiment-parameter-summary').innerText(), summary);
    await target.locator('[data-session-navigate="parameters"]').click();
    assert.equal(await field('gain').inputValue(), '0');
    assert.equal(await field('gate').isChecked(), false);
    assert.equal(await field(text).inputValue(), text);
    assert.equal(await field(text).isDisabled(), true);
    for (const [width, height] of [[1440, 1000], [800, 900]]) {
      await target.setViewportSize({width, height});
      for (const theme of ['light', 'dark']) {
        if (await target.locator('html').getAttribute('data-theme') !== theme) await target.locator('#theme-toggle').click();
        await inert();
        const name = `rendering-safety-${width}-${theme}`;
        await target.screenshot({path: `${directory}/${name}.png`, fullPage: true}); screenshots.push(name);
      }
    }
    await section(target, 'experiment');
    await target.locator('[data-show-experiment-parameters]').click();
    assert.ok((await target.locator('#experiment-parameters-drawer').innerText()).includes(text));
    await inert();
    controlling = false;
    await target.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
    await section(target, 'session');
    assert.equal(await target.locator('[data-start-session]').isDisabled(), true);
    await target.locator('[data-start-session]').evaluate(button => button.click());
    assert.equal(submitted.length, 1);
    await inert();
    assert.deepEqual(errors, []);
    console.log('PASS: nine adversarial bound cases; hostile node/device/capability/product/parameter/readback/error identities; numeric bounds, exact outgoing values, executed read-only values and View Only');
  } finally {await target.close();}
}
async function verifyMaintenanceBinding() {
  const target = await browser.newPage();
  const participant = {component_type: 'acquisition_node', component_id: 'node"&<id'};
  let authorizations = [{evidence_id: 'cleanup-authorization', payload: {decision: 'resume', target: participant,
    administrator_id: 'Lab Operator', details: {operation: 'cleanup_device_resources', command_id: 'cleanup-command',
      obligation: {session_id: 'historical-session', device_ids: ['camera']}}}}];
  const submitted = [];
  let controlling = true, attempt = null, sequence = 0, unknown = false;
  let ownerInstance = 'maintenance-instance', holdStatus = false, staleReply = null;
  const state = () => ({controller_id: 'feedback', instance_id: ownerInstance,
    control: {controlling, generation: 1}, status: {session_id: null, session_state: null},
    configuration: null, experiments: [], configured_nodes: [], configured_services: [participant], pending_operations: []});
  await target.routeWebSocket('**/ws', route => {
    route.onMessage(raw => {
      const request = JSON.parse(raw);
      if (request.operation === 'read_controller_state') { reply(route, request, 'succeeded', state()); return; }
      if (request.operation === 'read_service_status') {
        const response = {current: !unknown, report: unknown ? null : {...participant, ready: true, required: true, reason: 'ready'},
          reason: unknown ? 'Current readiness is unconfirmed' : null,
          details: {maintenance_attempt: attempt, recovery_authorizations: authorizations, operational_instance_id: 'maintenance-owner',
            readiness_error: unknown ? 'Dependency readiness is unknown: acquisition_node/offline-node' : undefined,
            dependency_readiness: [{participant: {component_type: 'acquisition_node', component_id: 'offline-node'}, service_readiness: null}],
            operational_retirement_confirmed: !attempt && !authorizations.length,
            retirement_delivery: {required: true, dependency_release_confirmed: false},
            remaining_obligations: ['Exact retained delivery obligation']}, participant};
        if (holdStatus) { holdStatus = false; staleReply = () => reply(route, request, 'succeeded', response); return; }
        reply(route, request, 'succeeded', response); return;
      }
      submitted.push(request);
      if (request.operation === 'stop_service') {
        attempt = {stop_attempt_id: `attempt-${++sequence}`, target: participant, outcome: 'blocked', blockers: ['Preservation incomplete'], failures: []};
        reply(route, request, 'failed', {outcome: 'blocked', attempt}, 'Closeout blocked');
      } else if (request.operation === 'kill_service' || request.operation === 'cancel_service') {
        assert.equal(request.parameters.stop_attempt_id, attempt.stop_attempt_id);
        attempt = null;
        reply(route, request, request.operation === 'kill_service' ? 'succeeded' : 'failed',
          {outcome: request.operation === 'kill_service' ? 'completed' : 'failed', termination_confirmed: request.operation === 'kill_service'});
      } else if (request.operation === 'cleanup_device_resources') {
        authorizations = [];
        reply(route, request, 'succeeded', {actual_outcome: 'succeeded', preservation: {archival_confirmed: true}});
      } else throw new Error(`Unexpected maintenance operation ${request.operation}`);
    });
    route.send(JSON.stringify({type: 'connected', browser_id: 'maintenance-browser'}));
  });
  try {
    await target.goto(process.env.MICEBALL_BROWSER_ORIGIN);
    await target.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    await section(target, 'services');
    await target.locator('[data-expand-service]').click();
    await target.locator('[data-mode="administrator"]').click();
    await target.locator('[data-danger-enter]').click();
    const authorize = async selector => {
      await target.locator(selector).click();
      const dialog = target.locator('.services-danger[open]');
      assert.equal(await dialog.locator('[data-live-confirm]').isDisabled(), true);
      await dialog.locator('[data-live-administrator]').fill('   ');
      assert.equal(await dialog.locator('[data-live-confirm]').isDisabled(), true);
      await dialog.locator('[data-live-administrator]').fill('Lab Operator');
      assert.equal(await dialog.locator('[data-live-authorized]').count(), 0);
      await dialog.locator('[data-live-confirm]').click();
    };
    await authorize('[data-stop-service]');
    const blockedDialog = target.locator('.services-danger[open]');
    await blockedDialog.locator('[data-live-choice]').waitFor();
    assert.match(await blockedDialog.innerText(), /attempt-1/);
    assert.match(await blockedDialog.innerText(), /Preservation incomplete/);
    assert.equal(await blockedDialog.locator('[data-live-confirm]').isDisabled(), true);
    await blockedDialog.locator('[data-admin-close]').click();
    assert.equal(submitted.length, 1); // Closing the choice never authorizes Cancel or Kill.
    await target.locator('[data-live-kill]').waitFor();
    assert.deepEqual(submitted[0].parameters, {participant, administrator_id: 'Lab Operator', authorized: true});
    await target.locator('.services-callout').filter({hasText: 'blocked'}).waitFor();
    await authorize('[data-live-kill]');
    await target.locator('.services-callout').filter({hasText: 'completed'}).waitFor();
    assert.deepEqual(submitted[1].parameters, {participant, administrator_id: 'Lab Operator', authorized: true, stop_attempt_id: 'attempt-1'});
    assert.equal(await target.locator('[data-live-kill]').count(), 0);
    await authorize('[data-stop-service]');
    await target.locator('[data-live-cancel]').waitFor();
    const cancelDialog = target.locator('.services-danger[open]');
    await cancelDialog.locator('[data-live-choice]').waitFor();
    await cancelDialog.locator('[data-live-choice]').selectOption('cancel_service');
    await cancelDialog.locator('[data-live-administrator]').fill('Lab Operator');
    assert.equal(await cancelDialog.locator('[data-live-authorized]').count(), 0);
    await cancelDialog.locator('[data-live-confirm]').click();
    await target.locator('.services-callout').filter({hasText: 'cancel_service'}).waitFor();
    assert.equal(submitted[3].parameters.stop_attempt_id, 'attempt-2');
    assert.equal(await target.locator('[data-live-kill]').count(), 0);
    await target.locator('[data-administrative="Supported recovery attempts"]').click();
    const recoveryDialog = target.locator('.services-danger[open]');
    assert.equal(await recoveryDialog.locator('[data-recovery-confirm]').isDisabled(), true);
    await recoveryDialog.locator('[data-recovery-administrator]').fill('operator');
    assert.equal(await recoveryDialog.locator('[data-recovery-confirm]').isDisabled(), true);
    await recoveryDialog.locator('[data-recovery-administrator]').fill('Lab Operator');
    await recoveryDialog.locator('[data-recovery-confirm]').click();
    await target.locator('.services-callout').filter({hasText: 'cleanup_device_resources'}).waitFor();
    assert.deepEqual(submitted[4].parameters, {participant, administrator_id: 'Lab Operator', authorized: true,
      authorization_evidence_id: 'cleanup-authorization', recovery_command_id: 'cleanup-command',
      obligation: {session_id: 'historical-session', device_ids: ['camera']}});
    controlling = false;
    await target.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
    assert.equal(await target.locator('[data-stop-service]').isDisabled(), true);
    await target.locator('[data-stop-service]').evaluate(button => button.dispatchEvent(new MouseEvent('click', {bubbles:true})));
    assert.equal(submitted.length, 5);
    assert.equal(await target.locator('[onpointerover], [onerror]').count(), 0);
    controlling = true;
    await target.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    await target.locator('[data-administrative="Supported recovery attempts"]').click();
    const feedback = await target.locator('.services-feedback').innerText();
    assert.match(feedback, /No supported exact-target recovery/);
    await target.waitForTimeout(4300); // More than two ordinary Controller refreshes.
    assert.equal(await target.locator('.services-feedback').innerText(), feedback);
    await target.locator('[data-administrative="Abandon outstanding obligations"]').click();
    const obligations = target.locator('.services-danger[open]');
    assert.match(await obligations.innerText(), /Exact retained delivery obligation/);
    assert.match(await obligations.innerText(), /Operational retirement, dependency-release confirmation and OS process exit are distinct/);
    await target.waitForTimeout(2200);
    assert.equal(await obligations.isVisible(), true);
    await obligations.locator('[data-admin-close]').click();
    assert.equal(await target.locator('[data-live-kill]').count(), 0);
    unknown = true;
    await target.locator('[data-readiness]').click();
    await target.getByText('Dependency readiness is unknown: acquisition_node/offline-node', {exact: true}).waitFor();
    assert.match(await target.locator('.services-detail-content').innerText(), /Current owner diagnostics/);
    assert.match(await target.locator('.service-status').innerText(), /availability unknown/);
    assert.match(await target.locator('section.inline-service-details').innerText(), /offline-node/);
    assert.equal(await target.locator('[data-live-kill]').count(), 0);
    assert.equal(submitted.length, 5); // Inspection never sends a maintenance mutation.
    unknown = false; holdStatus = true;
    await target.locator('[data-readiness]').click();
    for (let i = 0; i < 100 && !staleReply; i++) await target.waitForTimeout(20);
    assert.ok(staleReply);
    unknown = true; ownerInstance = 'replacement-controller';
    // The changed Controller replaces projections and obtains new diagnostics.
    await target.waitForTimeout(4300);
    staleReply();
    await target.waitForTimeout(200);
    assert.match(await target.locator('.service-status').innerText(), /availability unknown/);
    assert.match(await target.locator('section.inline-service-details').innerText(), /offline-node/);
    console.log('PASS: production Services confirmation, exact Stop/Kill/Cancel target and attempt, blocked/completed feedback, View Only and inert service identity; controlled transport only');
  } finally { await target.close(); }
}
try {
  await verifyMaintenanceBinding();
  await verifyGuiUsability(browser, process.env.MICEBALL_BROWSER_ORIGIN, JSON.parse(process.env.MICEBALL_INTEGRITY).session, section, directory);
  await verifyExperimentReconnection(browser, process.env.MICEBALL_BROWSER_ORIGIN, JSON.parse(process.env.MICEBALL_MONITORING), section);
  await verifyConfigurationIntegrity(browser, process.env.MICEBALL_BROWSER_ORIGIN, JSON.parse(process.env.MICEBALL_INTEGRITY), section);
  await verifyRenderingSafety();
  await page.goto(process.env.MICEBALL_BROWSER_ORIGIN);
  await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
  await section(page, 'services');
  const services = page.locator('#panel-services');
  await services.locator('[data-expand-service]').first().click();
  assert.doesNotMatch(await services.innerText(), /simulat|fictional|fixture|transport example|preview refreshed/i);
  assert.match(await services.locator('.services-feedback').innerText(), /current checks|Checking readiness|readiness check completed/i);
  assert.equal(await services.locator('[data-readiness]').count(), 5);
  assert.equal(await services.locator('[data-readiness]').first().isEnabled(), true);
  assert.equal(await services.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'true');
  const ownerReport = services.locator('[data-owner-report]');
  await ownerReport.locator('summary').click();
  let previousReport = await ownerReport.elementHandle();
  await page.waitForFunction(element => !element.isConnected, previousReport);
  assert.equal(await ownerReport.evaluate(element => element.open), true, 'Automatic repaint preserves open Owner report');
  await ownerReport.locator('summary').click();
  previousReport = await ownerReport.elementHandle();
  await page.waitForFunction(element => !element.isConnected, previousReport);
  assert.equal(await ownerReport.evaluate(element => element.open), false, 'Deliberate closing survives automatic repaint');
  await services.locator('[data-expand-service]').nth(1).click();
  await ownerReport.locator('summary').click();
  await services.locator('[data-expand-service]').first().click();
  assert.equal(await ownerReport.evaluate(element => element.open), false);
  await services.locator('[data-expand-service]').nth(1).click();
  assert.equal(await ownerReport.evaluate(element => element.open), true, 'Services retain independent disclosure choices');
  await services.locator('[data-expand-service]').first().click();
  await services.locator('[data-readiness]').first().evaluate(button => button.click());
  assert.equal(await services.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'true');
  await services.locator('[data-detail="History"]').click();
  assert.doesNotMatch(await services.innerText(), /simulat|fictional|fixture|transport example/i);
  await services.locator('[data-detail="Dependencies"]').click();
  assert.match(await services.innerText(), /No current dependency confirmation|Services start independently/);
  await services.locator('[data-detail="Status"]').click();
  assert.match(await services.locator('.services-detail-content').innerText(), /Unknown/);
  await services.locator('[data-refresh-services]').click();
  assert.match(await services.locator('.services-feedback').innerText(), /current checks|Checking readiness|readiness check completed/i);
  assert.doesNotMatch(await services.innerText(), /preview refreshed|fixture/i);
  assert.equal(await services.locator('#services-refresh').isEnabled(), true);
  assert.equal(await services.locator('#services-refresh').inputValue(), '10');
  await services.locator('#services-refresh').selectOption('0');
  serviceResponse = 'ready';
  await services.locator('[data-readiness]').first().click();
  await services.locator('.service-status').first().filter({hasText: 'Ready · current confirmation'}).waitFor();
  const finalFeedback = await services.locator('.services-feedback').innerText();
  assert.match(finalFeedback, /readiness check completed; Ready/);
  previousReport = await ownerReport.elementHandle();
  await page.waitForFunction(element => !element.isConnected, previousReport);
  assert.equal(await services.locator('.services-feedback').innerText(), finalFeedback, 'Controller repaint retains completed feedback');
  serviceResponse = 'not-ready';
  await services.locator('[data-readiness]').first().click();
  await services.locator('.services-feedback').filter({hasText: 'check completed; Not ready'}).waitFor();
  serviceResponse = 'unknown';
  serviceReason = '<img data-readiness-injected src=x onerror="window.__readinessInjected=1">';
  await services.locator('[data-readiness]').first().click();
  await services.locator('.services-feedback').filter({hasText: serviceReason}).waitFor();
  assert.equal(await services.locator('[data-readiness-injected]').count(), 0);
  assert.equal(await page.evaluate(() => window.__readinessInjected), undefined);
  serviceReason = 'Current readiness is unconfirmed';
  serviceResponse = 'ready';
  await services.locator('[data-readiness]').first().click();
  await services.locator('.service-status').first().filter({hasText: 'Ready · current confirmation'}).waitFor();
  serviceResponse = 'unknown';
  await services.locator('[data-readiness]').first().click();
  await services.locator('.service-status').first().filter({hasText: 'Last known: Ready · availability unknown'}).waitFor();
  serviceResponse = 'held';
  const beforeHeld = serviceRequests.length;
  await services.locator('[data-readiness]').first().click();
  await services.locator('[data-readiness]').first().filter({hasText: 'Checking'}).waitFor();
  await services.locator('[data-readiness]').first().evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', {bubbles:true})); });
  assert.equal(serviceRequests.length, beforeHeld + 1);
  const delayedService = serviceRequests.at(-1);
  reply(delayedService.route, delayedService.message, 'succeeded', {current: false, report: null, reason: 'Invalid current report', details: {}});
  await services.locator('[data-readiness]').first().filter({hasText: 'Check readiness'}).waitFor();
  assert.match(await services.locator('.services-feedback').innerText(), /availability unknown.*Invalid current report/);
  assert.equal(await services.locator('[data-expand-service]').count(), 5, 'Unknown status does not remove configured membership');
  await services.locator('[data-readiness]').first().click();
  await services.locator('[data-readiness]').first().filter({hasText: 'Checking'}).waitFor();
  const obsolete = serviceRequests.at(-1), afterObsolete = serviceRequests.length;
  instance = 'feedback-new-owner';
  for (let i = 0; i < 100 && serviceRequests.length < afterObsolete + 5; i++) await page.waitForTimeout(50);
  assert.equal(serviceRequests.length, afterObsolete + 5);
  reply(obsolete.route, obsolete.message, 'succeeded', {current: true, report: {...obsolete.message.parameters.participant, ready: true, required: true, reason: 'obsolete ready'}, details: {}});
  for (const pending of serviceRequests.slice(afterObsolete)) reply(pending.route, pending.message, 'succeeded', {current: false, report: null, reason: 'New owner unconfirmed', details: {}});
  await services.locator('[data-readiness]').first().filter({hasText: 'Check readiness'}).waitFor();
  assert.equal(await services.locator('.service-status').first().innerText(), 'Last known: Ready · availability unknown', 'An old owner response cannot promote current availability or erase historical confirmation');
  serviceResponse = 'ready';
  await services.locator('[data-readiness]').first().click();
  await services.locator('.service-status').first().filter({hasText: 'current confirmation'}).waitFor();
  serviceResponse = 'held';
  await services.locator('[data-readiness]').first().click();
  await services.locator('[data-readiness]').first().filter({hasText: 'Checking'}).waitFor();
  const beforeLoss = serviceRequests.at(-1);
  controllerResponse = 'rejected';
  await page.locator('#connection-state').filter({hasText: 'Unconfirmed'}).waitFor();
  await services.locator('.service-status').first().filter({hasText: 'availability unknown'}).waitFor();
  assert.doesNotMatch(await services.locator('.services-feedback').innerText(), /check completed; Ready/);
  controllerResponse = 'succeeded';
  await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
  reply(beforeLoss.route, beforeLoss.message, 'succeeded', {current: true, report: {...beforeLoss.message.parameters.participant, ready: true, required: true, reason: 'late ready'}, details: {}});
  await page.waitForTimeout(50);
  assert.equal(await services.locator('.service-status').first().innerText(), 'Last known: Ready · availability unknown', 'An earlier check cannot re-confirm availability after a newer communication loss');
  serviceResponse = 'unknown';
  await services.locator('[data-expand-service]').first().focus();
  await page.keyboard.press('Enter');
  assert.equal(await services.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'false');
  await page.keyboard.press('Space');
  assert.equal(await services.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'true');
  await services.locator('[data-mode="administrator"]').click();
  assert.doesNotMatch(await page.locator('.services-danger[open]').innerText(), /demo|simulat|fixture/i);
  await page.locator('[data-danger-enter]').click();
  assert.doesNotMatch(await services.innerText(), /demo|simulat|fictional|fixture|transport example/i);
  assert.equal(await services.locator('[data-stop-service]').isDisabled(), true);
  assert.equal(await services.locator('[data-shutdown-framework]').isDisabled(), true);
  for (const [width, height] of [[1440, 1000], [800, 900]]) {
    await page.setViewportSize({width, height});
    for (const theme of ['light', 'dark']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
      assert.equal(await services.locator('[data-readiness]').first().isEnabled(), true);
      await disabledStyle(services.locator('[data-shutdown-framework]'));
      await shot(`services-feedback-${width}-${theme}`);
    }
  }
  assert.ok(requests.every(operation => ['read_controller_state', 'read_service_status'].includes(operation)));
  await section(page, 'session');
  for (const selector of ['[data-start-session]', '[data-stop-session]', '[data-release-session]']) {
    await disabledStyle(page.locator(selector));
    await page.locator(selector).evaluate(button => button.click());
  }
  assert.ok(requests.every(operation => ['read_controller_state', 'read_service_status'].includes(operation)));
  await section(page, 'setup');
  await page.locator('[data-open-setup]').click();
  const refresh = page.locator('#load-inventory'), status = page.locator('#inventory-status');
  const enabledRefresh = await buttonStyle(refresh);
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  assert.equal(await refresh.isDisabled(), true);
  const pendingRefresh = await disabledStyle(refresh);
  assert.notDeepEqual(pendingRefresh, enabledRefresh);
  for (const theme of ['light', 'dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
    await disabledStyle(refresh);
    await shot(`inventory-disabled-${theme}`);
  }
  assert.equal(await page.locator('#inventory-node').isDisabled(), true);
  await refresh.evaluate(button => {button.click(); button.dispatchEvent(new MouseEvent('click', {bubbles: true}));});
  assert.equal(inventoryRequests.length, 1);
  await shot('inventory-feedback-pending');
  await page.waitForTimeout(2200); // A Controller-state refresh must not release the request guard.
  assert.equal(await refresh.isDisabled(), true);
  assert.equal(inventoryRequests.length, 1);
  const inventory = {devices: [{device_id: 'actual-device', enabled: true, declared_capabilities: ['actual-capability'], scientific_products: []}], session_parameter_definitions: {}};
  reply(inventoryRequests[0].route, inventoryRequests[0].message, 'succeeded', inventory);
  await status.filter({hasText: 'inventory confirmed; readiness remains Controller-owned'}).waitFor();
  assert.equal(await refresh.isEnabled(), true);
  assert.deepEqual(await buttonStyle(refresh), enabledRefresh, 'successful reply restores enabled appearance');
  assert.match(await page.locator('#session-device-list').innerText(), /actual-device/);
  assert.equal(await page.locator('#session-device-list input').count(), 1);
  await refresh.click();
  await page.waitForFunction(() => document.querySelector('#inventory-status').textContent.includes('Refreshing'));
  reply(inventoryRequests[1].route, inventoryRequests[1].message, 'failed', null, 'Owner inventory remains unconfirmed');
  await status.filter({hasText: 'Owner inventory remains unconfirmed'}).waitFor();
  assert.equal(await refresh.isEnabled(), true);
  assert.match(await page.locator('#session-device-list').innerText(), /actual-device/);
  assert.equal(await page.locator('#session-device-list input').isDisabled(), true);
  await shot('inventory-feedback-failed');
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  reply(inventoryRequests[2].route, inventoryRequests[2].message, 'pending', null);
  await status.filter({hasText: 'pending'}).waitFor();
  assert.equal(await refresh.isEnabled(), true);
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  reply(inventoryRequests[3].route, inventoryRequests[3].message, 'uncertain', null, 'Transport outcome remains unverified');
  await status.filter({hasText: 'Transport outcome remains unverified'}).waitFor();
  assert.equal(await refresh.isEnabled(), true);
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  const disconnected = connection;
  await disconnected.close({code: 1001, reason: 'controlled connection loss'});
  await status.filter({hasText: /unconfirmed.*[Cc]onnection|unconfirmed.*disconnected/}).waitFor();
  assert.equal(await refresh.isDisabled(), true);
  await shot('inventory-feedback-disconnected');
  await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
  assert.equal(await refresh.isEnabled(), true);
  assert.equal(inventoryRequests.length, 5); // No automatic replay after reconnect.
  assert.equal(await status.getAttribute('aria-busy'), null);
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  instance = 'replacement-instance';
  await page.waitForTimeout(2200); // Let the existing read-only refresh observe the replacement.
  reply(inventoryRequests[5].route, inventoryRequests[5].message, 'succeeded', {...inventory, devices: [{...inventory.devices[0], device_id: 'stale-device'}]});
  await status.filter({hasText: 'unconfirmed'}).waitFor();
  assert.doesNotMatch(await page.locator('#session-device-list').innerText(), /stale-device/);
  assert.equal(await refresh.isEnabled(), true);
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  reply(inventoryRequests[6].route, inventoryRequests[6].message, 'succeeded', inventory);
  await status.filter({hasText: 'inventory confirmed'}).waitFor();
  assert.equal(await page.locator('#session-device-list input').isEnabled(), true);
  await shot('inventory-feedback-recovered');
  const identityInventory = JSON.parse(process.env.MICEBALL_DEVICE_IDENTITY_INVENTORY);
  const parameterDevice = identityInventory.devices[0].device_id;
  identityInventory.session_parameter_definitions[parameterDevice] = {
    gain: {type: 'number', minimum: 0}, gate: {type: 'boolean'}, label: {type: 'string'}};
  acceptedConfiguration = {session_id: 'identity-session', selected_devices: identityInventory.devices,
    expected_runtime_participants: [{component_type: 'acquisition_node', component_id: 'node'}],
    session_parameters: {name: 'Identity regression'}, protocol_reference: null};
  await page.locator('#accepted-configuration').filter({hasText: 'identity-session'}).waitFor({state: 'attached'});
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  reply(inventoryRequests.at(-1).route, inventoryRequests.at(-1).message, 'succeeded', identityInventory);
  await status.filter({hasText: 'inventory confirmed'}).waitFor();
  assert.deepEqual(await page.locator('#session-device-list input').evaluateAll(inputs => inputs.map(input => input.dataset.device)),
    identityInventory.devices.map(device => JSON.stringify(['node', device.device_id])));
  await section(page, 'session');
  await page.locator('[data-prepare-free-operation]').click();
  await page.locator('.experiment-additional-devices').evaluate(element => element.open = true);
  await page.evaluate(() => {window.__auditMarkupExecuted = 0;});
  for (const [index, device] of identityInventory.devices.entries()) {
    const checkbox = page.locator('[data-session-experiment-device]').nth(index);
    await checkbox.hover();
    assert.equal(await page.evaluate(() => window.__auditMarkupExecuted), 0, 'inventory identity must not become executable markup');
    assert.equal(await checkbox.getAttribute('data-session-experiment-device'), JSON.stringify(['node', device.device_id]));
    assert.equal(await checkbox.getAttribute('onpointerover'), null);
    await checkbox.check();
    assert.equal(await checkbox.isChecked(), true);
    const validation = page.locator('[data-validate-device]').nth(index);
    assert.equal(await validation.getAttribute('data-validate-device'), JSON.stringify(['node', device.device_id]));
    assert.equal(await validation.getAttribute('onpointerover'), null);
    await validation.hover();
    assert.equal(await page.evaluate(() => window.__auditMarkupExecuted), 0);
    await checkbox.uncheck();
    assert.equal(await checkbox.isChecked(), false);
    await checkbox.check();
  }
  assert.equal(await page.locator('#panel-session [onpointerover]').count(), 0);
  assert.equal(await page.locator('#panel-session metadata').count(), 0);
  assert.equal(await page.locator('.experiment-parameter-summary').innerText(), 'No explicit adapter overrides.');
  await shot('device-identities-inert');
  await page.locator('[data-session-navigate="parameters"]').click();
  const labelValue = '<img src=x onerror="window.__summaryInjected=1"> & "quoted"';
  await page.evaluate(() => {window.__summaryInjected = 0;});
  await page.locator('[data-example-value]').nth(0).fill('3.5');
  await page.locator('[data-example-value]').nth(1).check();
  await page.locator('[data-example-value]').nth(1).uncheck();
  await page.locator('[data-example-value]').nth(2).fill(labelValue);
  await page.locator('#experiment-duration').fill('2');
  await page.locator('[data-framework-field="experimentId"]').fill('identity-regression');
  await page.locator('[data-framework-field="preservationBudget"]').fill('100000');
  await page.locator('[data-recording-budget]').fill('100000');
  await page.locator('[data-return-session]').click();
  const populatedSummary = `gain: 3.5 · gate: No · label: ${JSON.stringify(labelValue)}`;
  assert.equal(await page.locator('.experiment-parameter-summary').innerText(), populatedSummary);
  assert.equal(await page.locator('.experiment-parameter-summary img').count(), 0);
  assert.equal(await page.evaluate(() => window.__summaryInjected), 0);
  await shot('connected-working-summary');
  await page.locator('[data-launch-experiment]').click();
  await page.locator('#operation-results').filter({hasText: 'rejected'}).waitFor();
  assert.equal(experimentRequests.length, 1);
  assert.deepEqual(experimentRequests[0].parameters.configuration.participating_devices.node,
    identityInventory.devices.map(device => device.device_id));
  assert.deepEqual(experimentRequests[0].parameters.configuration.device_configurations.node[parameterDevice],
    {gain: 3.5, gate: false, label: labelValue});
  assert.equal(await page.evaluate(() => window.__auditMarkupExecuted), 0);
  // Controlled owner readback exercises executed presentation, not acquisition.
  activeExperiment = 'identity-regression';
  reportedExperiments = [{experiment_id: activeExperiment, scientific_outputs: [],
    configuration: structuredClone(experimentRequests[0].parameters.configuration)}];
  await page.locator('.experiment-current-card h4').filter({hasText: 'executed'}).waitFor();
  assert.equal(await page.locator('.experiment-parameter-summary').innerText(), populatedSummary);
  await page.locator('[data-session-navigate="parameters"]').click();
  assert.equal(await page.locator('[data-example-value]').first().inputValue(), '3.5');
  assert.equal(await page.locator('[data-example-value]').first().isDisabled(), true);
  await page.locator('[data-return-session]').click();
  await shot('connected-executed-summary');
  lifecycle = [{experiment_id: activeExperiment, event_type: 'experiment_stop', sequence: 1, session_time_s: 2}];
  activeExperiment = 'without-overrides';
  reportedExperiments.push({experiment_id: activeExperiment, scientific_outputs: [],
    configuration: {...structuredClone(experimentRequests[0].parameters.configuration), device_configurations: {}}});
  lifecycle.push({experiment_id: activeExperiment, event_type: 'experiment_start', sequence: 2, session_time_s: 2});
  await page.locator('[data-session-step]').filter({hasText: 'without-overrides'}).click();
  assert.equal(await page.locator('.experiment-parameter-summary').innerText(), 'No explicit adapter overrides.');
  assert.equal(await page.evaluate(() => window.__summaryInjected), 0);
  const baseline = await browser.newPage({viewport: {width: 1440, height: 1000}});
  await baseline.goto(process.env.MICEBALL_DEMO_ORIGIN);
  const demo = await browser.newPage({viewport: {width: 1440, height: 1000}});
  await demo.goto(process.env.MICEBALL_DEMO_CURRENT_ORIGIN);
  // Native fieldset inheritance is the other disabled mechanism in the GUI.
  // Exercise browser semantics with the actual application styles, without an operation.
  await demo.evaluate(() => {
    const form = document.createElement('form'); form.id = 'disabled-inheritance-test';
    form.style.cssText = 'position:fixed;z-index:1000;top:100px;left:250px';
    form.innerHTML = '<fieldset disabled><legend>Test only</legend><button type="button">Inherited disabled</button></fieldset><button type="button">Enabled comparison</button>';
    document.body.append(form);
  });
  for (const theme of ['light', 'dark']) {
    if (await demo.locator('html').getAttribute('data-theme') !== theme) await demo.locator('#theme-toggle').click();
    const inherited = demo.locator('#disabled-inheritance-test fieldset button');
    assert.equal(await inherited.getAttribute('disabled'), null);
    await disabledStyle(inherited);
    assert.equal(await demo.locator('#disabled-inheritance-test > button').isEnabled(), true);
  }
  await demo.locator('#disabled-inheritance-test').evaluate(form => form.remove());
  for (const target of [baseline, demo]) {
    if (await target.locator('html').getAttribute('data-theme') !== 'light') await target.locator('#theme-toggle').click();
  }
  for (const target of [baseline, demo]) {
    await section(target, 'services');
    await target.locator('[data-expand-service]').first().click();
  }
  assert.equal(await demo.locator('#panel-services').innerText(), await baseline.locator('#panel-services').innerText());
  const demoBefore = await baseline.locator('#panel-services').screenshot();
  assert.deepEqual(await demo.locator('#panel-services').screenshot(), demoBefore);
  for (const theme of ['light', 'dark']) {
    for (const target of [baseline, demo]) if (await target.locator('html').getAttribute('data-theme') !== theme) await target.locator('#theme-toggle').click();
    // Ordinary enabled buttons retain exactly their previous computed appearance.
    assert.deepEqual(await buttonStyle(demo.locator('[data-readiness]').first()), await buttonStyle(baseline.locator('[data-readiness]').first()));
    await section(demo, 'storage');
    await demo.locator('[data-storage-workspace="collection"]').click();
    await disabledStyle(demo.locator('[data-store-review]'));
    await demo.locator('[data-add-session]').first().click();
    assert.equal(await demo.locator('[data-store-review]').isEnabled(), true);
    await demo.locator('[data-remove-session]').first().click();
    await disabledStyle(demo.locator('[data-store-review]'));
    await demo.locator('[data-storage-workspace="deletion"]').click();
    await disabledStyle(demo.locator('[data-delete-review]'));
    await section(demo, 'setup');
    await demo.locator('#protocol-select').selectOption('');
    await disabledStyle(demo.locator('#edit-protocol'));
    await section(demo, 'services');
    await demo.screenshot({path: `${directory}/disabled-demo-${theme}.png`, fullPage: true});
  }
  for (const target of [baseline, demo]) {
    await target.locator('[data-readiness]').first().click();
    assert.match(await target.locator('.services-feedback').innerText(), /Readiness preview requested/);
    await target.locator('[data-mode="administrator"]').click();
    assert.match(await target.locator('.services-danger[open]').innerText(), /This demo sends no commands/);
    await target.locator('[data-danger-enter]').click();
    await target.locator('[data-stop-service]').click();
    assert.match(await target.locator('dialog[open]').innerText(), /Start orderly-stop simulation/);
    await target.locator('[data-admin-close]').click();
  }
  await demo.screenshot({path: `${directory}/services-feedback-demo.png`, fullPage: true});
  await demo.reload();
  await section(demo, 'session');
  await demo.locator('[data-session-step]').first().click();
  assert.match(await demo.locator('.experiment-parameter-summary').innerText(), /Example exposure \(ms\): 10/);
  await demo.locator('[data-prepare-experiment]').click();
  await demo.locator('[data-session-navigate="parameters"]').click();
  await demo.locator('[data-example-value]').first().fill('25');
  await demo.locator('[data-return-session]').click();
  assert.match(await demo.locator('.experiment-parameter-summary').innerText(), /Example exposure \(ms\): 25/);
  while (await demo.locator('.experiment-devices input[type="checkbox"]:checked').count()) {
    const id = await demo.locator('.experiment-devices input[type="checkbox"]:checked').first().getAttribute('data-session-experiment-device');
    await demo.locator(`[data-session-experiment-device=${JSON.stringify(id)}]`).first().uncheck();
  }
  assert.equal(await demo.locator('.experiment-parameter-summary').innerText(), 'No applicable example parameters.');
  // Exercise the shared Setup escaping helper through editable application data.
  const protocolText = '"quoted" & &#34; <img data-rendering-injected src=x onerror="window.__protocolInjected=1"> \u03a9';
  await demo.evaluate(() => {window.__protocolInjected = 0;});
  await section(demo, 'setup');
  await demo.locator('#copy-protocol').click();
  await demo.locator('#protocol-name').fill(protocolText);
  await demo.locator('#protocol-summary').fill(protocolText);
  if (await demo.locator('#copy-step').isVisible()) await demo.locator('#copy-step').click();
  await demo.locator('#step-form [name="name"]').fill(protocolText);
  await demo.locator('#step-form [name="description"]').fill(protocolText);
  assert.equal(await demo.locator('#editor-steps [data-select-step] strong').first().innerText(), protocolText);
  assert.ok((await demo.locator('#editor-steps [data-drag-step]').first().getAttribute('aria-label')).includes(protocolText));
  await demo.locator('#save-protocol').click();
  assert.equal(await demo.locator('#protocol-select option:checked').innerText(), protocolText);
  assert.equal(await demo.locator('#protocol-description').innerText(), protocolText);
  assert.ok((await demo.locator('#session-steps').innerText()).includes(protocolText));
  assert.equal(await demo.locator('[onerror], [data-rendering-injected]').count(), 0);
  assert.equal(await demo.evaluate(() => window.__protocolInjected), 0);
  await baseline.close(); await demo.close();
  assert.deepEqual(errors, []);
  await writeFile(`${directory}/feedback.json`, JSON.stringify({result: 'PASS', transport: 'controlled WebSocket replies; real GUI/backend shell', inventoryRequests: inventoryRequests.length, screenshots}, null, 2));
  console.log('PASS: working/executed and empty/populated summaries in both modes, escaped parameter text, unchanged outgoing overrides, and device-selection injection regression');
} catch (error) {
  await shot('feedback-failure'); console.error(errors); throw error;
} finally {await browser.close();}
}
