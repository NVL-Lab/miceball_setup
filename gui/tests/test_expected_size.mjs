import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
const origin = process.env.MICEBALL_EXPECTED_ORIGIN, inventory = JSON.parse(process.env.MICEBALL_EXPECTED_INVENTORY);
const errors = [], requests = [];
let controlling = true, hold = false, release, connection, alter = null;
let session = null, holdInventory = false, releaseInventory;
const snapshot = () => ({controller_id: 'controller', instance_id: 'expected-owner', browser_control_required: true,
  control: {controlling, generation: 1}, configured_nodes: ['node'], configured_services: [],
  pending_operations: [], configuration: session, status: {session_id: session?.session_id || null,
    session_state: session ? 'running' : null}, experiments: []});
page.on('pageerror', error => errors.push(error.message));
await page.routeWebSocket('**/ws', route => {
  connection = route;
  route.onMessage(async raw => {
    const message = JSON.parse(raw); requests.push(message);
    let details;
    if (message.operation === 'estimate_experiment_storage') {
      const response = await page.request.post(`${origin}/test/estimate`, {headers: {Origin: origin},
        data: {...message.parameters, expected_session_id: message.session_id}});
      details = await response.json();
      if (!response.ok()) {
        route.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'expected-owner', result: {status: 'failed', error: details.error}}));
        return;
      }
      if (hold) { hold = false; await new Promise(resolve => {release = resolve;}); }
      if (alter === 'configuration') details.configuration.duration_s += 1;
      if (alter === 'outputs') details.scientific_outputs = [];
      alter = null;
    } else if (message.operation === 'get_node_inventory') {
      details = structuredClone(inventory);
      if (session) details.configured_parameters = {scope: 'session', session_id: session.session_id,
        values: {camera: {frames_per_collect: 2, frame_width: 4, frame_height: 2}}};
      if (holdInventory) { holdInventory = false; await new Promise(resolve => {releaseInventory = resolve;}); }
    }
    else if (message.operation === 'list_artifact_destinations') details = {
      storage_id: 'storage', default_destination_id: 'default', destinations: [
        {destination_id: 'default', name: 'Default', root: '/test', enabled: true, validation: {status: 'unverified'}}]};
    else {
      if (message.operation === 'view_only') controlling = false;
      if (message.operation === 'take_browser_control') controlling = true;
      details = snapshot();
    }
    route.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'expected-owner',
      result: {status: 'succeeded', outcome: {details}}}));
  });
  route.send(JSON.stringify({type: 'connected', browser_id: 'expected-browser'}));
});
const estimates = () => requests.filter(r => r.operation === 'estimate_experiment_storage');
try {
  await page.goto(origin);
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  assert.match(await page.locator('.readiness-card ul').textContent(), /Select the devices needed/);
  await page.locator('#load-inventory').click();
  await page.locator('#session-device-list input').check();
  await page.locator('[data-setup-parameters]').click();
  await page.locator('[data-parameter-participant]').check();
  await page.locator('#experiment-duration').fill('2');
  await page.locator('[data-scientific-output]').check();
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('217.03 KiB'));
  await page.locator('[data-scientific-output]').uncheck();
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.value === '0');
  await page.locator('[data-scientific-output]').check();
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.value === '222240');
  await page.locator('[data-parameter-participant]').uncheck();
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('Set duration and participating'));
  await page.locator('[data-parameter-participant]').check();
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.value === '222240');
  assert.equal(await page.evaluate(async () => {
    const {state} = await import(new URL('./protocol-setup.js', document.baseURI));
    const {resolveParameterContext} = await import(new URL('./parameter-context.mjs', document.baseURI));
    const configuration = resolveParameterContext(state).configuration;
    return configuration.preservationBudget === null && Object.keys(configuration.recordingBudgets).length === 0;
  }), true, 'Calculated display values must not become explicit overrides');
  assert.equal(await page.locator('[data-recording-budget]').isVisible(), true);
  assert.equal(await page.locator('[data-framework-field="preservationBudget"]').isVisible(), true);
  assert.equal(await page.getByRole('button', {name: 'Adjust budgets', exact: true}).count(), 0);
  const recording = page.locator('[data-recording-budget]');
  assert.equal(await recording.inputValue(), '222240');
  assert.match(await recording.locator('..').textContent(), /Automatic:/);
  assert.equal(await recording.locator('..').getByRole('button').count(), 0);
  // Both typed configuration and output identity key orders differ from the GUI.
  for (const mismatch of ['configuration', 'outputs']) {
    alter = mismatch;
    await page.locator('#experiment-duration').fill(mismatch === 'configuration' ? '2.1' : '2.2');
    await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('confirmation does not match'));
    assert.equal(await recording.inputValue(), '');
  }
  await page.locator('#experiment-duration').fill('2');
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.value === '222240');
  await recording.fill('222239');
  assert.equal(await recording.evaluate(input => input.checkValidity()), false);
  await recording.fill('500000');
  assert.equal(await recording.evaluate(input => input.checkValidity()), true);
  await page.locator('#experiment-duration').fill('3');
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.placeholder === '263680');
  assert.equal(await recording.inputValue(), '500000');
  await recording.locator('xpath=following-sibling::button').click();
  assert.equal(await recording.inputValue(), '263680');
  assert.equal(await recording.locator('..').getByRole('button').count(), 0);
  hold = true;
  await page.locator('#experiment-duration').fill('4');
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('Calculating'));
  await page.locator('#experiment-duration').fill('5');
  while (!release) await new Promise(resolve => setTimeout(resolve, 1));
  release();
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.placeholder === '346560');
  assert.equal(estimates().at(-1).parameters.configuration.duration_s, 5);
  await page.getByLabel('fps', {exact: true}).fill('');
  // Empty removes the override; installation FPS remains 10.
  await page.getByLabel('fps', {exact: true}).fill('20');
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.placeholder === '553760');
  const rate = page.getByLabel('fps', {exact: true});
  await rate.fill(''); await rate.pressSequentially('1e999');
  assert.equal(await rate.evaluate(input => input.validity.badInput), true);
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('Unavailable'));
  assert.equal(await rate.evaluate(input => input.validity.badInput), true, 'Estimate feedback must preserve native invalid drafts');
  await rate.fill('20');
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.placeholder === '553760');
  assert.equal(await page.locator('[data-null-parameter]').count(), 0);
  // Invalid input makes estimation unavailable without manufacturing nulls.
  await rate.fill('0');
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('Unavailable'));
  assert.equal(await recording.isVisible(), true);
  assert.equal(await recording.getAttribute('placeholder'), 'Explicit budget required');
  await recording.fill('500000');
  await page.locator('[data-framework-field="preservationBudget"]').fill('600000');
  await page.getByLabel('fps', {exact: true}).fill('20');
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.placeholder === '553760');
  assert.equal(await recording.inputValue(), '500000');
  assert.equal(await recording.evaluate(input => input.checkValidity()), false);
  await recording.locator('xpath=following-sibling::button').click();
  await page.locator('#view-only').click();
  await page.locator('html[data-control-mode="view-only"]').waitFor();
  assert.equal(await page.locator('#experiment-duration').isDisabled(), true);
  await page.locator('#take-over').click();
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  connection.close();
  await page.locator('#connection-state').filter({hasText: 'Backend disconnected'}).waitFor();
  assert.match(await page.locator('[data-expected-size]').textContent(), /Unavailable/);
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'setup'})));
  await page.locator('#load-inventory').click();
  await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
  await page.locator('[data-setup-parameters]').click();
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.placeholder === '553760');
  for (const theme of ['light', 'dark']) for (const width of [1440, 800]) {
    await page.setViewportSize({width, height: 1000});
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    await page.locator('#panel-parameters .view-heading').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('[data-expected-size]').isVisible(), true);
    assert.equal(await page.locator('[data-expected-size]').evaluate(e => e.scrollWidth <= e.clientWidth + 1), true);
    assert.equal(await page.locator('[data-expected-size]').evaluate(e => getComputedStyle(e).fontSize), '11px');
    if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/expected-size-${theme}-${width}.png`, fullPage: true});
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'setup'})));
    await page.locator('.readiness-card').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('.readiness-card li').evaluateAll(rows => rows.every(row =>
      row.children.length === 3 && row.children[1].getBoundingClientRect().right <= row.children[2].getBoundingClientRect().left)), true);
    if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/readiness-${theme}-${width}.png`, fullPage: true});
    await page.locator('[data-setup-parameters]').click();
  }
  // Reproduce a Session change while installation inventory is in flight.
  // The old response must not strand the new Session's inherited settings.
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'setup'})));
  holdInventory = true;
  await page.locator('#load-inventory').click();
  while (!releaseInventory) await new Promise(resolve => setTimeout(resolve, 1));
  const accepted = await page.request.post(`${origin}/test/session`, {headers: {Origin: origin}});
  assert.equal(accepted.ok(), true);
  session = await accepted.json();
  await page.locator('#accepted-configuration').filter({hasText: 'scoped-session'}).waitFor({state: 'attached'});
  releaseInventory();
  await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
  await page.locator('[data-prepare-free-operation]').click();
  assert.equal(await page.locator('.experiment-additional-devices').evaluate(e => e.open), true);
  await page.locator('.experiment-additional-devices').evaluate(e => e.open = false);
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'experiment'})));
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
  assert.equal(await page.locator('.experiment-additional-devices').evaluate(e => e.open), true, 'Required selection opens on navigation');
  await page.locator('[data-session-experiment-device]').check();
  assert.equal(await page.locator('[data-validate-device]').isDisabled(), true);
  await page.locator('[data-session-navigate="parameters"]').click();
  assert.equal(await page.getByLabel('frame_width', {exact: true}).inputValue(), '4');
  assert.equal(await page.getByLabel('frame_height', {exact: true}).inputValue(), '2');
  assert.equal(await page.getByLabel('fps', {exact: true}).inputValue(), '');
  assert.match(await page.getByLabel('fps', {exact: true}).locator('xpath=ancestor::div[contains(@class,"parameter-override")][1]').textContent(), /Not specified in confirmed configuration/);
  assert.match(await page.getByLabel('frame_width', {exact: true}).locator('xpath=ancestor::div[contains(@class,"parameter-override")][1]').textContent(), /Inherited requested/);
  await page.getByLabel('frame_width', {exact: true}).fill('8');
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'setup'})));
  await page.locator('#load-inventory').click();
  await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
  await page.locator('[data-session-navigate="parameters"]').click();
  assert.equal(await page.getByLabel('frame_width', {exact: true}).inputValue(), '8', 'Refresh must preserve explicit overrides');
  assert.equal(await page.locator('.device-validation-settings').evaluate(e => e.classList.contains('parameter-section')), true);
  assert.equal(await page.locator('#device-validation-maximum').inputValue(), '5');
  await page.locator('#experiment-duration').fill('10');
  await page.locator('[data-framework-field="experimentId"]').fill('prepared-experiment');
  await page.locator('[data-scientific-output]').check();
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('positive selected rate'));
  assert.equal(await recording.inputValue(), '');
  await page.getByLabel('fps', {exact: true}).fill('30');
  await page.waitForFunction(() => /^\d+$/.test(document.querySelector('[data-recording-budget]')?.value));
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
  assert.equal(await page.locator('[data-launch-experiment]').isEnabled(), true, 'Valid automatically budgeted preparation becomes eligible');
  await page.locator('[data-session-navigate="parameters"]').click();
  await recording.fill('1');
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
  assert.equal(await page.locator('[data-launch-experiment]').isDisabled(), true, 'Below-minimum explicit budget remains blocked');
  assert.deepEqual(errors, []);
  console.log('PASS: production Parameters, owner-generated estimates, single-copy aggregate, ordinary automatic budgets, smaller/larger overrides, recalculation, return-to-auto, stale reply, authority, reconnect and two viewports.');
} finally {await browser.close();}
