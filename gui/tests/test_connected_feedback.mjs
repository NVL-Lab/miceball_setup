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
let connection, instance = 'feedback-instance';
const snapshot = () => ({controller_id: 'feedback', instance_id: instance,
  control: {controlling: false, generation: 0}, status: {session_id: null},
  configuration: null, experiments: [], configured_nodes: ['node'], pending_operations: []});
const reply = (route, message, status, details, error) => route.send(JSON.stringify({type: 'result',
  id: message.id, instance_id: instance, result: {status, error, outcome: {details}}}));
await page.routeWebSocket('**/ws', route => {
  connection = route;
  route.onMessage(raw => {
    const message = JSON.parse(raw); requests.push(message.operation);
    if (message.operation === 'read_controller_state') reply(route, message, 'succeeded', snapshot());
    else if (message.operation === 'get_node_inventory') inventoryRequests.push({route, message});
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
      await shot(`services-feedback-${width}-${theme}`);
    }
  }
  assert.ok(requests.every(operation => operation === 'read_controller_state'));
  await section(page, 'setup');
  await page.locator('[data-open-setup]').click();
  const refresh = page.locator('#load-inventory'), status = page.locator('#inventory-status');
  await refresh.click();
  await status.filter({hasText: 'Refreshing inventory'}).waitFor();
  assert.equal(await refresh.isDisabled(), true);
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
  const baseline = await browser.newPage({viewport: {width: 1440, height: 1000}});
  await baseline.goto(process.env.MICEBALL_DEMO_ORIGIN);
  const demo = await browser.newPage({viewport: {width: 1440, height: 1000}});
  await demo.goto(process.env.MICEBALL_DEMO_CURRENT_ORIGIN);
  for (const target of [baseline, demo]) {
    await section(target, 'services');
    await target.locator('[data-expand-service]').first().click();
  }
  assert.equal(await demo.locator('#panel-services').innerText(), await baseline.locator('#panel-services').innerText());
  const demoBefore = await baseline.locator('#panel-services').screenshot();
  assert.deepEqual(await demo.locator('#panel-services').screenshot(), demoBefore);
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
  await baseline.close(); await demo.close();
  assert.deepEqual(errors, []);
  await writeFile(`${directory}/feedback.json`, JSON.stringify({result: 'PASS', transport: 'controlled WebSocket replies; real GUI/backend shell', inventoryRequests: inventoryRequests.length, screenshots}, null, 2));
  console.log('PASS: Services unavailable controls/details, independent expansion, unchanged demo pixels/interactions; inventory pending, duplicate guard, success, failure, pending reply, disconnect, reconnect, stale owner refusal and explicit recovery');
} catch (error) {
  await shot('feedback-failure'); console.error(errors); throw error;
} finally {await browser.close();}
}
