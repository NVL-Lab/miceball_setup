import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || 'msedge'});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const errors = [], commands = [];
let configuration = null;
page.on('pageerror', error => errors.push(error.message));
await page.routeWebSocket('**/ws', socket => {
  socket.onMessage(raw => {
    const message = JSON.parse(raw); commands.push(message.operation);
    if (replyArtifactDestinations(socket, message)) return;
    assert.equal(message.operation, 'read_controller_state');
    socket.send(JSON.stringify({type: 'result', id: message.id, result: {status: 'succeeded', outcome: {details: {
      controller_id: 'controller', instance_id: 'controller', control: {controlling: false, generation: 1},
      configured_services: [], configured_nodes: [], pending_operations: [], experiments: [],
      configuration, status: {session_id: configuration?.session_id || null, session_state: configuration ? 'running' : null}}}}}));
  });
  socket.send(JSON.stringify({type: 'connected', browser_id: 'settings-browser'}));
});
const origin = process.env.MICEBALL_SETTINGS_ORIGIN;
const snapshot = async () => (await page.request.get(`${origin}/api/catalog`)).json();
const section = name => page.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
async function enter() {
  await section('parameters');
  await page.locator('[data-mode="administrator"]').click();
  await page.locator('[data-administrator-entry]').fill('Settings operator');
  await page.locator('[data-danger-enter]').click();
}
try {
  await page.goto(origin);
  await section('parameters');
  assert.equal(await page.locator('[data-synchronization-form]').count(), 0);
  await enter();
  const form = page.locator('[data-synchronization-form]');
  await page.waitForFunction(() => document.querySelector('[data-synchronization-form] [name="exchanges"]').value !== '');
  const initial = await snapshot();
  assert.equal(await form.locator('input').count(), 7);
  assert.equal(await form.locator('select').count(), 1);
  assert.equal(await form.locator('button').count(), 1);
  await form.locator('[name="exchanges"]').fill('5');
  await page.request.post(`${origin}/api/catalog`, {headers: {Origin: origin}, data: {collection: 'experimenters',
    record: {id: 'alice', name: 'Alice'}, actor: 'alice', expected_revision: initial.revision}});
  await page.evaluate(() => document.dispatchEvent(new Event('gui-control-acquired')));
  await page.waitForFunction(() => document.querySelector('#experimenter-select option[value="alice"]'));
  await section('services'); await section('parameters');
  assert.equal(await form.locator('[name="exchanges"]').inputValue(), '5');
  await form.locator('button').click();
  await form.locator('[role="status"]').filter({hasText: 'draft is retained'}).waitFor();
  assert.equal((await snapshot()).synchronization_configuration.exchanges, initial.synchronization_configuration.exchanges);
  assert.equal(await form.locator('[name="exchanges"]').inputValue(), '5');
  await page.reload(); await enter();
  await page.waitForFunction(() => document.querySelector('[data-synchronization-form] [name="exchanges"]').value !== '');
  await form.locator('[name="exchanges"]').fill('5');
  await form.locator('button').click();
  await form.locator('[role="status"]').filter({hasText: 'Saved for subsequent Sessions'}).waitFor();
  assert.equal((await snapshot()).synchronization_configuration.exchanges, 5);
  configuration = {session_id: 'fixed', selected_devices: [], protocol_reference: null,
    session_parameters: {name: 'Accepted Session'}, synchronization_configuration: (await snapshot()).synchronization_configuration};
  const accepted = structuredClone(configuration);
  await page.waitForFunction(() => document.querySelector('.setup-demo-note').textContent.includes('Accepted Session'));
  let releaseReply;
  await page.route('**/api/catalog', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    await new Promise(resolve => { releaseReply = resolve; });
    await route.fulfill({response});
  });
  await form.locator('[name="exchanges"]').fill('6');
  await form.locator('button').click();
  for (let i = 0; i < 100 && !releaseReply; i++) await page.waitForTimeout(20);
  assert.ok(releaseReply);
  await form.locator('[name="exchanges"]').fill('7');
  releaseReply();
  await form.locator('[role="status"]').filter({hasText: 'newer edits remain unsaved'}).waitFor();
  assert.equal(await form.locator('[name="exchanges"]').inputValue(), '7');
  assert.equal((await snapshot()).synchronization_configuration.exchanges, 6);
  await page.unroute('**/api/catalog');
  assert.deepEqual(JSON.parse(await page.locator('#accepted-configuration').textContent()), accepted);
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    for (const width of [1440, 800]) {
      await page.setViewportSize({width, height: 900});
      await form.locator('button').scrollIntoViewIfNeeded();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/synchronization-${theme}-${width}.png`});
    }
  }
  await section('services');
  await page.locator('#activity-history summary').click();
  assert.match(await page.locator('#activity-history').innerText(), /Synchronization defaults saved/);
  assert.ok(commands.every(operation => ['read_controller_state', 'list_artifact_destinations'].includes(operation)));
  assert.deepEqual(errors, []);
  console.log('PASS: administrator-only settings without scientific selection, revision conflict/draft retention, saved defaults, fixed Session isolation, no reconfiguration commands, Activity History and themed responsive rendering.');
} finally { await browser.close(); }
