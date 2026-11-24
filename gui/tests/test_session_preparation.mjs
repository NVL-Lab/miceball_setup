import {returnFromParameters} from './parameter_navigation.mjs';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const page = await browser.newPage();
const requests = [], errors = [];
let latest, lastState;
page.on('pageerror', error => errors.push(error.message));
page.on('websocket', socket => {
  socket.on('framesent', frame => {
    try { requests.push(JSON.parse(frame.payload)); } catch (_) {}
  });
  socket.on('framereceived', frame => {
    try {
      const details = JSON.parse(frame.payload).result?.outcome?.details;
      if (details?.status && typeof details.status === 'object') lastState = details;
      if (details?.status && details?.configuration) latest = details;
    } catch (_) {}
  });
});
try {
  await page.goto(process.env.MICEBALL_PREPARATION_ORIGIN);
  await page.locator('html[data-control-mode="view-only"]').waitFor();
  assert.equal(await page.locator('.launch-session-demo').isDisabled(), true);
  assert.match(await page.locator('.launch-session-demo span').innerText(), /View Only/);
  await page.locator('#take-over').click();
  await page.locator('html[data-control-mode="controlling"]').waitFor();
  await page.locator('[data-open-setup]').click();
  const protocol = process.env.MICEBALL_PREPARATION_PROTOCOL === '1';
  if (protocol) {
    await page.locator('#experimenter-select').selectOption('scientist');
    await page.locator('#project-select').selectOption('project');
  }
  await page.locator('#protocol-select').selectOption(protocol ? 'procedure' : '');
  await page.locator('#load-inventory').click();
  await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
  await page.locator('#session-device-list input').first().check();
  await page.locator('[data-setup-parameters]').click();
  await page.locator('#experiment-duration').fill('5');
  await page.locator('#device-validation-maximum').fill('8.5');
  await returnFromParameters(page);
  await page.locator('#artifact-destination').selectOption('default');
  await page.locator('#error-evidence-location').fill(process.env.MICEBALL_PREPARATION_ERRORS);
  await page.locator('.launch-session-demo').click();
  for (let count = 0; count < 150 && latest?.status?.session_state !== 'running'; count++) await page.waitForTimeout(100);
  assert.equal(latest?.status?.session_state, 'running', await page.locator('.setup-demo-note').textContent());
  const launch = requests.find(request => request.operation === 'launch_session');
  assert.equal(launch.parameters.config_parameters.protocol_reference, protocol ? 'Procedure' : null);
  assert.deepEqual(launch.parameters.config_parameters.protocol_plan, {});
  assert.equal(requests.filter(request => request.operation === 'start_launched_session').length, 1);
  assert.equal(requests.filter(request => request.operation === 'start_launched_experiment').length, 0);
  assert.equal('deviceValidationMaximumSeconds' in launch.parameters.config_parameters, false);
  const accepted = structuredClone(latest.configuration);
  await page.locator('[data-section="parameters"]').click();
  assert.equal(await page.locator('#device-validation-maximum').inputValue(), '8.5');
  await page.locator('#device-validation-maximum').fill('13.5');
  assert.equal(await page.locator('#device-validation-maximum').evaluate(input => input.checkValidity()), true);
  await page.locator('[data-section="session"]').click();
  if (!protocol) await page.locator('[data-prepare-free-operation]').waitFor({state: 'attached'});
  assert.equal(await page.locator('[data-validate-device]:enabled').count(), 0);
  assert.deepEqual(latest.configuration, accepted);
  if (process.env.MICEBALL_PREPARATION_CLOSEOUT === '1') {
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
    await page.locator('[data-stop-session]').click();
    await page.locator('[data-confirm-stop]').click();
    for (let count = 0; count < 200 && lastState?.status?.session_id; count++) await page.waitForTimeout(100);
    assert.equal(lastState?.status?.session_id, null, 'Controller must confirm binding release');
    assert.equal(lastState.configuration, null);
    assert.equal(requests.filter(request => request.operation === 'normal_stop_session').length, 1);
    assert.equal(requests.filter(request => request.operation === 'release_session').length, 1);
    await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
    await page.locator('[data-section="parameters"]').click();
    assert.equal(await page.locator('#device-validation-maximum').inputValue(), '13.5', 'Release does not reset GUI working settings');
    await page.locator('[data-section="setup"]').click();
    await page.locator('[data-open-setup]').click();
    await page.locator('#error-evidence-location').fill(process.env.MICEBALL_PREPARATION_ERRORS);
    await page.locator('#load-inventory').click();
    await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
    await page.locator('#session-device-list input').first().check();
    await page.locator('.launch-session-demo').click();
    await page.locator('[data-section="session"]').click();
    await page.locator('[data-stop-session]:enabled').waitFor();
    await page.locator('[data-section="parameters"]').click();
    assert.equal(await page.locator('#device-validation-maximum').inputValue(), '13.5', 'The next Session shares GUI working settings, not scientific configuration');
    await page.locator('[data-section="session"]').click();
    await page.locator('[data-stop-session]').click(); await page.locator('[data-confirm-stop]').click();
    await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
    console.log('PASS: one Stop confirmation completed Normal Stop and release through real NATS owners');
  }
  assert.deepEqual(errors, []);
  console.log('PASS: JSON-free five-second Free Mode preparation through real owners; Session running; no Experiment started');
} finally { await browser.close(); }
