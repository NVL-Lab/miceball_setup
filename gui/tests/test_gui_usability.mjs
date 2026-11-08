import assert from 'node:assert/strict';

export async function verifyDemoAdministrator(browser, origin, section, directory) {
  const page = await browser.newPage();
  try {
    await page.goto(origin); await section(page, 'services');
    const history = page.locator('#control-activity-history');
    assert.equal(await history.evaluate(node => node.open), false);
    await history.locator(':scope > summary').click();
    assert.match(await history.innerText(), /No retained browser-control activity/);
    await history.locator(':scope > summary').click();
    await page.locator('[data-mode="administrator"]').click();
    await page.locator('[data-danger-enter]').click();
    for (const theme of ['light', 'dark']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
      await page.locator('[data-shutdown-framework]').click();
      const name = page.locator('dialog[open] input[data-administrator-name]');
      assert.equal(await name.count(), 1, 'Demo shutdown must require a manually entered Administrator name');
      assert.equal(await name.inputValue(), '');
      const confirm = page.locator('[data-confirm-shutdown]');
      assert.equal(await confirm.isDisabled(), true);
      await name.fill('   '); assert.equal(await confirm.isDisabled(), true);
      await name.fill('Lab Operator'); assert.equal(await confirm.isEnabled(), true);
      await page.keyboard.press('Escape');
      await page.locator('[data-shutdown-framework]').click();
      assert.equal(await name.inputValue(), '');
      await name.fill('Lab Operator'); await confirm.click();
      await page.locator('[data-finish-shutdown]').click();
      await page.locator('[data-kill-service]').first().click();
      assert.equal(await name.inputValue(), '');
      assert.equal(await page.locator('[data-confirm-kill]').isDisabled(), true);
      assert.equal(await page.locator('dialog[open] input[type="checkbox"]').count(), 0);
      await name.fill('  '); assert.equal(await page.locator('[data-confirm-kill]').isDisabled(), true);
      await name.fill('Lab Operator'); await page.locator('[data-confirm-kill]').click();
      await page.locator('[data-admin-close]').click();
      await page.screenshot({path: `${directory}/administrator-demo-${theme}.png`, fullPage: true});
    }
    await page.locator('[data-expand-service]').first().click();
    await page.locator('button[data-stop-service]').click();
    assert.equal(await page.locator('[data-administrator-name]').inputValue(), '');
    assert.equal(await page.locator('[data-confirm-shutdown]').isDisabled(), true);
    await page.locator('[data-admin-close]').click();
    await page.locator('[data-administrative="Abandon outstanding obligations"]').click();
    assert.equal(await page.locator('[data-administrator-name]').inputValue(), '');
    assert.equal(await page.locator('[data-admin-review]').isDisabled(), true);
    await page.locator('[data-administrator-name]').fill('  ');
    assert.equal(await page.locator('[data-admin-review]').isDisabled(), true);
    await page.locator('[data-administrator-name]').fill('Lab Operator');
    await page.locator('[data-admin-review]').click();
    assert.match(await page.locator('[data-admin-outcome]').innerText(), /local preview only/);
    await page.locator('[data-admin-close]').click();
    console.log('PASS: demo Shutdown/Kill names, empty/whitespace rejection, fresh entry, Escape and both themes');
  } finally { await page.close(); }
}

// Developer rendering checks with controlled transport; not independent validation.
export async function verifyGuiUsability(browser, origin, configuration, section, directory) {
  const context = await browser.newContext({timezoneId: 'Pacific/Honolulu', viewport: {width: 1440, height: 1000}});
  await context.addInitScript(() => {
    const NativeDate = Date, instant = NativeDate.UTC(2027, 0, 1, 2);
    globalThis.Date = class extends NativeDate {
      constructor(...args) { super(...(args.length ? args : [instant])); }
      static now() { return instant; }
    };
    sessionStorage.setItem('miceball-pending', JSON.stringify([
      {operation: 'view_only', request_id: 'retained-control', instance_id: 'usability-instance', status: 'succeeded',
        result: {status: 'succeeded', timestamp: '2026-11-06T12:34:56Z'}},
      {operation: 'take_browser_control', request_id: 'pending-control', instance_id: 'usability-instance', status: 'uncertain'},
    ]));
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
      if (message.operation === 'read_operation_outcome') return reply(route, message, 'succeeded',
        {status: 'succeeded', result: {status: 'succeeded', request_id: 'pending-control'}});
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
      const observingHeader = await page.locator('.topbar').evaluate(node => getComputedStyle(node).backgroundColor);
      await page.locator('#take-over').click(); await page.locator('html[data-control-mode="controlling"]').waitFor();
      assert.notEqual(await page.locator('html').evaluate(html => getComputedStyle(html).getPropertyValue('--workspace')), observing);
      assert.notEqual(await page.locator('.topbar').evaluate(node => getComputedStyle(node).backgroundColor), observingHeader);
      await page.screenshot({path: `${directory}/usability-controlling-${theme}.png`});
      await page.locator('#view-only').click(); await page.locator('html[data-control-mode="view-only"]').waitFor();
      await page.setViewportSize({width: 800, height: 900});
      await page.screenshot({path: `${directory}/usability-view-only-${theme}.png`});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.locator('#take-over').click(); await page.locator('html[data-control-mode="controlling"]').waitFor();
    await section(page, 'session');
    assert.doesNotMatch(await page.locator('#operation-results').innerText(), /take_browser_control|view_only/);
    assert.equal(await page.locator('.topbar .control-activity').count(), 0);
    await section(page, 'services');
    const history = page.locator('#control-activity-history');
    assert.equal(await history.evaluate(node => node.open), false);
    assert.equal(await history.evaluate(node => node === node.parentElement.lastElementChild), true);
    await history.locator(':scope > summary').click();
    await history.locator('details summary').filter({hasText: 'Take browser control'}).first().click();
    assert.match(await history.innerText(), /Take browser control/);
    assert.match(await history.innerText(), /take_browser_control/);
    await history.locator('details summary').filter({hasText: 'View Only'}).first().click();
    assert.match(await history.innerText(), /2026-11-06T12:34:56Z/);
    const retained = await page.evaluate(() => JSON.parse(sessionStorage.getItem('miceball-pending')));
    assert.deepEqual(retained[0], {operation: 'view_only', request_id: 'retained-control', instance_id: 'usability-instance', status: 'succeeded', result: {status: 'succeeded', timestamp: '2026-11-06T12:34:56Z'}});
    assert.equal(retained.find(entry => entry.request_id === 'pending-control').status, 'succeeded');
    await page.locator('[data-refresh-services]').click();
    assert.equal(await history.evaluate(node => node.open), true);
    assert.match(await history.innerText(), /2026-11-06T12:34:56Z/);
    await page.screenshot({path: `${directory}/services-control-history.png`, fullPage: true});
    await history.locator(':scope > summary').click(); await section(page, 'setup');

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
