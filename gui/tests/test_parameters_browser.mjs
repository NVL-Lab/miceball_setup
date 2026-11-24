import {returnFromParameters} from './parameter_navigation.mjs';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), errors = [];
page.on('pageerror', error => errors.push(error.message));
const origin = process.env.MICEBALL_PARAMETERS_ORIGIN, inventory = JSON.parse(process.env.MICEBALL_PARAMETERS_INVENTORY);
const snapshot = {controller_id: 'controller', instance_id: 'controller', browser_control_required: true, control: {controlling: true, generation: 1}, configured_nodes: ['node'], configured_services: [], pending_operations: [], configuration: null, status: {session_id: null}, experiments: []};
await page.routeWebSocket('**/ws', socket => {
  socket.onMessage(raw => {
    const message = JSON.parse(raw);
    if (message.operation === 'view_only') snapshot.control.controlling = false;
    if (message.operation === 'take_browser_control') snapshot.control.controlling = true;
    socket.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'controller', result: {status: 'succeeded', outcome: {details: message.operation === 'get_node_inventory' ? inventory : snapshot}}}));
  });
  socket.send(JSON.stringify({type: 'connected', browser_id: 'parameters'}));
});
const section = name => page.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
try {
  await page.goto(origin);
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  const order = await page.locator('.section-nav > .nav-item:not(.editor-tab)').evaluateAll(items => items.map(item => item.dataset.section));
  assert.deepEqual(order, ['setup', 'session', 'experiment', 'analysis', 'storage', 'parameters', 'services']);
  assert.equal(await page.locator('[data-section="parameters"]').getAttribute('hidden'), null);
  await page.locator('#load-inventory').click();
  await page.locator('#session-device-list input').check();
  await page.locator('[data-setup-parameters]').click();
  assert.equal(await page.locator('#panel-setup #device-validation-maximum').count(), 0);
  assert.equal(await page.locator('#device-validation-maximum').inputValue(), '5');
  assert.equal(await page.locator('#panel-parameters .view-heading [data-return-session]').count(), 0);
  assert.equal(await page.locator('#panel-parameters .prototype-caption').innerText(), 'Experiment parameters');
  assert.equal((await page.locator('#panel-parameters').innerText()).includes('Unsent working values;'), false);
  for (const value of ['', '0', '-1']) {
    await page.locator('#device-validation-maximum').fill(value);
    assert.equal(await page.locator('#device-validation-maximum').evaluate(input => input.checkValidity()), false);
  }
  await page.locator('#device-validation-maximum').fill('7.5');
  await page.locator('#device-validation-maximum').press('ArrowUp');
  assert.equal(await page.locator('#device-validation-maximum').inputValue(), '8.5');
  await section('session'); await section('parameters');
  assert.equal(await page.locator('#device-validation-maximum').inputValue(), '8.5');
  await page.locator('[data-parameter-participant]').check();
  await page.locator('#experiment-duration').fill('17');
  const rate = page.getByLabel('rate', {exact: true});
  await rate.fill('0'); assert.equal(await rate.evaluate(input => input.checkValidity()), false);
  await rate.fill('3'); assert.equal(await rate.evaluate(input => input.checkValidity()), true);
  await rate.fill('3.1'); assert.equal(await rate.evaluate(input => input.checkValidity()), false);
  await rate.blur();
  assert.match(await page.locator('#activity-history').textContent(), /Parameter validation.*rate/);
  await rate.fill('.5');
  await page.getByLabel('count', {exact: true}).selectOption('0');
  assert.equal(await page.getByLabel('advanced_text', {exact: true}).isVisible(), true);
  await page.getByLabel('advanced_text', {exact: true}).fill('  "quoted" \\ Ω\nline');
  await returnFromParameters(page);
  await page.locator('[data-setup-parameters]').click();
  assert.equal(await page.locator('#experiment-duration').inputValue(), '17');
  assert.equal(await rate.inputValue(), '0.5');
  await returnFromParameters(page);
  // Existing dialogs create real durable identities needed for protocol ownership.
  await page.selectOption('#experimenter-select', '__new_experimenter');
  await page.locator('#catalog-fields [name="name"]').fill('Scientist');
  await page.locator('#catalog-save').click(); await page.locator('#catalog-dialog').waitFor({state: 'hidden'});
  const actor = await page.locator('#experimenter-select').inputValue();
  await page.selectOption('#project-select', '__new_project');
  await page.locator('#catalog-fields [name="project_name"]').fill('Study');
  await page.locator('#catalog-fields [name="primary_experimenter"]').selectOption(actor);
  await page.locator('#catalog-save').click(); await page.locator('#catalog-dialog').waitFor({state: 'hidden'});
  await page.locator('#new-protocol').click(); await page.locator('#add-step').click();
  await page.locator('#step-form [name="name"]').fill('Acquisition');
  await page.locator('[data-step-parameters]').click();
  await page.locator('[data-parameter-participant]').check();
  await page.locator('#experiment-duration').fill('23');
  await page.getByLabel('count', {exact: true}).selectOption('0');
  await rate.fill('.5');
  const text = '  "quoted" \\ Ω\nline'; await page.getByLabel('advanced_text', {exact: true}).fill(text);
  await page.locator('#personal-experiment-template button[type="submit"]').click();
  assert.match(await page.locator('#activity-history').textContent(), /Catalog save.*Personal template name/);
  await returnFromParameters(page);
  await page.locator('#save-reusable-step').click();
  await page.locator('#step-definition-status').filter({hasText: 'read-only'}).waitFor();
  await section('parameters');
  assert.equal(await page.locator('#experiment-duration').isDisabled(), true);
  assert.equal(await page.locator('#panel-parameters .prototype-caption').innerText(), 'Saved template');
  assert.equal(await page.locator('#device-validation-maximum').isEnabled(), true);
  assert.equal(await page.locator('#experiment-duration').inputValue(), '23');
  await returnFromParameters(page); await page.locator('#copy-step').click();
  await section('parameters');
  assert.equal(await page.locator('#experiment-duration').isEnabled(), true);
  await page.locator('#experiment-duration').fill('99');
  await returnFromParameters(page); await page.locator('#save-protocol').click();
  await page.locator('#panel-setup').waitFor({state: 'visible'});
  const catalog = (await (await page.request.get(`${origin}/api/catalog`)).json()).catalog;
  assert.equal(catalog.definitions[0].parameters.durationSeconds, 23);
  assert.equal(catalog.protocols[0].steps[0].parameters.durationSeconds, 99);
  assert.equal(catalog.definitions[0].parameters.values[JSON.stringify(['node', 'camera', 'count'])], 0);
  assert.equal(catalog.definitions[0].parameters.values[JSON.stringify(['node', 'camera', 'advanced_text'])], text);
  const current = await (await page.request.get(`${origin}/api/catalog`)).json();
  const loaded = current.catalog.protocols[0];
  loaded.steps[0].parameters.values[JSON.stringify(['node', 'camera', 'count'])] = 1;
  const stored = await page.request.post(`${origin}/api/catalog`, {headers: {Origin: origin}, data: {
    collection: 'protocols', record: loaded, actor, expected_revision: current.revision}});
  assert.equal(stored.status(), 200);
  await page.reload(); await page.locator('html[data-control-mode="controlling"]').waitFor();
  await page.locator('#project-select option').filter({hasText: 'Study'}).waitFor({state: 'attached'});
  await page.selectOption('#project-select', catalog.projects[0].id);
  await page.selectOption('#protocol-select', loaded.id);
  await page.locator('#load-inventory').click(); await page.locator('#session-device-list input').check();
  await page.locator('[data-setup-parameters]').click();
  const choice = page.getByLabel('count', {exact: true});
  assert.equal(await choice.inputValue(), '__current__', 'A loaded undeclared value must not become a fabricated default');
  assert.equal(await choice.evaluate(input => input.checkValidity()), false);
  await choice.selectOption('0');
  const duration = page.locator('#experiment-duration');
  const originalDuration = await duration.inputValue();
  await duration.fill('123456789012.125');
  assert.equal(await duration.inputValue(), '123456789012.125');
  assert.equal(await duration.evaluate(input => input.checkValidity()), true);
  await duration.fill(originalDuration);
  for (const theme of ['light', 'dark']) for (const width of [1440, 800, 390]) {
    await page.setViewportSize({width, height: 900});
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    await section('parameters');
    assert.equal(await page.locator('#panel-parameters').isVisible(), true);
    // The existing shell has a 720px minimum; this batch does not redesign it.
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= Math.max(innerWidth, 720) + 1), true,
      JSON.stringify(await page.evaluate(() => [...document.querySelectorAll('#panel-parameters *')].filter(element => element.getBoundingClientRect().right > innerWidth + 1).map(element => [element.tagName, element.id, element.className, element.getBoundingClientRect().width]).slice(0, 12))));
    const dimensions = await page.locator('#experiment-duration').evaluate(input => ({width: input.getBoundingClientRect().width, parent: input.parentElement.getBoundingClientRect().width}));
    assert.ok(dimensions.width <= dimensions.parent + 1);
    assert.ok(dimensions.width < 220, 'Ordinary numeric input is compact');
    if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/unified-parameters-${theme}-${width}.png`, fullPage: true});
    if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) {
      await page.locator('#device-validation-maximum').scrollIntoViewIfNeeded();
      await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/validation-maximum-${theme}-${width}.png`});
    }
  }
  await page.locator('#view-only').click();
  await page.locator('html[data-control-mode="view-only"]').waitFor();
  assert.equal(await page.locator('#device-validation-maximum').isDisabled(), true);
  await page.locator('#take-over').click();
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  assert.equal(await page.locator('#device-validation-maximum').isEnabled(), true);
  assert.equal(await page.locator('#device-validation-maximum').inputValue(), '5', 'The earlier full GUI reload resets the nonpersistent setting');
  await page.reload(); await page.locator('html[data-control-mode="controlling"]').waitFor();
  await section('parameters');
  assert.equal(await page.locator('#device-validation-maximum').inputValue(), '5');
  assert.deepEqual(errors, []);
  console.log('PASS: permanent navigation, Setup/Step contexts, typed bounds/choices, advanced parameters, durable immutable Step/copy, return navigation, both themes and widths; controlled inventory, real catalog HTTP.');
} catch (error) { console.error(errors); console.error(await page.locator('body').innerText()); throw error; }
finally {await browser.close();}
