import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
const origin = process.env.MICEBALL_EXPECTED_ORIGIN, inventory = JSON.parse(process.env.MICEBALL_EXPECTED_INVENTORY);
const errors = [], requests = [];
let controlling = true, hold = false, release, connection;
const snapshot = () => ({controller_id: 'controller', instance_id: 'expected-owner', browser_control_required: true,
  control: {controlling, generation: 1}, configured_nodes: ['node'], configured_services: [],
  pending_operations: [], configuration: null, status: {session_id: null}, experiments: []});
page.on('pageerror', error => errors.push(error.message));
await page.routeWebSocket('**/ws', route => {
  connection = route;
  route.onMessage(async raw => {
    const message = JSON.parse(raw); requests.push(message);
    let details;
    if (message.operation === 'estimate_experiment_storage') {
      const response = await page.request.post(`${origin}/test/estimate`, {headers: {Origin: origin}, data: message.parameters});
      details = await response.json();
      if (!response.ok()) {
        route.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'expected-owner', result: {status: 'failed', error: details.error}}));
        return;
      }
      if (hold) { hold = false; await new Promise(resolve => {release = resolve;}); }
    } else if (message.operation === 'get_node_inventory') details = inventory;
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
  await page.locator('#load-inventory').click();
  await page.locator('#session-device-list input').check();
  await page.locator('[data-setup-parameters]').click();
  await page.locator('[data-parameter-participant]').check();
  await page.locator('#experiment-duration').fill('2');
  await page.locator('[data-scientific-output]').check();
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('217.03 KiB'));
  assert.equal(await page.locator('[data-recording-budget]').isVisible(), false);
  assert.equal(await page.locator('[data-framework-field="preservationBudget"]').isVisible(), false);
  await page.getByRole('button', {name: 'Adjust budgets', exact: true}).click();
  const recording = page.locator('[data-recording-budget]');
  assert.equal(await recording.getAttribute('placeholder'), '222240');
  await recording.fill('222239');
  assert.equal(await recording.evaluate(input => input.checkValidity()), false);
  await recording.fill('500000');
  assert.equal(await recording.evaluate(input => input.checkValidity()), true);
  await page.locator('#experiment-duration').fill('3');
  await page.waitForFunction(() => document.querySelector('[data-recording-budget]')?.placeholder === '263680');
  assert.equal(await recording.inputValue(), '500000');
  await recording.locator('xpath=following-sibling::button').click();
  assert.equal(await recording.inputValue(), '');
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
  const fpsEmpty = page.getByLabel('fps', {exact: true}).locator('xpath=ancestor::div[contains(@class,"parameter-override")][1]').locator('[data-null-parameter]');
  await fpsEmpty.check();
  await page.waitForFunction(() => document.querySelector('[data-expected-size]')?.textContent.includes('Unavailable'));
  assert.equal(await recording.isVisible(), true);
  assert.equal(await recording.getAttribute('placeholder'), 'Explicit budget required');
  await recording.fill('500000');
  await page.locator('[data-framework-field="preservationBudget"]').fill('600000');
  await fpsEmpty.uncheck();
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
  for (const width of [1440, 800]) {
    await page.setViewportSize({width, height: 1000});
    await page.locator('#panel-parameters .view-heading').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('[data-expected-size]').isVisible(), true);
    assert.equal(await page.locator('[data-expected-size]').evaluate(e => e.scrollWidth <= e.clientWidth + 1), true);
    if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/expected-size-${width}.png`, fullPage: true});
  }
  assert.deepEqual(errors, []);
  console.log('PASS: production Parameters, owner-generated estimates, single-copy aggregate, ordinary automatic budgets, smaller/larger overrides, recalculation, return-to-auto, stale reply, authority, reconnect and two viewports.');
} finally {await browser.close();}
