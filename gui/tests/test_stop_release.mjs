import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const scenarios = ['success', 'pending-stop', 'pending-release', 'release-readback-unconfirmed', 'stop-failed', 'stop-uncertain', 'release-failed',
  'release-uncertain', 'control-loss', 'takeover', 'replacement', 'session-mismatch', 'disconnect', 'terminal-reconnect'];
try {
  for (const scenario of scenarios) {
    const page = await browser.newPage();
    const requests = [], errors = [];
    let sid = 'stopped-session', phase = scenario === 'terminal-reconnect' ? 'completed' : 'running';
    let instance = 'owner', generation = 1, controlling = true, retry = false;
    const configuration = () => sid ? {session_id: sid, protocol_reference: null, session_parameters: {},
      selected_devices: [], expected_runtime_participants: []} : null;
    const snapshot = () => ({controller_id: 'controller', instance_id: instance,
      control: {controlling, generation}, status: {session_id: sid, session_state: phase,
        active_experiment_id: null, experiment_lifecycle_evidence: []}, configuration: configuration(),
      configured_nodes: [], configured_services: [], pending_operations: [], experiments: [],
      closeout: {last_reconciliation: {preservation_confirmed: false, unresolved: [{reason: 'Historical archive warning'}]}}});
    await page.routeWebSocket('**/ws', route => {
      const reply = (request, status, details = {}, error = '') => route.send(JSON.stringify({type: 'result',
        id: request.id, instance_id: instance, result: {request_id: `browser-${request.id}`, status, error, outcome: {details}}}));
      route.onMessage(raw => {
        const request = JSON.parse(raw);
        if (replyArtifactDestinations(route, request)) return;
        requests.push(request);
        if (request.operation === 'read_controller_state') return reply(request, 'succeeded', snapshot());
        if (request.operation === 'read_operation_outcome') {
          if (scenario === 'pending-release') { sid = null; phase = null; }
          return reply(request, 'succeeded', {
          status: scenario.includes('uncertain') ? 'uncertain' : 'succeeded',
          result: {status: 'succeeded', outcome: {details: {session_id: 'stopped-session'}}}});
        }
        if (request.operation === 'normal_stop_session') {
          assert.equal(request.session_id, 'stopped-session');
          if (scenario === 'stop-failed') return reply(request, 'failed', {}, 'Owner preservation refused');
          phase = 'completed';
          if (scenario === 'control-loss') controlling = false;
          if (scenario === 'takeover') generation++;
          if (scenario === 'replacement') instance = 'replacement';
          if (scenario === 'session-mismatch') sid = 'other-session';
          if (scenario === 'disconnect') { route.close(); return; }
          return reply(request, scenario === 'stop-uncertain' ? 'uncertain' : scenario === 'pending-stop' ? 'pending' : 'succeeded',
            {session_id: 'stopped-session'});
        }
        if (request.operation === 'release_session') {
          assert.equal(request.session_id, 'stopped-session');
          if (!retry && scenario === 'release-failed') return reply(request, 'failed', {}, 'Owner handoff remains unconfirmed');
          if (scenario === 'release-uncertain') return reply(request, 'uncertain', {}, 'Release acknowledgment unavailable');
          if (scenario === 'pending-release') return reply(request, 'pending');
          if (scenario === 'release-readback-unconfirmed') return reply(request, 'succeeded', {session_id: sid});
          sid = null; phase = null;
          return reply(request, 'succeeded', {session_id: 'stopped-session'});
        }
        throw new Error(`Unexpected operation ${request.operation}`);
      });
      route.send(JSON.stringify({type: 'connected', browser_id: 'stop-browser'}));
    });
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(process.env.MICEBALL_STOP_ORIGIN);
      await page.locator('html[data-control-mode="controlling"]').waitFor();
      await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
      if (scenario !== 'terminal-reconnect') {
        await page.locator('[data-stop-session]').click();
        await page.locator('[data-confirm-stop]').evaluate(button => { button.click(); button.click(); });
      }
      const shouldRelease = ['success', 'pending-stop', 'pending-release', 'release-readback-unconfirmed', 'release-failed', 'release-uncertain'].includes(scenario);
      if (shouldRelease) {
        for (let i = 0; i < 100 && !requests.some(r => r.operation === 'release_session'); i++) await page.waitForTimeout(60);
      } else await page.waitForTimeout(1500);
      assert.equal(requests.filter(r => r.operation === 'normal_stop_session').length, scenario === 'terminal-reconnect' ? 0 : 1, scenario);
      assert.equal(requests.filter(r => r.operation === 'release_session').length, shouldRelease ? 1 : 0, scenario);
      if (['success', 'pending-stop', 'pending-release'].includes(scenario)) await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
      if (scenario === 'release-readback-unconfirmed') {
        await page.locator('[data-session-closeout-feedback]').filter({hasText: 'Released Session state is unconfirmed'}).waitFor();
        assert.equal(await page.locator('.launch-session-demo').isDisabled(), true);
      }
      if (scenario === 'disconnect') {
        await page.reload();
        await page.locator('html[data-control-mode="controlling"]').waitFor();
        await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'session'})));
        await page.locator('[data-release-session]:enabled').waitFor();
        assert.equal(requests.filter(r => r.operation === 'release_session').length, 0, 'Reconnect must not resume Stop continuation');
        await page.locator('[data-release-session]').click(); await page.locator('[data-confirm-stop]').click();
        await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
        assert.equal(requests.filter(r => r.operation === 'normal_stop_session').length, 1);
      }
      if (scenario === 'release-failed') {
        await page.locator('[data-session-closeout-feedback]').filter({hasText: 'Owner handoff remains unconfirmed'}).waitFor();
        assert.equal(await page.locator('[data-stop-session]').isDisabled(), true);
        retry = true;
        await page.locator('[data-release-session]').click(); await page.locator('[data-confirm-stop]').click();
        await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
        assert.equal(requests.filter(r => r.operation === 'normal_stop_session').length, 1);
        assert.equal(requests.filter(r => r.operation === 'release_session').length, 2);
      }
      if (scenario === 'terminal-reconnect') {
        assert.equal(await page.locator('[data-release-session]').innerText(), 'Retry Release');
        await page.locator('[data-release-session]').click(); await page.locator('[data-confirm-stop]').click();
        await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
        assert.equal(requests.filter(r => r.operation === 'normal_stop_session').length, 0);
      }
      if (scenario === 'stop-failed') assert.match(await page.locator('#activity-history').textContent(), /Owner preservation refused/);
      if (scenario.endsWith('uncertain')) assert.equal(await page.locator('.launch-session-demo').isDisabled(), true);
      assert.deepEqual(errors, [], scenario);
    } finally { await page.close(); }
  }
  console.log(`PASS: ${scenarios.length} production-browser Stop/release scenarios`);
} finally { await browser.close(); }
