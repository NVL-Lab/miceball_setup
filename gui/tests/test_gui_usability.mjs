import assert from 'node:assert/strict';

// Developer rendering checks with controlled transport; not independent validation.
export async function verifyGuiUsability(browser, origin, configuration, section, directory) {
  const context = await browser.newContext({timezoneId: 'Pacific/Honolulu', viewport: {width: 1440, height: 1000}});
  await context.addInitScript(() => {
    const NativeDate = Date, instant = NativeDate.UTC(2027, 0, 1, 2);
    globalThis.Date = class extends NativeDate {
      constructor(...args) { super(...(args.length ? args : [instant])); }
      static now() { return instant; }
    };
  });
  const page = await context.newPage(), submitted = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let controlling = false, accepted = null, connection, pendingRelease;
  const snapshot = () => ({controller_id: 'usability', instance_id: 'usability-instance',
    control: {controlling, generation: 1}, status: {session_id: accepted ? 'usability-session' : null, session_state: accepted ? 'completed' : null},
    configuration: accepted, experiments: [], configured_nodes: [], configured_services: [], pending_operations: []});
  const reply = (route, message, status, details) => route.send(JSON.stringify({type: 'result', id: message.id,
    instance_id: 'usability-instance', result: {status, request_id: message.id, outcome: {details}}}));
  await page.routeWebSocket('**/ws', route => {
    connection = route;
    route.onMessage(raw => {
      const message = JSON.parse(raw);
      if (message.operation === 'read_controller_state') return reply(route, message, 'succeeded', snapshot());
      submitted.push(message);
      if (message.operation === 'take_browser_control') controlling = true;
      else if (message.operation === 'view_only') controlling = false;
      else if (message.operation === 'launch_session') accepted = {...configuration, ...message.parameters.config_parameters};
      else if (message.operation === 'release_session') { pendingRelease = {route, message}; return; }
      else throw new Error(`Unexpected usability operation ${message.operation}`);
      reply(route, message, 'succeeded', {});
    });
    route.send(JSON.stringify({type: 'connected', browser_id: 'usability-browser'}));
  });
  try {
    await page.goto(origin);
    await page.locator('html[data-control-mode="view-only"]').waitFor();
    const date = page.locator('.session-identity-grid input[type="date"]');
    assert.equal(await date.inputValue(), '2026-12-31'); // Local day differs from UTC Jan 1.
    await date.fill('2026-11-15');
    await section(page, 'session'); await section(page, 'setup');
    assert.equal(await date.inputValue(), '2026-11-15');

    await page.locator('#project-select').selectOption('__new_project');
    const primary = page.locator('#catalog-fields [name="primary_experimenter"]');
    assert.equal(await primary.locator('option').count(), 1);
    await page.locator('#catalog-fields [name="project_name"]').fill('New Project');
    assert.equal(await primary.evaluate(control => control.checkValidity()), false);
    await page.locator('[data-dialog-dismiss]').first().click();
    await page.locator('#experimenter-select').selectOption('__new_experimenter');
    await page.locator('#catalog-fields [name="name"]').fill('New Scientist'); await page.locator('#catalog-save').click();
    await page.locator('#project-select').selectOption('__new_project');
    await page.locator('#catalog-fields [name="project_name"]').fill('New Project');
    await primary.evaluate(control => control.add(new Option('Missing Experimenter', 'missing-experimenter')));
    await primary.selectOption('missing-experimenter'); await page.locator('#catalog-save').click();
    assert.equal(await page.locator('#catalog-dialog').isVisible(), true);
    assert.equal(await primary.evaluate(control => control.validity.customError), true);
    await primary.selectOption('New Scientist'); await page.locator('#catalog-save').click();
    assert.equal(await page.locator('#project-select option:checked').getAttribute('data-primary-experimenter'), 'New Scientist');

    for (const theme of ['light', 'dark']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
      const observing = await page.locator('html').evaluate(html => getComputedStyle(html).getPropertyValue('--workspace'));
      await page.locator('#take-over').click(); await page.locator('html[data-control-mode="controlling"]').waitFor();
      assert.notEqual(await page.locator('html').evaluate(html => getComputedStyle(html).getPropertyValue('--workspace')), observing);
      await page.locator('#view-only').click(); await page.locator('html[data-control-mode="view-only"]').waitFor();
      await page.setViewportSize({width: 800, height: 900});
      await page.screenshot({path: `${directory}/usability-view-only-${theme}.png`});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.locator('#take-over').click(); await page.locator('html[data-control-mode="controlling"]').waitFor();
    await section(page, 'session');
    assert.doesNotMatch(await page.locator('#operation-results').innerText(), /take_browser_control|view_only/);
    await page.locator('.control-activity > summary').click();
    assert.match(await page.locator('#control-outcomes').innerText(), /take_browser_control/);
    await page.locator('.control-activity > summary').click(); await section(page, 'setup');

    const name = page.locator('.session-identity-grid textarea[data-configuration-string]');
    assert.equal(await name.getAttribute('data-string-encoding'), 'text');
    const pasted = 'pasted\r\ntext\0';
    await name.evaluate((control, text) => {
      const transfer = new DataTransfer(); transfer.setData('text/plain', text);
      control.dispatchEvent(new ClipboardEvent('paste', {clipboardData: transfer, bubbles: true, cancelable: true}));
    }, pasted);
    assert.equal(await name.getAttribute('data-string-encoding'), 'exact');
    assert.equal(JSON.parse(await name.inputValue()), pasted);
    await name.locator('xpath=following-sibling::button[1]').click();
    assert.equal(JSON.parse(await name.inputValue()), pasted);
    await name.fill('"ordinary again"');
    await name.locator('xpath=following-sibling::button[1]').click();
    assert.equal(await name.getAttribute('data-string-encoding'), 'text');
    const text = '  "Session Ω" \\n literal  ', storage = 'C:\\data\\ordinary path', notes = 'first line\nsecond line Ω';
    await name.fill(text);
    await page.locator('[aria-labelledby="notes-title"] textarea').fill(notes);
    await page.locator('[aria-labelledby="storage-title"] textarea[data-configuration-string]:not(#error-evidence-location)').fill(storage);
    await page.locator('#error-evidence-location').fill('C:\\errors');
    await page.locator('details').filter({has: page.locator('#session-framework-fields')}).last().evaluate(node => node.open = true);
    await page.locator('#session-framework-fields').fill(JSON.stringify(configuration));
    await page.locator('.launch-session-demo').click();
    await page.locator('.session-identity-grid textarea[readonly]').waitFor({state:'attached'});
    const sent = submitted.find(entry => entry.operation === 'launch_session').parameters.config_parameters;
    assert.equal(sent.session_parameters.name, text); assert.equal(sent.storage_location, storage);
    assert.equal(sent.session_parameters.notes, notes); assert.equal(sent.session_parameters.date, '2026-11-15');
    await section(page, 'session');
    assert.match(await page.locator('#operation-results').innerText(), /launch_session/);
    await page.locator('[data-release-session]').click(); await page.locator('[data-confirm-stop]').click();
    await page.waitForFunction(() => document.querySelector('.launch-session-demo').disabled);
    assert.equal(await page.locator('html').getAttribute('data-control-mode'), 'controlling'); // Busy is not View Only.
    while (!pendingRelease) await page.waitForTimeout(20);
    reply(pendingRelease.route, pendingRelease.message, 'failed', {}); pendingRelease = null;
    await page.locator('[data-release-session]').waitFor({state:'visible'});
    await page.waitForTimeout(50); assert.equal(await date.inputValue(), '2026-11-15');
    await page.locator('[data-release-session]').click(); await page.locator('[data-confirm-stop]').click();
    while (!pendingRelease) await page.waitForTimeout(20);
    accepted = null; reply(pendingRelease.route, pendingRelease.message, 'succeeded', {});
    await page.waitForFunction(() => document.querySelector('.session-identity-grid input[type="date"]').value === '2026-12-31');
    connection.close(); await page.locator('html[data-control-mode="unconfirmed"]').waitFor();
    assert.equal(await date.inputValue(), '2026-12-31');
    assert.deepEqual(errors, []);
    console.log('PASS: Project membership/association; ownership tint/history; ordinary text payloads; local date, failed/successful release and disconnection');
  } finally { await context.close(); }
}
