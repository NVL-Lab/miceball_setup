// Real shared presenters; transport responses are controlled, not live readiness.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
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
const snapshot = () => ({controller_id: 'feedback', instance_id: instance,
  control: {controlling: Boolean(acceptedConfiguration), generation: 0},
  status: {session_id: acceptedConfiguration?.session_id || null, session_state: acceptedConfiguration ? 'running' : null,
    active_experiment_id: activeExperiment, experiment_lifecycle_evidence: lifecycle},
  configuration: acceptedConfiguration, experiments: reportedExperiments, configured_nodes: ['node'], pending_operations: []});
const reply = (route, message, status, details, error) => route.send(JSON.stringify({type: 'result',
  id: message.id, instance_id: instance, result: {status, error, outcome: {details}}}));
await page.routeWebSocket('**/ws', route => {
  connection = route;
  route.onMessage(raw => {
    const message = JSON.parse(raw); requests.push(message.operation);
    if (message.operation === 'read_controller_state') reply(route, message, 'succeeded', snapshot());
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
try {
  await page.goto(process.env.MICEBALL_BROWSER_ORIGIN);
  await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
  await section(page, 'services');
  const services = page.locator('#panel-services');
  await services.locator('[data-expand-service]').first().click();
  assert.doesNotMatch(await services.innerText(), /simulat|fictional|fixture|transport example|preview refreshed/i);
  assert.match(await services.locator('.services-feedback').innerText(), /readiness checks.*unavailable/i);
  assert.equal(await services.locator('[data-readiness]').count(), 5);
  assert.equal(await services.locator('[data-readiness]').first().isDisabled(), true);
  await disabledStyle(services.locator('[data-readiness]').first());
  assert.equal(await services.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'true');
  await services.locator('[data-readiness]').first().evaluate(button => button.click());
  assert.equal(await services.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'true');
  await services.locator('[data-detail="History"]').click();
  assert.doesNotMatch(await services.innerText(), /simulat|fictional|fixture|transport example/i);
  await services.locator('[data-detail="Dependencies"]').click();
  assert.match(await services.innerText(), /readback is not connected/);
  await services.locator('[data-detail="Status"]').click();
  assert.match(await services.locator('.services-detail-content').innerText(), /Unknown \(unverified\)/);
  await services.locator('[data-refresh-services]').click();
  assert.match(await services.locator('.services-feedback').innerText(), /unavailable/i);
  assert.doesNotMatch(await services.innerText(), /preview refreshed|fixture/i);
  assert.equal(await services.locator('#services-refresh').isDisabled(), true);
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
      await disabledStyle(services.locator('[data-readiness]').first());
      await disabledStyle(services.locator('[data-shutdown-framework]'));
      await shot(`services-feedback-${width}-${theme}`);
    }
  }
  assert.ok(requests.every(operation => operation === 'read_controller_state'));
  await section(page, 'session');
  for (const selector of ['[data-start-session]', '[data-stop-session]', '[data-release-session]']) {
    await disabledStyle(page.locator(selector));
    await page.locator(selector).evaluate(button => button.click());
  }
  assert.ok(requests.every(operation => operation === 'read_controller_state'));
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
    identityInventory.devices.map(device => `node/${device.device_id}`));
  await section(page, 'session');
  await page.locator('[data-prepare-free-operation]').click();
  await page.locator('.experiment-additional-devices').evaluate(element => element.open = true);
  await page.evaluate(() => {window.__auditMarkupExecuted = 0;});
  for (const [index, device] of identityInventory.devices.entries()) {
    const checkbox = page.locator('[data-session-experiment-device]').nth(index);
    await checkbox.hover();
    assert.equal(await page.evaluate(() => window.__auditMarkupExecuted), 0, 'inventory identity must not become executable markup');
    assert.equal(await checkbox.getAttribute('data-session-experiment-device'), `node/${device.device_id}`);
    assert.equal(await checkbox.getAttribute('onpointerover'), null);
    await checkbox.check();
    assert.equal(await checkbox.isChecked(), true);
    const validation = page.locator('[data-validate-device]').nth(index);
    assert.equal(await validation.getAttribute('data-validate-device'), `node/${device.device_id}`);
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
  const populatedSummary = `gain: 3.5 · gate: No · label: ${labelValue}`;
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
  await baseline.close(); await demo.close();
  assert.deepEqual(errors, []);
  await writeFile(`${directory}/feedback.json`, JSON.stringify({result: 'PASS', transport: 'controlled WebSocket replies; real GUI/backend shell', inventoryRequests: inventoryRequests.length, screenshots}, null, 2));
  console.log('PASS: working/executed and empty/populated summaries in both modes, escaped parameter text, unchanged outgoing overrides, and device-selection injection regression');
} catch (error) {
  await shot('feedback-failure'); console.error(errors); throw error;
} finally {await browser.close();}
}
