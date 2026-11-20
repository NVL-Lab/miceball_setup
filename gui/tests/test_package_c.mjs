import assert from 'node:assert/strict';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';

// Framework-produced inventory, production presenters, controlled transport outcomes.
export async function verifyPackageC(browser, origin, initial, section, directory) {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const requests = [], errors = [];
  let inventory = structuredClone(initial), result = 'succeeded', controlling = true, connection;
  let heldInventory = null, holdReadback = false;
  const snapshot = () => ({controller_id: 'admin-controller', instance_id: 'admin-instance',
    control: {controlling, generation: 1}, configured_nodes: ['node'], configured_services: [],
    configuration: null, experiments: [], pending_operations: [],
    status: {session_id: null, session_state: null, active_experiment_id: null, experiment_lifecycle_evidence: []}});
  const reply = (route, request, status, details = {}, error = '') => route.send(JSON.stringify({type: 'result',
    id: request.id, instance_id: 'admin-instance', result: {request_id: request.id, status, error, outcome: {details}}}));
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/ws', route => {
    connection = route;
    route.onMessage(raw => {
      const request = JSON.parse(raw);
      if (replyArtifactDestinations(route, request)) return;
      requests.push(request);
      if (request.operation === 'read_controller_state') return reply(route, request, 'succeeded', snapshot());
      if (request.operation === 'read_synchronization_status') return reply(route, request, 'succeeded', {current: false, timing: null, reason: 'Unavailable'});
      if (request.operation === 'get_node_inventory') {
        if (holdReadback) { heldInventory = {route, request}; return; }
        return reply(route, request, 'succeeded', inventory);
      }
      if (request.operation === 'read_operation_outcome') return reply(route, request, 'succeeded', {status: 'unknown', result: null});
      if (request.operation === 'update_device_configuration') {
        const values = request.parameters;
        assert.equal(request.session_id, null);
        assert.equal(values.node_id, 'node'); assert.equal(values.device_id, 'camera');
        assert.equal(values.authorized, true); assert.equal(values.administrator_id, 'Lab Operator');
        if (values.expected_revision !== inventory.administrative_configuration.revision)
          return reply(route, request, 'rejected', {}, 'Saved revision changed; refresh and review');
        if (result !== 'rejected') {
          inventory.administrative_configuration.saved.camera = structuredClone(values.parameters);
          inventory.administrative_configuration.revision = 'b'.repeat(64);
        }
        return reply(route, request, result, {}, result === 'succeeded' ? '' : 'Publication not confirmed');
      }
      if (request.operation === 'view_only') { controlling = false; return reply(route, request, 'succeeded'); }
      throw new Error(`Unexpected administrative operation ${request.operation}`);
    });
    route.send(JSON.stringify({type: 'connected', browser_id: 'admin-browser'}));
  });
  const wait = async predicate => {
    for (let i = 0; i < 100 && !predicate(); i++) await page.waitForTimeout(50);
    assert.ok(predicate(), 'Expected configuration workflow did not complete');
  };
  const refresh = async () => {
    await section(page, 'setup'); await page.locator('[data-open-setup]').click();
    await page.locator('#load-inventory').click();
    await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
    await section(page, 'parameters');
  };
  try {
    await page.goto(origin);
    await page.locator('html[data-control-mode="controlling"]').waitFor();
    await refresh();
    assert.equal(await page.locator('[data-administrative-device]').count(), 0);
    await page.locator('[data-mode="administrator"]').click();
    await page.locator('[data-administrator-entry]').fill('Lab Operator');
    await page.locator('[data-danger-enter]').click();
    await section(page, 'parameters');
    const form = page.locator('[data-administrative-device]');
    const input = form.getByRole('spinbutton', {name: 'frames_per_collect', exact: true});
    const save = form.getByRole('button', {name: 'Save device settings', exact: true});
    assert.equal(await input.inputValue(), '2');
    assert.match(await form.innerText(), /Saved and loaded values match/);
    await input.fill('3');
    const originalRevision = await form.getAttribute('data-revision');
    inventory.administrative_configuration.revision = 'a'.repeat(64);
    inventory.administrative_configuration.saved.camera.frames_per_collect = 4;
    await refresh();
    assert.equal(await input.inputValue(), '3');
    assert.equal(await form.getAttribute('data-revision'), originalRevision, 'Refresh must not rebase a dirty draft');
    await save.click();
    await form.locator('[data-administrative-feedback]').filter({hasText: 'Saved revision changed'}).waitFor();
    assert.equal(requests.filter(item => item.operation === 'update_device_configuration').length, 1);
    assert.equal(await input.inputValue(), '3');
    await form.locator('[data-administrative-reload]').click();
    assert.equal(await input.inputValue(), '4');
    await input.fill('5'); await save.click();
    await form.locator('[data-administrative-feedback]').filter({hasText: 'Saved durably'}).waitFor();
    assert.match(await form.innerText(), /Normal AcquisitionNode restart required/);
    assert.match(await form.innerText(), /Loaded:.*2/);
    assert.equal(await input.inputValue(), '5');
    result = 'uncertain'; holdReadback = true;
    await input.fill('6'); await save.click();
    await wait(() => heldInventory !== null);
    assert.equal(await save.isDisabled(), true, 'Uncertainty must not permit replay before readback');
    const count = requests.filter(item => item.operation === 'update_device_configuration').length;
    await page.waitForTimeout(300);
    assert.equal(requests.filter(item => item.operation === 'update_device_configuration').length, count);
    holdReadback = false;
    reply(heldInventory.route, heldInventory.request, 'succeeded', inventory); heldInventory = null;
    await form.locator('[data-administrative-feedback]').filter({hasText: 'uncertain'}).waitFor();
    assert.equal(await input.inputValue(), '6');
    assert.equal(await save.isEnabled(), true, 'Fresh readback permits a new explicit attempt');
    await form.locator('[data-administrative-reload]').click();
    result = 'succeeded'; await input.fill('7'); await save.click();
    await form.locator('[data-administrative-feedback]').filter({hasText: 'Saved durably'}).waitFor();
    await page.screenshot({path: `${directory}/package-c-administrative-settings.png`, fullPage: true});
    await page.locator('#view-only').click();
    await page.locator('html[data-control-mode="view-only"]').waitFor();
    assert.equal(await input.isDisabled(), true);
    await section(page, 'services');
    assert.match(await page.locator('#activity-history').textContent(), /could not be confirmed.*No automatic retry/i);
    assert.deepEqual(errors, []);
    connection.close();
    console.log('PASS: administrator-only fields; stale dirty revision; refusal; explicit reload; durable save/restart feedback; uncertainty readback/no replay; explicit retry; View Only/history');
  } finally { await page.close(); }
}
