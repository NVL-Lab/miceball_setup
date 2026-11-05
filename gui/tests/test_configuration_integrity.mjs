import assert from 'node:assert/strict';

export async function verifyConfigurationIntegrity(browser, origin, fixture, section) {
  const page = await browser.newPage();
  const sent = [], errors = [];
  let configuration = null, phase = null, executed = false, unsafeReadback = false;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/ws', route => {
    route.onMessage(raw => {
      const message = JSON.parse(raw); sent.push(message);
      let details, status = 'succeeded';
      if (message.operation === 'read_controller_state') {
        details = {controller_id: 'integrity', instance_id: 'integrity-instance', control: {controlling: true, generation: 1},
          configured_nodes: Object.keys(fixture.inventories), pending_operations: [], configuration,
          status: {session_id: configuration?.session_id || null, session_state: phase,
            active_experiment_id: executed ? 'integrity-experiment' : null, experiment_lifecycle_evidence: []},
          experiments: executed ? [{experiment_id: 'integrity-experiment', configuration: fixture.experiment, scientific_outputs: fixture.outputs}] : [],
          ...(unsafeReadback ? {unsupported_number: 0} : {})};
      } else if (message.operation === 'get_node_inventory') details = fixture.inventories[message.parameters.node_id];
      else if (message.operation === 'launch_session') {
        assert.deepEqual(message.parameters.selections, Object.fromEntries(Object.entries(fixture.inventories).map(([node, inventory]) => [node, inventory.devices])));
        assert.deepEqual(message.parameters.config_parameters.session_parameters, fixture.session.session_parameters);
        configuration = fixture.session; phase = 'initialized'; details = {session_id: configuration.session_id};
      } else if (message.operation === 'start_launched_session') phase = 'running';
      else if (message.operation === 'start_launched_experiment') {
        assert.deepEqual(message.parameters.configuration, fixture.experiment);
        assert.deepEqual(message.parameters.scientific_outputs, fixture.outputs);
        executed = true;
      } else throw new Error(`Unexpected integrity operation: ${message.operation}`);
      let reply = JSON.stringify({type: 'result', id: message.id, instance_id: 'integrity-instance', result: {status, outcome: {details}}});
      if (unsafeReadback && message.operation === 'read_controller_state') reply = reply.replace('"unsupported_number":0', '"unsupported_number":9007199254740993');
      route.send(reply);
    });
    route.send(JSON.stringify({type: 'connected', browser_id: 'integrity-browser'}));
  });
  const control = async (attribute, coordinates) => {
    const key = JSON.stringify(coordinates);
    const index = await page.locator(`[${attribute}]`).evaluateAll((elements, {key, attribute}) => elements.findIndex(element => element.getAttribute(attribute) === key), {key, attribute});
    assert.ok(index >= 0, `Missing control ${key}`);
    return page.locator(`[${attribute}]`).nth(index);
  };
  try {
    await page.goto(origin);
    await page.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    await page.locator('[data-open-setup]').click();
    for (const [node, inventory] of Object.entries(fixture.inventories)) {
      await page.locator('#inventory-node').selectOption(node);
      await page.locator('#load-inventory').click();
      await page.locator('#inventory-status').filter({hasText: `${node}: inventory confirmed`}).waitFor();
      const keys = inventory.devices.map(device => JSON.stringify([node, device.device_id]));
      for (const key of keys) {
        const input = page.locator('#session-device-list input');
        const index = await input.evaluateAll((elements, key) => elements.findIndex(element => element.dataset.device === key), key);
        await input.nth(index).check();
      }
    }
    await page.locator('.session-identity-grid input[type="text"]').fill(fixture.session.session_parameters.name);
    await page.locator('.session-identity-grid input[type="date"]').fill(fixture.session.session_parameters.date);
    await page.locator('.session-identity-grid input[type="number"]').fill('0');
    await page.locator('[aria-labelledby="notes-title"] textarea').fill('notes');
    await page.locator('[aria-labelledby="storage-title"] input').first().fill(fixture.session.storage_location);
    await page.locator('#error-evidence-location').fill(fixture.session.error_evidence_location);
    await page.locator('details').filter({has: page.locator('#session-framework-fields')}).last().evaluate(element => element.open = true);
    const fields = {protocol_plan: {}, session_parameters: fixture.session.session_parameters};
    await page.locator('#session-framework-fields').fill('{"protocol_plan":{},"unsafe":9007199254740993}');
    await page.locator('.launch-session-demo').click();
    assert.equal(sent.filter(message => message.operation === 'launch_session').length, 0);
    assert.match(await page.locator('.setup-demo-note').innerText(), /cannot be represented faithfully/);
    await page.locator('#session-framework-fields').fill(JSON.stringify(fields));
    await page.locator('.launch-session-demo').click();
    await page.locator('[data-start-session]').waitFor();
    await page.locator('[data-start-session]').click();
    await page.locator('[data-prepare-free-operation]').click();
    await page.locator('.experiment-additional-devices').evaluate(element => element.open = true);
    for (let index = 0; index < fixture.session.selected_devices.length; index++) {
      const input = page.locator('[data-session-experiment-device]').nth(index);
      await input.check(); await input.uncheck(); await input.check();
    }
    await page.locator('[data-session-navigate="parameters"]').click();
    for (const row of fixture.rows) {
      const coordinates = [row.node, row.device, row.name];
      const input = await control('data-example-value', coordinates);
      if (row.value === null) await (await control('data-null-parameter', coordinates)).click();
      else if (typeof row.value === 'boolean') {await input.check(); if (!row.value) await input.uncheck();}
      else {await input.fill(row.value === '' ? 'temporary' : String(row.value)); if (row.value === '') await input.fill('');}
    }
    const unset = ['constructor', 'ordinary', 'unset'];
    await (await control('data-example-value', unset)).fill('42');
    await (await control('data-unset-parameter', unset)).click();
    await page.locator('#experiment-duration').fill('2');
    await page.locator('[data-framework-field="experimentId"]').fill('integrity-experiment');
    await page.locator('[data-framework-field="preservationBudget"]').fill('1000000');
    for (const input of await page.locator('[data-recording-budget]').all()) await input.fill('100000');
    for (const input of await page.locator('[data-scientific-output]').all()) await input.check();
    const large = ['__proto__', '__proto__', 'large'];
    await (await control('data-example-value', large)).fill('9007199254740993');
    assert.match(await page.locator('#parameter-feedback').innerText(), /cannot be represented faithfully/);
    await page.locator('[data-return-session]').click();
    assert.equal(await page.locator('[data-launch-experiment]').isDisabled(), true);
    await page.locator('[data-launch-experiment]').evaluate(button => button.click());
    assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, 0);
    await page.locator('[data-session-navigate="parameters"]').click();
    const overflow = await control('data-example-value', large);
    await overflow.fill(''); await overflow.pressSequentially('1e999');
    assert.equal(await overflow.evaluate(input => input.validity.badInput), true);
    assert.match(await page.locator('#parameter-feedback').innerText(), /Invalid numeric input/);
    await page.locator('[data-return-session]').click();
    assert.equal(await page.locator('[data-launch-experiment]').isDisabled(), true);
    await page.locator('[data-launch-experiment]').evaluate(button => button.click());
    assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, 0);
    await page.locator('[data-session-navigate="parameters"]').click();
    await (await control('data-example-value', large)).fill('7');
    await page.locator('[data-return-session]').click();
    await page.locator('[data-launch-experiment]').click();
    await page.locator('.experiment-current-card h4').filter({hasText: 'executed'}).waitFor({state: 'attached'});
    await section(page, 'session');
    await page.locator('[data-session-navigate="parameters"]').click();
    for (const row of fixture.rows) {
      const input = await control('data-example-value', [row.node, row.device, row.name]);
      assert.equal(await input.isDisabled(), true);
      if (typeof row.value === 'boolean') assert.equal(await input.isChecked(), row.value);
      else assert.equal(await input.inputValue(), row.value === null ? '' : String(row.value));
    }
    await section(page, 'experiment');
    await page.locator('[data-show-experiment-parameters]').click();
    const drawer = await page.locator('#experiment-parameters-drawer').innerText();
    assert.match(drawer, /nullable: null/);
    assert.match(drawer, /unset: No explicit override/);
    assert.doesNotMatch(drawer, /nullable: Unavailable/);
    unsafeReadback = true;
    await page.locator('#connection-state').filter({hasText: 'Unconfirmed'}).waitFor();
    await section(page, 'session');
    assert.equal(await page.locator('[data-stop-session]').isDisabled(), true);
    unsafeReadback = false;
    await page.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    assert.equal(sent.filter(message => message.operation === 'launch_session').length, 1);
    assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, 1);
    assert.deepEqual(errors, []);
    console.log('PASS: independently specified Session/Experiment configurations, prototype keys, coordinate collisions, empty/unset/null/zero/false, numeric refusal, authoritative readback and no replay');
  } finally {await page.close();}
}
