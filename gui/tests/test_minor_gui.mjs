import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
const page = await context.newPage(), errors = [];
page.on('pageerror', error => errors.push(error.message));
const origin = process.env.MICEBALL_MINOR_ORIGIN;
const snapshot = {controller_id: 'controller', instance_id: 'controller', control: {controlling: true, generation: 1},
  configured_nodes: ['node'], configured_services: [{component_type: 'controller', component_id: 'controller'}],
  status: {session_id: null}, configuration: null, pending_operations: [], experiments: []};
const inventory = {devices: [{device_id: 'cam1', enabled: true, declared_capabilities: [],
  scientific_products: [{data_product_id: 'frames', product_type: 'camera_frames', schema: {}, file_format: 'jsonl'}]}], session_parameter_definitions: {}};
await page.routeWebSocket('**/ws', socket => {
  socket.onMessage(raw => {
    const message = JSON.parse(raw);
    socket.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'controller', result: {
      status: 'succeeded', outcome: {details: message.operation === 'get_node_inventory' ? inventory
        : message.operation === 'read_service_status' ? {current: false, reason: 'Controlled unavailable report', details: {}} : snapshot}}}));
  });
  socket.send(JSON.stringify({type: 'connected', browser_id: 'minor'}));
});
const section = name => page.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
try {
  await page.goto(origin); await page.locator('html[data-control-mode="controlling"]').waitFor();
  await page.locator('#load-inventory').click();
  if (process.argv[2] === 'outputs') {
    await page.locator('#session-device-list input').check();
    await page.locator('[data-setup-parameters]').click();
    await page.locator('[data-parameter-participant]').check();
    const output = page.locator('[data-scientific-output]');
    assert.equal(await output.count(), 1);
    const initial = await output.isChecked();
    const group = output.locator('xpath=ancestor::section[1]');
    assert.equal(await group.getByRole('heading', {name: 'Scientific Outputs', exact: true}).count(), 1);
    assert.equal(await group.locator('[data-recording-budget]').count(), 0);
    assert.equal(await group.locator('[data-parameter-participant]').count(), 0);
    assert.equal(await output.isChecked(), initial);
    await output.uncheck();
    await page.locator('[data-parameter-participant]').uncheck();
    await page.locator('[data-parameter-participant]').check();
    assert.equal(await output.isChecked(), false, 'Participation must not reselect outputs');
    await output.check(); assert.equal(await output.isChecked(), true);
    snapshot.configuration = {session_id: 'grouping-session', session_parameters: {name: 'Grouping Session'},
      protocol_reference: null, selected_devices: inventory.devices,
      expected_runtime_participants: [{component_type: 'acquisition_node', component_id: 'node'}]};
    snapshot.status = {session_id: 'grouping-session', session_state: 'running', active_experiment_id: null};
    await page.locator('#accepted-configuration').filter({hasText: 'grouping-session'}).waitFor({state: 'attached'});
    await section('session'); await page.locator('[data-prepare-free-operation]').click();
    const extra = page.locator('.experiment-additional-devices');
    if (!await extra.evaluate(element => element.open)) await extra.locator('summary').click();
    await page.locator('[data-session-experiment-device]').check();
    await page.locator('[data-session-navigate="parameters"]').click();
    assert.equal(await output.count(), 1);
    assert.equal(await group.getByRole('heading', {name: 'Scientific Outputs', exact: true}).count(), 1);
    for (const theme of ['light', 'dark']) for (const width of [1440, 800]) {
      await page.setViewportSize({width, height: 900});
      await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
      await group.scrollIntoViewIfNeeded();
      const bounds = await group.boundingBox(), heading = await group.locator('h4').boundingBox(), choice = await output.boundingBox();
      assert.ok(heading.x >= bounds.x && choice.x >= bounds.x && choice.y >= heading.y + heading.height);
      assert.ok(choice.y + choice.height <= bounds.y + bounds.height);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      if (process.env.LAB_SYNC_GUI_EVIDENCE_DIR) await page.screenshot({path: `${process.env.LAB_SYNC_GUI_EVIDENCE_DIR}/minor-outputs-${theme}-${width}.png`, fullPage: true});
    }
  } else {
    await section('services');
    await page.locator('[data-expand-service]').first().click();
    assert.equal(await page.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'true');
    const history = page.locator('#activity-history');
    await history.locator('summary').click();
    const message = history.locator('li span').first();
    await message.scrollIntoViewIfNeeded();
    const rect = await message.boundingBox();
    await page.mouse.move(rect.x + 1, rect.y + rect.height / 2); await page.mouse.down();
    await page.mouse.move(rect.x + rect.width - 1, rect.y + rect.height / 2, {steps: 10}); await page.mouse.up();
    const selected = await page.evaluate(() => getSelection().toString());
    assert.ok(selected.length > 5);
    await page.waitForTimeout(2300); // Existing Controller polling refreshes Services.
    assert.equal(await page.evaluate(() => getSelection().toString()), selected);
    assert.equal(await page.locator('[data-expand-service]').first().getAttribute('aria-expanded'), 'true');
    const count = await history.locator('li').count();
    await page.evaluate(async () => (await import('./activity-history.mjs')).recordLocalActivity('save_catalog'));
    assert.equal(await page.evaluate(() => getSelection().toString()), selected);
    assert.equal(await history.locator('li').count(), count + 1);
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin});
    const previous = await page.evaluate(() => navigator.clipboard.readText());
    try {
      await page.keyboard.press('Control+c');
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), selected);
    } finally { await page.evaluate(text => navigator.clipboard.writeText(text), previous); }
    await history.locator('summary').click(); assert.equal(await history.evaluate(element => element.open), false);
    await history.locator('summary').click(); assert.equal(await history.evaluate(element => element.open), true);
    await section('setup'); await section('services');
    assert.equal(await history.locator('li').count(), count + 1);
  }
  assert.deepEqual(errors, []);
  console.log(`PASS: ${process.argv[2]} presentation and existing interactions`);
} finally { await browser.close(); }
