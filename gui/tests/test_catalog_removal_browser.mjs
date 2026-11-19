import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const context = await browser.newContext({viewport: {width: 1440, height: 900}});
const page = await context.newPage();
page.setDefaultTimeout(10000);
const origin = process.env.MICEBALL_CATALOG_ORIGIN;
const errors = [], commands = [];
page.on('pageerror', error => errors.push(error.message));
let accepted = null;
await page.routeWebSocket('**/ws', route => {
  route.onMessage(raw => {
    const message = JSON.parse(raw); commands.push(message.operation);
    if (replyArtifactDestinations(route, message)) return;
    if (message.operation === 'read_controller_state') route.send(JSON.stringify({type: 'result', id: message.id,
      result: {status: 'succeeded', outcome: {details: {controller_id: 'test-controller', instance_id: 'test-instance',
        control: {controlling: false}, configured_services: [], configured_nodes: [], pending_operations: [],
        configuration: accepted, status: {session_id: accepted?.session_id || null, session_state: accepted ? 'running' : null}, experiments: []}}}}));
  });
  route.send(JSON.stringify({type: 'connected', browser_id: 'test-browser'}));
});
const snapshot = async () => (await context.request.get(`${origin}/api/catalog`)).json();
async function put(collection, record, actor = 'alice') {
  const current = await snapshot();
  const response = await context.request.post(`${origin}/api/catalog`, {headers: {Origin: origin},
    data: {collection, record, actor, expected_revision: current.revision}});
  assert.equal(response.status(), 200, await response.text());
}
async function refresh() {
  await page.evaluate(() => document.dispatchEvent(new Event('gui-control-acquired')));
  await page.waitForFunction(() => !document.querySelector('[data-catalog-remove]').disabled ||
    document.querySelector('.identity-card [role="status"]').textContent === 'Catalogs loaded.');
}
try {
  await put('experimenters', {id: 'alice', name: 'Alice'});
  await put('projects', {id: 'p', name: 'Study', primary_experimenter: 'alice'});
  const protocol = {id: 'protocol', projectId: 'p', owner: 'alice', name: 'Procedure', protected: false, description: '', steps: []};
  await put('protocols', protocol);
  const definition = {id: 'saved', name: 'Acquire', owner: 'alice', operation: 'acquisition', description: '', mandatory: true, required: [], optional: [], configuration: ''};
  await put('definitions', definition);
  await page.goto(origin);
  await page.locator('#experimenter-select option[value="alice"]').waitFor({state: 'attached'});
  await page.selectOption('#experimenter-select', 'alice');
  await page.selectOption('#project-select', 'p');
  await page.selectOption('#protocol-select', 'protocol');
  assert.equal(await page.locator('[data-catalog-category]').isVisible(), false);
  await page.locator('#remove-protocol').click();
  await page.locator('[data-remove-cancel]').click();
  assert.equal((await snapshot()).catalog.protocols.length, 1);
  await page.locator('#remove-protocol').click();
  await page.locator('[data-remove-confirm]').waitFor({state: 'visible'});
  await page.keyboard.press('Escape');
  assert.equal((await snapshot()).catalog.protocols.length, 1);
  await page.locator('#remove-protocol').click();
  await page.locator('[data-remove-confirm]').click();
  await page.locator('#remove-protocol').waitFor({state: 'hidden'});
  assert.equal((await snapshot()).catalog.protocols.length, 0);
  await put('protocols', {...protocol, id: 'replacement'});
  await refresh();
  await page.locator('#protocol-select option[value="replacement"]').waitFor({state: 'attached'});
  await page.selectOption('#protocol-select', 'replacement');
  await page.locator('#edit-protocol').click();
  await page.selectOption('#add-operation', 'saved');
  await page.locator('#remove-saved-step').click();
  await page.locator('[data-remove-confirm]').click();
  await page.locator('[data-remove-confirm]').waitFor({state: 'hidden'});
  assert.equal((await snapshot()).catalog.definitions.length, 0);
  await page.locator('#cancel-protocol').click();
  await put('definitions', definition);
  await put('templates', {id: 'daily', projectId: 'p', protocol: 'replacement', owner: 'alice', name: 'Daily', included: [], devices: []});
  await refresh();
  await page.locator('#session-template option[value="daily"]').waitFor({state: 'attached'});
  await page.selectOption('#session-template', 'daily');
  await page.locator('#remove-session-template').click();
  await page.locator('[data-remove-confirm]').click();
  await page.locator('[data-remove-confirm]').waitFor({state: 'hidden'});
  assert.equal((await snapshot()).catalog.templates.length, 0);
  await put('experimentTemplates', {id: 'personal-experiment', name: 'Daily acquisition', owner: 'alice', operation: 'acquisition', configuration: {durationSeconds: 12, participants: [], values: {}}});
  await refresh();
  await page.selectOption('#protocol-select', '');
  await page.locator('[data-setup-parameters]').click();
  await page.locator('[name="templateName"]').fill('Daily acquisition');
  await page.locator('[data-remove-experiment-template]').click();
  await page.locator('[data-remove-confirm]').click();
  await page.locator('[data-remove-confirm]').waitFor({state: 'hidden'});
  assert.equal((await snapshot()).catalog.experimentTemplates.length, 0);
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'setup'})));

  await page.locator('[data-mode="administrator"]').click();
  await page.locator('[data-administrator-entry]').fill('Catalog operator');
  await page.locator('[data-danger-enter]').click();
  const disclosure = page.locator('.setup-card').filter({has: page.locator('[data-catalog-category]')}).locator('details');
  assert.equal(await disclosure.evaluate(element => element.open), false);
  await disclosure.locator('summary').click();
  await page.selectOption('[data-catalog-category]', 'projects');
  await page.selectOption('[data-catalog-entry]', 'p');
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    for (const width of [1440, 800]) {
      await page.setViewportSize({width, height: 800});
      assert.equal(await page.locator('[data-catalog-remove]').isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.locator('[data-catalog-remove]').scrollIntoViewIfNeeded();
      const bounds = await page.locator('[data-catalog-remove]').boundingBox();
      assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 800);
      if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/catalog-removal-${theme}-${width}.png`});
    }
  }
  accepted = {session_id: 'accepted', protocol_reference: 'Procedure', selected_devices: [],
    session_parameters: {experimenter: 'Historical Alice', catalog_experimenter_id: 'alice', project: 'Historical Study', catalog_project_id: 'p', animal: 'Historical animal'}};
  await page.waitForFunction(() => document.querySelector('.setup-demo-note').textContent.includes('Accepted Session'));
  await page.locator('[data-catalog-remove]').click();
  await page.locator('[data-remove-confirm]').waitFor({state: 'visible'});
  assert.ok((await page.locator('[data-remove-target]').textContent()).includes('Procedure'));
  await page.locator('[data-remove-confirm]').click();
  await page.locator('[data-remove-confirm]').waitFor({state: 'hidden'});
  const after = await snapshot();
  assert.equal(after.catalog.projects.length, 0);
  assert.equal(after.catalog.protocols.length, 0);
  assert.equal(after.catalog.definitions.length, 1);
  assert.equal(await page.locator('#experimenter-select option:checked').textContent(), 'Historical Alice');
  assert.equal(await page.locator('#project-select option:checked').textContent(), 'Historical Study');
  assert.deepEqual(JSON.parse(await page.locator('#accepted-configuration').textContent()), accepted);
  assert.ok(commands.every(operation => ['read_controller_state', 'list_artifact_destinations'].includes(operation)), commands.join(', '));
  await page.locator('[data-mode="experimenter"]').click();
  assert.equal(await page.locator('[data-catalog-category]').isVisible(), false);
  assert.deepEqual(errors, []);
  console.log('PASS: personal removal/cancellation, name reuse, Administrator-only collapsed management, atomic project removal, retained definitions and accepted historical identities, light/dark and narrow rendering; catalog operations send no framework commands.');
} catch (error) { console.error('Browser errors:', errors); throw error; }
finally { await browser.close(); }
