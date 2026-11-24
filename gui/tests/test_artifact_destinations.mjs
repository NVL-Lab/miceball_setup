// Real GUI/backend shell, controlled Controller replies. No scientific operations.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || 'msedge'});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
const errors = [], submissions = [];
page.on('pageerror', error => errors.push(error.message));
let configuration = null, uncertain = false, unavailable = false, rejectLaunch = true;
const destinations = [
  {destination_id: 'default', name: 'Installation default', root: '/archive', enabled: true, validation: {status: 'unverified', available_bytes: 123456, reason: 'Admission validation required'}},
  {destination_id: 'other', name: 'Second disk', root: '/other', enabled: true, validation: {status: 'unverified', available_bytes: null}},
  {destination_id: 'missing', name: 'Offline disk', root: '/missing', enabled: true, validation: {status: 'invalid', reason: 'Directory absent'}}];
const snapshot = () => ({controller_id: 'controller', instance_id: 'instance', control: {controlling: true, generation: 1},
  configuration, status: {session_id: configuration?.session_id || null, session_state: configuration ? 'initialized' : null},
  experiments: [], configured_nodes: [], configured_services: [], pending_operations: []});
await page.routeWebSocket('**/ws', route => {
  route.onMessage(raw => {
    const message = JSON.parse(raw); let details = {}, status = 'succeeded', error = '';
    if (message.operation === 'read_controller_state') details = snapshot();
    else if (message.operation === 'start_launched_session') details = {session_id: 'accepted'};
    else if (message.operation === 'read_storage_sessions') details = {sessions: [], capacity: null};
    else if (message.operation === 'list_artifact_destinations') {
      if (unavailable) {status = 'failed'; error = 'Destination readback unavailable';}
      else details = {storage_id: 'storage', default_destination_id: 'default', destinations};
    } else if (message.operation === 'register_artifact_destination') {
      submissions.push(message);
      if (uncertain) {status = 'uncertain'; error = 'Communication outcome unconfirmed';}
      else if (message.parameters.root === '/invalid') {status = 'failed'; error = 'Directory is not verified usable';}
      else destinations.push({...message.parameters, enabled: true, validation: {status: 'unverified'}});
    } else if (message.operation === 'update_artifact_destination') {
      submissions.push(message);
      const entry = destinations.find(item => item.destination_id === message.parameters.destination_id);
      if (message.parameters.remove && entry.destination_id === 'other') {status = 'failed'; error = 'Retained Session bindings require this destination';}
      else if (message.parameters.remove) destinations.splice(destinations.indexOf(entry), 1);
      else entry.enabled = message.parameters.enabled;
    } else if (message.operation === 'launch_session') {
      submissions.push(message);
      if (rejectLaunch) { status = 'failed'; error = 'Scientific destination admission could not be confirmed'; }
      else { configuration = {...message.parameters.config_parameters, session_id: 'accepted'}; details = {session_id: 'accepted'}; }
    } else if (message.operation === 'read_operation_outcome') details = {status: 'uncertain', result: null};
    else throw new Error(`Unexpected operation ${message.operation}`);
    route.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'instance', result: {status, error, outcome: {details}}}));
  });
  route.send(JSON.stringify({type: 'connected', browser_id: 'browser'}));
});
const section = name => page.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
const admin = async () => {
  await section('services'); await page.locator('[data-mode="administrator"]').click();
  await page.locator('[data-administrator-entry]').fill('Alice'); await page.locator('[data-danger-enter]').click(); await section('storage');
};
const register = async root => {
  await page.locator('[data-destination-register]').click();
  const form = page.locator('dialog[open] form');
  assert.equal(await form.locator('[name="administrator"]').inputValue(), 'Alice');
  await form.locator('[name="name"]').fill('Approved extra disk');
  await form.locator('[name="root"]').fill(root);
  await form.locator('[type="submit"]').click();
};
try {
  await page.goto(process.env.MICEBALL_DESTINATION_ORIGIN);
  await page.locator('#artifact-destination option[value="default"]').waitFor({state: 'attached'});
  assert.equal(await page.locator('#artifact-destination').inputValue(), 'default');
  assert.equal(await page.locator('#artifact-destination option[value="missing"]').evaluate(option => option.disabled), true);
  assert.match(await page.locator('#artifact-destination-info').innerText(), /unverified/);
  assert.equal(await page.locator('[data-destination-register]').count(), 0);
  await page.selectOption('#artifact-destination', 'other');
  await section('session'); await section('setup');
  assert.equal(await page.locator('#artifact-destination').inputValue(), 'other');
  await admin();
  assert.match(await page.locator('.artifact-destinations').innerText(), /Installation default/);
  await page.locator('[data-destination-toggle="other"]').click();
  assert.equal(await page.locator('dialog[open] [name="administrator"]').inputValue(), 'Alice');
  await page.locator('dialog[open] [type="submit"]').click();
  await page.locator('dialog[open]').waitFor({state: 'hidden'});
  await section('setup');
  assert.equal(await page.locator('#artifact-destination').inputValue(), 'other');
  assert.match(await page.locator('#artifact-destination-info').innerText(), /Disabled/);
  await page.selectOption('#artifact-destination', 'default');
  await section('storage');
  await page.locator('[data-destination-remove="other"]').click();
  assert.equal(await page.locator('dialog[open] [name="administrator"]').inputValue(), 'Alice');
  await page.locator('dialog[open] [type="submit"]').click();
  await page.locator('[data-destination-dialog-status]').filter({hasText: 'Retained Session'}).waitFor();
  await page.locator('[data-destination-cancel]').click();
  await page.locator('[data-destination-refresh]').click();
  await register('/invalid');
  await page.locator('[data-destination-dialog-status]').filter({hasText: 'not verified usable'}).waitFor();
  await page.locator('[data-destination-cancel]').click();
  await page.locator('[data-destination-refresh]').click();
  await register('/approved');
  await page.locator('dialog[open]').waitFor({state: 'hidden'});
  assert.equal(submissions.filter(item => item.operation === 'register_artifact_destination').at(-1).parameters.administrator_mode, true);
  const extraId = destinations.at(-1).destination_id;
  await page.locator(`[data-destination-remove="${extraId}"]`).click();
  assert.equal(await page.locator('dialog[open] [name="administrator"]').inputValue(), 'Alice');
  await page.locator('dialog[open] [type="submit"]').click();
  await page.locator('dialog[open]').waitFor({state: 'hidden'});
  assert.equal(destinations.some(entry => entry.destination_id === extraId), false);
  for (const theme of ['light', 'dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
    for (const width of [1440, 760]) {
      await page.setViewportSize({width, height: 850});
      await section('storage');
      assert.equal(await page.locator('[data-destination-register]').isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await mkdir(process.env.MICEBALL_DESTINATION_EVIDENCE, {recursive: true});
      await page.screenshot({path: `${process.env.MICEBALL_DESTINATION_EVIDENCE}/destinations-${theme}-${width}.png`, fullPage: true});
      await section('setup');
      assert.equal(await page.locator('#artifact-destination').isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.locator('#artifact-destination').scrollIntoViewIfNeeded();
      await page.screenshot({path: `${process.env.MICEBALL_DESTINATION_EVIDENCE}/destination-setup-${theme}-${width}.png`});
    }
  }
  await section('setup');
  await page.locator('[data-open-setup]').click();
  await page.locator('.session-identity-grid textarea[data-configuration-string]').fill('Destination Session');
  await page.locator('.launch-session-demo').click();
  await page.locator('#activity-history').filter({hasText: 'could not be confirmed'}).waitFor({state: 'attached'});
  assert.equal(configuration, null);
  assert.equal(await page.locator('#artifact-destination').inputValue(), 'default');
  rejectLaunch = false;
  await page.locator('.launch-session-demo').click();
  await section('setup');
  await page.locator('#artifact-destination-info').filter({hasText: 'Session destination: Installation default'}).waitFor();
  assert.equal(await page.locator('#artifact-destination-info').evaluate(element => getComputedStyle(element).fontWeight), '400');
  assert.equal(await page.locator('#artifact-destination').isDisabled(), true);
  assert.equal(configuration.storage_location, 'default');
  assert.equal(configuration.session_parameters.name, 'Destination Session');
  await section('storage'); uncertain = true;
  await register('/uncertain');
  await page.locator('[data-destination-dialog-status]').filter({hasText: 'could not be confirmed'}).waitFor();
  await page.locator('[data-destination-cancel]').click();
  await section('services');
  await page.locator('#activity-history').evaluate(details => details.open = true);
  assert.match(await page.locator('#activity-history').innerText(), /Scientific destination registered|Scientific destination updated/);
  assert.match(await page.locator('#activity-history').innerText(), /could not be confirmed/);
  unavailable = true; await section('setup'); await page.getByRole('button', {name: 'Refresh destinations', exact: true}).click();
  await page.locator('#artifact-destination-info').filter({hasText: 'availability unconfirmed'}).waitFor();
  assert.equal(await page.locator('#artifact-destination').inputValue(), 'default');
  assert.deepEqual(errors, []);
  console.log('PASS: approved selection, management/refusals, fixed accepted identity, Activity History, both themes and narrow rendering (controlled transport).');
} catch (error) { console.error(errors); console.error(await page.locator('#artifact-destination').evaluate(select => select.outerHTML)); throw error; }
finally { await browser.close(); }
