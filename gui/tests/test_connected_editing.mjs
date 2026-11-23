import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), errors = [], calls = [];
page.on('pageerror', error => errors.push(error.message));
const origin = process.env.MICEBALL_CORRECTIONS_ORIGIN;
const snapshot = {controller_id: 'controller', instance_id: 'controller', browser_control_required: true,
  control: {controlling: true, generation: 1}, configured_nodes: ['node-a', 'node-b'], configured_services: [],
  pending_operations: [], configuration: null, status: {session_id: null}, experiments: []};
const inventories = Object.fromEntries(['node-a', 'node-b'].map(node => [node, {
  devices: ['sensor', 'aux'].map(device_id => ({device_id, enabled: true, declared_capabilities: [], scientific_products: []})),
  session_parameter_definitions: {sensor: {batch: {type: 'integer', minimum: 1, adjustment_scope: 'administrator'}},
    aux: {label: {type: 'string', nullable: true, adjustment_scope: 'administrator'}, enabled: {type: 'boolean', adjustment_scope: 'administrator'}}},
  administrative_configuration: {available: true, blockers: [], revision: 'revision-1',
    loaded: {sensor: {batch: 1}, aux: {label: 'old', enabled: true}},
    saved: {sensor: {batch: 2}, aux: {label: 'new', enabled: false}}}
}]));
await page.routeWebSocket('**/ws', socket => {
  socket.onMessage(raw => {
    const message = JSON.parse(raw); calls.push(message);
    if (message.operation === 'view_only') snapshot.control.controlling = false;
    if (message.operation === 'take_browser_control') snapshot.control.controlling = true;
    socket.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'controller', result: {
      status: 'succeeded', outcome: {details: message.operation === 'get_node_inventory' ? inventories[message.parameters.node_id] : snapshot}}}));
  });
  socket.send(JSON.stringify({type: 'connected', browser_id: 'corrections'}));
});
const section = name => page.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
const mode = name => page.locator(`html[data-control-mode="${name}"]`).waitFor();
try {
  await page.goto(origin); await mode('controlling');
  const name = page.locator('.session-identity-grid textarea').first();
  assert.equal(await name.locator('xpath=following-sibling::button[1]').isVisible(), false);
  const ordinary = '  "Session" \\ Ω  ';
  await name.fill(ordinary);
  assert.equal(await name.inputValue(), ordinary);
  const exceptional = 'A\r\nB\u0001\ud800';
  await name.evaluate((control, value) => control.dispatchEvent(new InputEvent('beforeinput', {bubbles: true,
    cancelable: true, inputType: 'insertText', data: value})), exceptional);
  assert.equal(await name.getAttribute('data-string-encoding'), 'exact');
  const exact = await name.inputValue();
  assert.equal(JSON.parse(exact), ordinary + exceptional);
  assert.ok(exact.includes('\\r\\n'));
  assert.equal(await name.locator('xpath=following-sibling::small[1]').isVisible(), true);
  await page.selectOption('#experimenter-select', '__new_experimenter');
  await page.locator('#catalog-fields input').first().fill('Retained draft');
  snapshot.control.controlling = false; await mode('view-only');
  assert.equal(await page.locator('#catalog-fields input').first().isDisabled(), true);
  assert.equal(await page.locator('#catalog-save').isDisabled(), true);
  await page.keyboard.press('Escape');
  await page.locator('#catalog-dialog').waitFor({state: 'hidden'});
  for (const selector of ['#experimenter-select', '#project-select', '#animal-select', '.session-identity-grid textarea',
    '#protocol-select', '#session-template', '#new-protocol']) {
    assert.equal(await page.locator(selector).first().isDisabled(), true, selector);
  }
  await name.evaluate(control => control.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, cancelable: true, data: 'bad'})));
  assert.equal(await name.inputValue(), exact);
  await page.locator('#take-over').click(); await mode('controlling');
  assert.equal(await name.isEnabled(), true);
  assert.equal(await name.inputValue(), exact);
  // Repeated refresh must not turn ownership restrictions into permanent disabled state.
  await page.locator('#view-only').click(); await mode('view-only');
  await page.waitForTimeout(2200);
  await page.locator('#take-over').click(); await mode('controlling');
  assert.equal(await page.locator('#experimenter-select').isEnabled(), true);
  for (const node of ['node-a', 'node-b']) {
    await page.selectOption('#inventory-node', node); await page.locator('#load-inventory').click();
  }
  await section('parameters');
  await page.locator('[data-mode="administrator"]').click();
  await page.locator('[data-administrator-entry]').fill('Operator');
  await page.locator('[data-danger-enter]').click();
  const groups = page.locator('[data-administrative-device]');
  await groups.first().waitFor(); assert.equal(await groups.count(), 4);
  assert.equal(await page.getByRole('heading', {name: 'Device Parameters', exact: true}).count(), 1);
  const group = groups.filter({has: page.getByRole('heading', {name: 'node-a / sensor', exact: true})});
  const batch = group.getByLabel('batch', {exact: true});
  assert.equal(await groups.filter({has: page.getByRole('heading', {name: 'node-a / aux', exact: true})})
    .getByLabel('label', {exact: true}).inputValue(), 'new');
  const nullable = groups.filter({has: page.getByRole('heading', {name: 'node-a / aux', exact: true})})
    .locator('[data-administrative-null]');
  assert.equal(await nullable.isChecked(), false);
  await nullable.check();
  assert.equal(await batch.inputValue(), '2');
  assert.match(await group.textContent(), /Normal AcquisitionNode restart required/);
  await batch.fill('0'); assert.equal(await batch.evaluate(input => input.checkValidity()), false);
  await batch.fill('7');
  inventories['node-a'].session_parameter_definitions.sensor.batch.maximum = 10;
  await section('setup'); await page.selectOption('#inventory-node', 'node-a'); await page.locator('#load-inventory').click();
  await section('parameters');
  assert.equal(await batch.inputValue(), '7'); assert.equal(await batch.isEnabled(), true);
  inventories['node-a'].session_parameter_definitions.sensor.batch.maximum = 5;
  await section('setup'); await page.selectOption('#inventory-node', 'node-a'); await page.locator('#load-inventory').click();
  await section('parameters');
  assert.equal(await batch.inputValue(), '7');
  assert.equal(await batch.isDisabled(), true);
  assert.match(await group.textContent(), /definitions changed/);
  await group.locator('[data-administrative-reload]').click();
  assert.equal(await batch.inputValue(), '2');
  await batch.fill('7'); assert.equal(await batch.evaluate(input => input.checkValidity()), false);
  await batch.fill('4');
  await page.locator('#view-only').click(); await mode('view-only');
  assert.equal(await batch.isDisabled(), true);
  assert.equal(await group.locator('[type="submit"]').isDisabled(), true);
  assert.equal(await page.locator('[data-synchronization-form] input').first().isDisabled(), true);
  for (const tab of ['setup', 'session', 'experiment', 'analysis', 'services', 'storage']) {
    await section(tab);
    if (tab === 'storage') {
      const search = page.locator('[data-history-query]');
      await page.locator('[data-storage-workspace="history"]').click();
      await search.fill('Session'); assert.equal(await search.inputValue(), 'Session');
    }
    if (tab === 'setup') {
      assert.equal(await page.locator('#new-protocol').isDisabled(), true);
      for (const input of await page.locator('#session-device-list input').all()) assert.equal(await input.isDisabled(), true);
    }
  }
  await section('parameters');
  await page.locator('#take-over').click(); await mode('controlling');
  assert.equal(await batch.inputValue(), '4'); assert.equal(await batch.isEnabled(), true);
  inventories['node-a'].devices[0].enabled = false;
  await section('setup'); await page.selectOption('#inventory-node', 'node-a'); await page.locator('#load-inventory').click();
  await section('parameters');
  assert.equal(await batch.inputValue(), '4'); assert.equal(await batch.isDisabled(), true);
  inventories['node-a'].devices[0].enabled = true;
  await section('setup'); await page.locator('#load-inventory').click(); await section('parameters');
  assert.equal(await batch.inputValue(), '4'); assert.equal(await batch.isEnabled(), true);
  for (const theme of ['light', 'dark']) for (const width of [1440, 800]) {
    await page.setViewportSize({width, height: 900});
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    for (const tab of ['setup', 'session', 'experiment', 'analysis', 'parameters', 'services', 'storage']) {
      await section(tab);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `${theme}/${width}/${tab}`);
      await page.waitForFunction(() => [...document.querySelectorAll('.section-panel.is-active h3')]
        .every(heading => getComputedStyle(heading).fontSize === '14px'));
      assert.equal(await page.locator('.section-panel.is-active h3').evaluateAll(headings =>
        headings.every(heading => getComputedStyle(heading).fontSize === '14px')), true,
        JSON.stringify(await page.locator('.section-panel.is-active h3').evaluateAll(headings =>
          headings.map(heading => [heading.textContent, getComputedStyle(heading).fontSize]))));
      assert.equal(await page.locator('.section-panel.is-active summary').evaluateAll(summaries =>
        summaries.every(summary => summary.parentElement.tagName === 'DETAILS' && getComputedStyle(summary).cursor === 'pointer')), true);
      if (tab === 'setup') assert.equal(await page.locator('.device-card h4').first().evaluate(heading =>
        parseFloat(getComputedStyle(heading).borderTopWidth)), 0);
    }
    await section('parameters');
    if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/gui-corrections-${theme}-${width}.png`, fullPage: true});
  }
  assert.equal(calls.some(message => message.operation === 'update_device_configuration'), false);
  await section('setup');
  await name.fill('"ordinary again Ω"'); await name.blur();
  assert.equal(await name.getAttribute('data-string-encoding'), 'text');
  assert.equal(await name.inputValue(), 'ordinary again Ω');
  // Losing ownership during an already-started pointer drag cannot commit it.
  await page.selectOption('#experimenter-select', '__new_experimenter');
  await page.locator('#catalog-fields [name="name"]').fill('Drag scientist');
  await page.locator('#catalog-save').click(); await page.locator('#catalog-dialog').waitFor({state: 'hidden'});
  const actor = await page.locator('#experimenter-select').inputValue();
  await page.selectOption('#project-select', '__new_project');
  await page.locator('#catalog-fields [name="project_name"]').fill('Drag project');
  await page.locator('#catalog-fields [name="primary_experimenter"]').selectOption(actor);
  await page.locator('#catalog-save').click(); await page.locator('#catalog-dialog').waitFor({state: 'hidden'});
  await page.locator('#new-protocol').click();
  await page.locator('#add-step').click(); await page.locator('#step-form [name="name"]').fill('First');
  await page.locator('#add-step').click(); await page.locator('#step-form [name="name"]').fill('Second');
  const handle = page.locator('[data-drag-step]').first(); await handle.scrollIntoViewIfNeeded();
  const start = await handle.boundingBox(), end = await page.locator('#editor-steps > li').last().boundingBox();
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2); await page.mouse.down();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height - 2, {steps: 5});
  snapshot.control.controlling = false; await mode('view-only'); await page.mouse.up();
  assert.deepEqual(await page.locator('#editor-steps strong').allTextContents(), ['First', 'Second']);
  assert.equal(await page.locator('#step-form [name="name"]').isDisabled(), true);
  assert.deepEqual(errors, []);
  console.log('PASS: connected ownership transitions, open-dialog restriction, retained drafts, automatic exact strings, four dynamic device groups, refreshed constraints, themes and widths.');
} finally { await browser.close(); }
