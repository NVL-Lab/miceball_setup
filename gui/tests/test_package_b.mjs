import assert from 'node:assert/strict';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';

// Production presenters with framework-produced configuration/inventory and controlled outcomes.
export async function verifyPackageB(browser, origin, fixture, inventories, section, directory) {
  const wait = async (page, predicate) => {
    for (let i = 0; i < 100; i++) {
      if (predicate()) return;
      await page.waitForTimeout(60);
    }
    assert.ok(predicate(), 'Expected public workflow did not complete');
  };
  for (const scenario of ['success', 'launch-rejected', 'start-rejected', 'start-uncertain',
    'launch-uncertain', 'pending', 'control-loss', 'takeover', 'replacement', 'disconnect',
    'busy-feedback', 'pending-feedback', 'uncertain-feedback']) {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const requests = [], errors = [];
    let accepted = null, sessionState = null, instance = 'package-owner', generation = 1;
    let controlling = true, pending = null, launchSeen = false;
    let inventory = structuredClone(inventories[0]);
    const snapshot = () => ({controller_id: 'package-controller', instance_id: instance,
      control: {controlling, generation}, configuration: accepted,
      status: {session_id: accepted?.session_id || null, session_state: sessionState,
        active_experiment_id: null, experiment_lifecycle_evidence: []},
      configured_nodes: ['node'], configured_services: [], experiments: [], pending_operations: []});
    const reply = (route, request, status, details = {}, error = '') => route.send(JSON.stringify({
      type: 'result', id: request.id, instance_id: instance, result: {
        request_id: `package-browser-${request.id}`, status, error, outcome: {details}}}));
    const accept = request => {
      accepted = {...request.parameters.config_parameters,
        session_id: 'package-session', selected_devices: inventories[0].devices,
        expected_runtime_participants: [{component_type: 'acquisition_node', component_id: 'node'}]};
      sessionState = 'initialized';
    };
    page.on('pageerror', error => errors.push(error.message));
    await page.routeWebSocket('**/ws', route => {
      route.onMessage(raw => {
        const request = JSON.parse(raw);
        if (replyArtifactDestinations(route, request)) return;
        requests.push(request);
        if (request.operation === 'read_controller_state') return reply(route, request, 'succeeded', snapshot());
        if (request.operation === 'get_node_inventory') return reply(route, request, 'succeeded', inventory);
        if (request.operation === 'read_operation_outcome') {
          if (scenario === 'pending-feedback' || scenario === 'uncertain-feedback')
            return reply(route, request, 'succeeded', {status: scenario === 'pending-feedback' ? 'pending' : 'uncertain', result: null});
          if (pending) {
            accept(pending);
            const details = {status: 'succeeded', result: {status: 'succeeded',
              request_id: request.parameters.target_request_id, outcome: {details: {session_id: 'package-session'}}}};
            return reply(route, request, 'succeeded', details);
          }
          return reply(route, request, 'succeeded', {status: 'unknown', result: null});
        }
        if (request.operation === 'launch_session') {
          launchSeen = true;
          if (scenario === 'busy-feedback') return;
          if (scenario === 'pending-feedback' || scenario === 'uncertain-feedback')
            return reply(route, request, scenario === 'pending-feedback' ? 'pending' : 'uncertain');
          if (scenario === 'launch-rejected') return reply(route, request, 'rejected', {}, 'Owner refused launch');
          if (scenario === 'pending' || scenario === 'launch-uncertain') {
            pending = request;
            return reply(route, request, scenario === 'pending' ? 'pending' : 'uncertain');
          }
          accept(request);
          if (scenario === 'control-loss') controlling = false;
          if (scenario === 'takeover') generation++;
          if (scenario === 'replacement') instance = 'replacement-owner';
          if (scenario === 'disconnect') { route.close(); return; }
          return reply(route, request, 'succeeded', {session_id: 'package-session'});
        }
        if (request.operation === 'start_launched_session') {
          assert.equal(request.session_id, 'package-session');
          if (scenario === 'start-rejected') return reply(route, request, 'rejected', {}, 'Owner refused start');
          if (scenario === 'start-uncertain') return reply(route, request, 'uncertain', {}, 'Start unconfirmed');
          sessionState = 'running';
          return reply(route, request, 'succeeded', {session_state: 'running'});
        }
        if (request.operation === 'start_launched_experiment')
          return reply(route, request, 'rejected', {}, 'Controlled Experiment rejection');
        throw new Error(`Unexpected Package B operation ${request.operation}`);
      });
      route.send(JSON.stringify({type: 'connected', browser_id: 'package-browser'}));
    });
    try {
      await page.goto(origin);
      await page.locator('html[data-control-mode="controlling"]').waitFor();
      assert.equal(await page.locator('.topbar__eyebrow').textContent(), 'Connected Framework');
      await page.locator('[data-open-setup]').click();
      await page.locator('#load-inventory').click();
      await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
      await page.locator('#session-device-list input').first().check();
      // Dispatch two immediate actions. Only the original action may allocate a Session.
      await page.locator('.launch-session-demo').evaluate(button => { button.click(); button.click(); });
      await wait(page, () => launchSeen);
      if (scenario.endsWith('-feedback')) {
        const text = scenario === 'busy-feedback' ? /request is in progress/
          : scenario === 'pending-feedback' ? /sequence is still pending/ : /could not be confirmed/;
        await page.locator('.launch-session-demo span').filter({hasText: text}).waitFor();
        assert.equal(await page.locator('.launch-session-demo').isDisabled(), true);
        assert.equal(requests.filter(request => request.operation === 'launch_session').length, 1);
        assert.equal(requests.filter(request => request.operation === 'start_launched_session').length, 0);
        continue;
      }
      const shouldStart = ['success', 'pending', 'start-rejected', 'start-uncertain'].includes(scenario);
      if (shouldStart) await wait(page, () => requests.some(request => request.operation === 'start_launched_session'));
      await page.waitForTimeout(2500);
      assert.equal(requests.filter(request => request.operation === 'launch_session').length, 1, scenario);
      assert.equal(requests.filter(request => request.operation === 'start_launched_session').length, shouldStart ? 1 : 0, scenario);
      if (scenario === 'start-rejected') {
        await section(page, 'session');
        assert.equal(await page.locator('[data-start-session]').isEnabled(), true);
        assert.match(await page.locator('#activity-history').innerText(), /Owner refused start/);
      }
      if (scenario === 'disconnect') assert.equal(await page.locator('.topbar__eyebrow').textContent(), 'Connected Framework');
      if (scenario !== 'success') { assert.deepEqual(errors, []); continue; }
      assert.match(await page.locator('.launch-session-demo span').textContent(), /Session already accepted/);
      await section(page, 'session');
      assert.equal(await page.locator('[data-start-session]').isDisabled(), true);
      await page.locator('[data-prepare-free-operation]').click();
      assert.match(await page.locator('.session-selected-heading').innerText(), /Configuration incomplete/);
      await page.locator('.experiment-additional-devices > summary').click();
      await page.locator('[data-session-experiment-device]').first().check();
      await page.locator('[data-session-navigate="parameters"]').click();
      const field = name => page.getByRole('spinbutton', {name, exact: true});
      // Installation values cannot be relabelled as this accepted Session's baseline.
      assert.equal(await field('frame_width').inputValue(), '');
      assert.match(await field('frame_width').locator('../..').innerText(), /Configured value unavailable/);
      inventory = structuredClone(inventories[1]);
      await section(page, 'setup'); await page.locator('[data-open-setup]').click();
      await page.locator('#load-inventory').click();
      await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
      await section(page, 'parameters');
      assert.equal(await field('frame_width').inputValue(), '800');
      assert.equal(await field('frame_height').inputValue(), '480');
      assert.equal(await field('fps').inputValue(), '');
      assert.match(await field('fps').locator('../..').innerText(), /Inherited configuration: no value requested/);
      assert.equal(await field('frames_per_collect').count(), 0, 'Administrative values are not ordinary overrides');
      await field('frame_width').fill('900');
      await field('fps').fill('30');
      await field('fps').fill('');
      await page.locator('#experiment-duration').fill('2');
      await page.locator('[data-framework-field="experimentId"]').fill('package-experiment');
      await page.locator('[data-framework-field="preservationBudget"]').fill('100000');
      await page.locator('[data-recording-budget]').fill('100000');
      await section(page, 'setup'); await page.locator('#load-inventory').click();
      await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
      await section(page, 'parameters');
      assert.equal(await field('frame_width').inputValue(), '900', 'Refresh preserves explicit draft');
      await page.locator('[data-return-session]').click(); await page.locator('[data-launch-experiment]').click();
      await wait(page, () => requests.some(request => request.operation === 'start_launched_experiment'));
      const submitted = requests.find(request => request.operation === 'start_launched_experiment');
      assert.deepEqual(submitted.parameters.configuration.device_configurations, {node: {camera: {frame_width: 900}}});
      await page.locator('[data-launch-experiment]:enabled').waitFor();
      await page.locator('[data-session-navigate="parameters"]').click();
      assert.equal(await field('frame_width').inputValue(), '900', 'Rejected command retains preparation');
      await page.locator('[data-null-parameter]').last().check();
      await page.locator('[data-return-session]').click(); await page.locator('[data-launch-experiment]').click();
      await wait(page, () => requests.filter(request => request.operation === 'start_launched_experiment').length === 2);
      assert.deepEqual(requests.filter(request => request.operation === 'start_launched_experiment').at(-1).parameters.configuration.device_configurations,
        {node: {camera: {frame_width: 900, fps: null}}});
      await page.locator('[data-launch-experiment]:enabled').waitFor();
      await page.locator('[data-session-navigate="parameters"]').click();
      await field('frame_width').fill('');
      await section(page, 'session'); await section(page, 'parameters');
      assert.equal(await field('frame_width').inputValue(), '800');
      await field('frame_width').fill('900');
      await section(page, 'session');
      await page.locator('[data-prepare-free-operation]').click();
      if (!await page.locator('.experiment-additional-devices').evaluate(element => element.open))
        await page.locator('.experiment-additional-devices > summary').click();
      await page.locator('[data-session-experiment-device]').first().check();
      await page.locator('[data-session-navigate="parameters"]').click();
      assert.equal(await field('frame_width').inputValue(), '800', 'A new occurrence inherits baseline, not previous overrides');
      await page.screenshot({path: `${directory}/package-b-parameters.png`, fullPage: true});
      assert.deepEqual(errors, []);
    } finally { await page.close(); }
  }
  const demo = await browser.newPage();
  try {
    await demo.goto(process.env.MICEBALL_DEMO_CURRENT_ORIGIN);
    assert.equal(await demo.locator('.topbar__eyebrow').textContent(), 'Demonstration — no framework operations');
    assert.equal(await demo.locator('#connection-state').count(), 0);
  } finally { await demo.close(); }
  console.log('PASS: 13 launch/interruption/eligibility scenarios; numeric clearing versus explicit empty-value request; inherited values, draft retention and independent mode identity');
}
