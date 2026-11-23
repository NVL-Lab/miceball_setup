import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || 'msedge'});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), errors = [];
const origin = process.env.MICEBALL_CORRECTIONS_ORIGIN;
page.on('pageerror', error => errors.push(error.message));
let online = false, controlling = false, reads = 0, failCatalog = true;
const snapshot = () => ({controller_id: 'controller', instance_id: 'controller', control: {controlling, generation: 1},
  configured_services: [{component_type: 'controller', component_id: 'controller'}], configured_nodes: [],
  status: {session_id: null}, configuration: null, pending_operations: [], experiments: []});
await page.route('**/api/catalog', async route => {
  if (route.request().method() === 'GET') {
    reads++;
    if (failCatalog) return route.fulfill({status: 503, json: {error: 'Catalog disk unavailable; retained catalog unchanged'}});
  }
  await route.continue();
});
await page.routeWebSocket('**/ws', socket => {
  socket.onMessage(raw => {
    const message = JSON.parse(raw);
    if (replyArtifactDestinations(socket, message)) return;
    if (message.operation === 'take_browser_control') controlling = true;
    let details = snapshot();
    if (message.operation === 'read_service_status') details = {current: false, reason: 'No live readiness report', details: {}};
    socket.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'controller', result: {
      status: online ? 'succeeded' : 'failed', error: online ? '' : 'Controller connection unavailable', outcome: {details}}}));
  });
  socket.send(JSON.stringify({type: 'connected', browser_id: 'corrections'}));
});
const section = name => page.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
try {
  await page.goto(origin);
  await page.locator('#activity-history').filter({hasText: 'Catalog disk unavailable'}).waitFor({state: 'attached'});
  await page.locator('#activity-history').filter({hasText: 'Controller connection is unconfirmed'}).waitFor({state: 'attached'});
  await section('services');
  assert.match(await page.locator('.services-card').first().textContent(), /Configured services.*unavailable/);
  assert.equal(await page.locator('[data-gui-backend]').evaluate(element => element.previousElementSibling.querySelector('.services-list') !== null), true);
  await page.waitForTimeout(4500); // Observe multiple existing two-second poll cycles.
  assert.equal(await page.locator('[data-activity-records] li').filter({hasText: 'Controller connection is unconfirmed'}).count(), 1);
  failCatalog = false; online = true;
  await page.locator('html[data-control-mode="view-only"]').waitFor();
  await section('setup');
  await page.locator('[role="status"]').filter({hasText: /^Catalogs loaded\.$/}).waitFor();
  // Public catalog HTTP establishes the same identities as the creation forms.
  let revision = (await (await page.request.get(`${origin}/api/catalog`)).json()).revision;
  const put = async (collection, record) => {
    const response = await page.request.post(`${origin}/api/catalog`, {headers: {Origin: origin}, data: {collection, record, actor: 'alice', expected_revision: revision}});
    assert.equal(response.status(), 200); revision = (await response.json()).revision;
  };
  await put('experimenters', {id: 'alice', name: 'Alice'});
  await put('projects', {id: 'project', name: 'Study', primary_experimenter: 'alice'});
  await section('services'); await section('setup');
  await page.locator('#project-select option[value="project"]').waitFor({state: 'attached'});
  assert.equal(await page.locator('#experimenter-select').isDisabled(), true);
  await page.locator('#take-over').click();
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  await page.selectOption('#experimenter-select', 'alice'); await page.selectOption('#project-select', 'project');
  await page.locator('#new-protocol').click();
  await page.locator('#protocol-name').fill(''); await page.locator('#save-protocol').click();
  assert.match(await page.locator('#activity-history').textContent(), /Provide a protocol name/);
  await page.locator('#protocol-name').fill('Unsaved draft');
  controlling = false;
  await page.locator('html[data-control-mode="view-only"]').waitFor();
  assert.equal(await page.locator('#protocol-name').isDisabled(), true);
  await put('experimenters', {id: 'bob', name: 'Bob'});
  const before = reads;
  await page.locator('#take-over').click();
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  await page.locator('#experimenter-select option[value="bob"]').waitFor({state: 'attached'});
  assert.ok(reads > before, 'Control acquisition reads the catalog');
  assert.equal(await page.locator('#protocol-name').inputValue(), 'Unsaved draft');
  await page.locator('#save-protocol').click();
  await page.locator('#editor-message').filter({hasText: 'another browser'}).waitFor();
  assert.equal(await page.getByRole('button', {name: 'Reload catalogs', exact: true}).count(), 0);
  online = false;
  await page.locator('html[data-control-mode="unconfirmed"]').waitFor();
  await section('services');
  assert.match(await page.locator('.services-card').first().textContent(), /Configured services \(1\)/);
  assert.match(await page.locator('.services-list').textContent(), /Controller/);
  for (const theme of ['light', 'dark']) for (const width of [1440, 760]) {
    await page.setViewportSize({width, height: 850});
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    for (const name of ['experiment', 'storage', 'parameters']) {
      await section(name);
      assert.equal(await page.locator('h1:visible').count(), 1);
      assert.equal(await page.locator('.section-panel.is-active h2:not(.visually-hidden):visible').count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
  }
  assert.deepEqual(errors, []);
  console.log('PASS: initial/recovered connection history without polling flood, unknown/retained membership, backend order, automatic catalog refresh with stale draft retained, single titles and themes/layouts.');
} catch (error) { console.error(errors); throw error; }
finally { await browser.close(); }
