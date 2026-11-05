import assert from 'node:assert/strict';

export async function verifyConfigurationIntegrity(browser, origin, fixture, section) {
  const page = await browser.newPage();
  const sent = [], errors = [];
  let configuration = null, phase = null, executed = false, unsafeReadback = false;
  let numericExpected = null;
  let numericRequests = 0;
  let completed = false, repeatExpected = null, repeatRequests = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/ws', route => {
    route.onMessage(raw => {
      const message = JSON.parse(raw); sent.push(message);
      let details, status = 'succeeded';
      if (message.operation === 'read_controller_state') {
        details = {controller_id: 'integrity', instance_id: 'integrity-instance', control: {controlling: true, generation: 1},
          configured_nodes: Object.keys(fixture.inventories), pending_operations: [], configuration,
          status: {session_id: configuration?.session_id || null, session_state: phase,
            active_experiment_id: executed && !completed ? 'integrity-experiment' : null,
            experiment_lifecycle_evidence: completed ? [{experiment_id: 'integrity-experiment', event_type: 'experiment_stop', sequence: 1, session_time_s: 2}] : []},
          experiments: executed ? [{experiment_id: 'integrity-experiment', configuration: fixture.experiment, scientific_outputs: fixture.outputs}] : [],
          ...(unsafeReadback ? {unsupported_number: 0} : {})};
      } else if (message.operation === 'get_node_inventory') details = fixture.inventories[message.parameters.node_id];
      else if (message.operation === 'launch_session') {
        assert.deepEqual(message.parameters.selections, Object.fromEntries(Object.entries(fixture.inventories).map(([node, inventory]) => [node, inventory.devices])));
        assert.deepEqual(message.parameters.config_parameters.session_parameters, fixture.session.session_parameters);
        configuration = fixture.session; phase = 'initialized'; details = {session_id: configuration.session_id};
      } else if (message.operation === 'start_launched_session') phase = 'running';
      else if (message.operation === 'start_launched_experiment') {
        if (numericExpected !== null) {
          assert.deepEqual(message.parameters.configuration.device_configurations,
            {['__proto__']: {['__proto__']: {count: numericExpected}}});
          numericRequests++; status = 'rejected';
        } else if (repeatExpected !== null) {
          assert.equal(message.parameters.experiment_id, 'integrity-repeat');
          assert.deepEqual(message.parameters.configuration, fixture.experiment);
          const coordinates = outputs => outputs.map(output => [output.source_node_id, output.source_device_id, output.data_product_id]).sort();
          assert.deepEqual(coordinates(message.parameters.scientific_outputs), coordinates(repeatExpected));
          repeatRequests++; status = 'rejected';
        } else {
          assert.deepEqual(message.parameters.configuration, fixture.experiment);
          assert.deepEqual(message.parameters.scientific_outputs, fixture.outputs);
          executed = true;
        }
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
  const outputControl = async output => {
    const index = await page.locator('[data-scientific-output]').evaluateAll((inputs, output) => inputs.findIndex(input => {
      const item = JSON.parse(input.dataset.scientificOutput);
      return item.source_node_id === output.source_node_id && item.source_device_id === output.source_device_id && item.data_product_id === output.data_product_id;
    }), output);
    assert.ok(index >= 0, `Missing scientific output ${JSON.stringify(output)}`);
    return page.locator('[data-scientific-output]').nth(index);
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
    for (const text of ['9007199254740993', '1.0000000000000001', '9007199254740991.1']) {
      await page.locator('#session-framework-fields').fill(`{"protocol_plan":{},"device_configurations":{"__proto__":{"count":${text}}}}`);
      await page.locator('.launch-session-demo').click();
      assert.equal(sent.filter(message => message.operation === 'launch_session').length, 0);
      assert.match(await page.locator('.setup-demo-note').innerText(), /cannot be represented faithfully/);
    }
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
    await page.locator('#experiment-duration').fill('2');
    await page.locator('[data-framework-field="experimentId"]').fill('integrity-experiment');
    await page.locator('[data-framework-field="preservationBudget"]').fill('1000000');
    for (const input of await page.locator('[data-recording-budget]').all()) await input.fill('100000');
    const count = ['__proto__', '__proto__', 'count'];
    for (const text of ['1.5', '1.0000000000000001', '9007199254740991.1', '-1.0000000000000001', '1e-20']) {
      const input = await control('data-example-value', count);
      await input.fill(text);
      assert.equal(await input.inputValue(), text);
      assert.ok((await page.locator('#parameter-feedback').innerText()).includes(text));
      await page.locator('[data-return-session]').click();
      assert.ok((await page.locator('.experiment-parameter-summary').innerText()).includes(`count: ${text}`));
      assert.equal(await page.locator('[data-launch-experiment]').isDisabled(), true);
      await page.locator('[data-launch-experiment]').evaluate(button => button.dispatchEvent(new MouseEvent('click', {bubbles: true})));
      await page.waitForTimeout(50);
      assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, 0);
      await page.locator('[data-session-navigate="parameters"]').click();
    }
    for (const [text, expected] of [['7', 7], ['1e3', 1000], ['100e-2', 1], ['0', 0],
      ['9007199254740991', 9007199254740991], ['-9007199254740991', -9007199254740991]]) {
      await (await control('data-example-value', count)).fill(text);
      await page.locator('[data-return-session]').click();
      assert.equal(await page.locator('[data-launch-experiment]').isEnabled(), true);
      numericExpected = expected;
      await page.locator('[data-launch-experiment]').click();
      await page.waitForFunction(() => !document.querySelector('[data-launch-experiment]').disabled);
      await page.locator('[data-session-navigate="parameters"]').click();
    }
    assert.equal(numericRequests, 6);
    numericExpected = null;
    console.log('PASS: all four audited integer cases, negative/non-integral tokens, valid exponent notation, zero and safe-integer boundaries through production editing/submission');
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
    for (const input of await page.locator('[data-scientific-output]').all()) assert.equal(await input.isChecked(), false);
    for (const output of fixture.outputs) await (await outputControl(output)).check();
    assert.equal(await (await outputControl(fixture.additional_output)).isChecked(), false);
    const large = ['__proto__', '__proto__', 'large'];
    await (await control('data-example-value', large)).fill('9007199254740993');
    assert.match(await page.locator('#parameter-feedback').innerText(), /cannot be represented faithfully/);
    await page.locator('[data-return-session]').click();
    assert.equal(await page.locator('[data-launch-experiment]').isDisabled(), true);
    await page.locator('[data-launch-experiment]').evaluate(button => button.click());
    assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, numericRequests);
    await page.locator('[data-session-navigate="parameters"]').click();
    const overflow = await control('data-example-value', large);
    await overflow.fill(''); await overflow.pressSequentially('1e999');
    assert.equal(await overflow.evaluate(input => input.validity.badInput), true);
    assert.match(await page.locator('#parameter-feedback').innerText(), /Invalid numeric input/);
    await page.locator('[data-return-session]').click();
    assert.equal(await page.locator('[data-launch-experiment]').isDisabled(), true);
    await page.locator('[data-launch-experiment]').evaluate(button => button.click());
    assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, numericRequests);
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
    for (const output of fixture.outputs) {
      const input = await outputControl(output);
      assert.equal(await input.isChecked(), true, 'Framework-produced selected output must render checked');
      assert.equal(await input.isDisabled(), true);
    }
    assert.equal(await (await outputControl(fixture.additional_output)).isChecked(), false);
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
    assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, numericRequests + 1);
    completed = true;
    await page.locator('[data-prepare-experiment]').waitFor();
    await page.locator('[data-prepare-experiment]').click();
    await page.locator('[data-session-navigate="parameters"]').click();
    await page.locator('[data-framework-field="experimentId"]').fill('integrity-repeat');
    for (const output of fixture.outputs) {
      const input = await outputControl(output);
      assert.equal(await input.isChecked(), true);
      await input.uncheck();
    }
    const first = await outputControl(fixture.outputs[0]);
    await first.check(); await first.uncheck();
    const submitRepeat = async outputs => {
      repeatExpected = outputs;
      const previous = repeatRequests;
      await page.locator('[data-return-session]').click();
      await page.locator('[data-launch-experiment]').click();
      await page.waitForFunction(() => !document.querySelector('[data-launch-experiment]').disabled);
      assert.equal(repeatRequests, previous + 1);
      await page.locator('[data-session-navigate="parameters"]').click();
    };
    await submitRepeat([]);
    for (const input of await page.locator('[data-scientific-output]').all()) assert.equal(await input.isChecked(), false);
    const subset = [fixture.outputs.at(-1), fixture.outputs[0], fixture.additional_output];
    for (const output of subset) {
      const input = await outputControl(output);
      await input.check(); await input.uncheck(); await input.check();
    }
    await submitRepeat(subset);
    await (await outputControl(fixture.additional_output)).uncheck();
    await submitRepeat([fixture.outputs.at(-1), fixture.outputs[0]]);
    for (const output of fixture.outputs) {
      assert.equal(await (await outputControl(output)).isChecked(), output === fixture.outputs[0] || output === fixture.outputs.at(-1));
    }
    assert.equal(await (await outputControl(fixture.additional_output)).isChecked(), false);
    assert.equal(sent.filter(message => message.operation === 'start_launched_experiment').length, numericRequests + 4);
    console.log('PASS: canonical framework outputs render selected; repeat deselection submits []; reordered editing preserves exact empty/partial sets across nodes, delimiter identities and distinct products');
    assert.deepEqual(errors, []);
    console.log('PASS: independently specified Session/Experiment configurations, prototype keys, coordinate collisions, empty/unset/null/zero/false, numeric refusal, authoritative readback and no replay');
  } finally {await page.close();}
}

export async function verifyExperimentReconnection(browser, origin, fixture, section) {
  const page = await browser.newPage(), requests = [], errors = [];
  let snapshot = fixture.snapshots[0], connection;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/ws', route => {
    connection = route;
    route.onMessage(raw => {
      const message = JSON.parse(raw); requests.push(message.operation);
      assert.ok(['read_controller_state', 'get_node_inventory'].includes(message.operation));
      route.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'monitor-instance',
        result: {status: 'succeeded', outcome: {details: message.operation === 'get_node_inventory' ? fixture.inventory : snapshot}}}));
    });
    route.send(JSON.stringify({type: 'connected', browser_id: 'monitor-observer'}));
  });
  const inventory = async () => {
    await page.locator('[data-open-setup]').click();
    await page.locator('#load-inventory').click();
    await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
  };
  const monitor = async (identity, duration, gain, source) => {
    await page.locator('#experiment-monitor-fields').filter({hasText: identity}).waitFor();
    const information = await page.locator('#experiment-monitor-fields').innerText();
    assert.ok(information.includes(`${duration} s`));
    await page.locator('#experiment-parameters-drawer').filter({hasText: `gain: ${gain}`}).waitFor();
    assert.match(await page.locator('#experiment-parameters-drawer').innerText(), new RegExp(source));
  };
  const reconnect = async () => {
    connection.close();
    await page.locator('#connection-state').filter({hasText: 'Backend disconnected'}).waitFor();
    await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
  };
  try {
    await page.goto(origin);
    await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
    await inventory();
    await section(page, 'session');
    await page.locator('[data-prepare-free-operation]').click();
    await page.locator('[data-session-navigate="parameters"]').click();
    await page.locator('#experiment-duration').fill('99');
    await section(page, 'experiment');
    await page.locator('[data-show-experiment-parameters]').click();
    await monitor('first', 11, 1.25, 'Fixed executed-attempt configuration');
    snapshot = fixture.snapshots[1];
    await reconnect();
    await monitor('latest', 22, 8.5, 'Fixed executed-attempt configuration');
    await section(page, 'session');
    await page.locator('[data-session-navigate="parameters"]').click();
    assert.equal(await page.locator('#experiment-duration').inputValue(), '99');
    assert.equal(await page.locator('#experiment-duration').isEnabled(), true);
    await section(page, 'experiment');
    snapshot = structuredClone(fixture.snapshots[1]);
    snapshot.status.active_experiment_id = 'latest';
    snapshot.status.experiment_lifecycle_evidence.pop();
    await reconnect();
    await monitor('latest', 22, 8.5, 'Fixed executing-attempt configuration');
    snapshot = fixture.snapshots[1];
    await page.reload();
    await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
    await inventory();
    await section(page, 'experiment');
    await page.locator('[data-show-experiment-parameters]').click();
    await monitor('latest', 22, 8.5, 'Fixed executed-attempt configuration');
    assert.deepEqual(errors, []);
    assert.ok(requests.includes('read_controller_state'));
    assert.ok(requests.every(operation => ['read_controller_state', 'get_node_inventory'].includes(operation)));
    console.log('PASS: framework-produced first/latest lifecycle readback, completed/running reconnect, fresh observer, exact executed duration/gain and separate unsent preparation; no lifecycle replay');
  } finally {await page.close();}
}
