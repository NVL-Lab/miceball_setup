import {returnFromParameters} from './parameter_navigation.mjs';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
import assert from 'node:assert/strict';

// Developer browser checks of public controls with controlled transport outcomes.
export async function verifyActivityHistory(browser, origin, fixture, section, directory) {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const requests = [], errors = [];
  let controlling = false, denyTakeover = true, accepted = null, sessionState = null;
  let launchMode = 'failed', resolveLaunch = false, pendingLaunch = null;
  let descriptor = null, activeExperiment = null, lifecycle = [];
  page.on('pageerror', error => errors.push(error.message));
  const snapshot = () => ({controller_id: 'activity', instance_id: 'activity-owner',
    control: {controlling, generation: 1}, configuration: accepted,
    status: {session_id: accepted ? 'activity-session' : null, session_state: sessionState,
      active_experiment_id: activeExperiment, experiment_lifecycle_evidence: lifecycle},
    configured_nodes: ['node'], configured_services: [], experiments: descriptor ? [descriptor] : [], pending_operations: []});
  const accept = parameters => { accepted = {...fixture.snapshots[0].configuration, ...parameters.config_parameters, session_id: 'activity-session'}; sessionState = 'initialized'; };
  const result = (route, message, status, details = {}, error) => route.send(JSON.stringify({type: 'result', id: message.id,
    instance_id: 'activity-owner', result: {request_id: `activity-browser-${message.id}`, status, error, outcome: {details}}}));
  await page.routeWebSocket('**/ws', route => {
    route.onMessage(raw => {
      const message = JSON.parse(raw); if (replyArtifactDestinations(route, message)) return;
      if (message.operation === 'read_controller_state') return result(route, message, 'succeeded', snapshot());
      if (message.operation === 'read_operation_outcome') {
        if (pendingLaunch && resolveLaunch) {
          accept(pendingLaunch.parameters);
          return result(route, message, 'succeeded', {status: 'succeeded', result: {status: 'succeeded', outcome: {details: {session_id: 'activity-session'}}}});
        }
        return result(route, message, 'succeeded', {status: pendingLaunch ? 'pending' : 'unknown', result: null});
      }
      requests.push(message);
      switch (message.operation) {
        case 'take_browser_control':
          if (denyTakeover) return result(route, message, 'rejected', {}, 'Control request denied by Controller.');
          controlling = true; break;
        case 'view_only': controlling = false; break;
        case 'get_node_inventory': return result(route, message, 'succeeded', fixture.inventory);
        case 'launch_session':
          if (launchMode === 'failed') return result(route, message, 'failed', {}, 'Required synchronization configuration is missing.');
          if (launchMode === 'rejected') return result(route, message, 'rejected', {}, 'Launch configuration rejected.');
          if (launchMode === 'backend-rejected') return route.send(JSON.stringify({type: 'result', id: message.id, status: 'rejected', error: 'Launch configuration was not accepted by the GUI backend.'}));
          if (launchMode === 'uncertain') return result(route, message, 'uncertain', {}, 'Controller response timed out.');
          if (launchMode === 'pending') { pendingLaunch = message; return result(route, message, 'pending'); }
          accept(message.parameters); return result(route, message, 'succeeded', {session_id: 'activity-session'});
        case 'start_launched_session': sessionState = 'running'; break;
        case 'start_launched_experiment':
          descriptor = {experiment_id: message.parameters.experiment_id, configuration: message.parameters.configuration, scientific_outputs: message.parameters.scientific_outputs};
          activeExperiment = descriptor.experiment_id;
          lifecycle = [{experiment_id: activeExperiment, event_type: 'experiment_start', sequence: 1, session_time_s: 0}]; break;
        case 'stop_launched_experiment':
          lifecycle.push({experiment_id: activeExperiment, event_type: 'experiment_stop', sequence: 2, session_time_s: 1});
          activeExperiment = null; break;
        case 'normal_stop_session': sessionState = 'completed'; break;
        case 'release_session': accepted = null; sessionState = null; descriptor = null; lifecycle = []; break;
        default: throw new Error(`Unexpected activity operation ${message.operation}`);
      }
      result(route, message, 'succeeded', {});
    });
    route.send(JSON.stringify({type: 'connected', browser_id: 'activity-browser'}));
  });
  const history = page.locator('#activity-history');
  const latest = () => history.locator('[data-activity]').last();
  const showHistory = async () => { await section(page, 'services'); await history.evaluate(node => node.open = true); };
  try {
    await page.goto(origin); await page.locator('html[data-control-mode="view-only"]').waitFor();
    assert.equal(await history.count(), 1, 'One unified Activity History must be present');
    await page.locator('#take-over').click(); await showHistory();
    await latest().filter({hasText: /Control.*denied|Control.*could not/}).waitFor();
    denyTakeover = false; await page.locator('#take-over').click();
    await latest().filter({hasText: 'Control acquired.'}).waitFor();
    const count = await history.locator('[data-activity]').count();
    await page.waitForTimeout(2200);
    assert.equal(await history.locator('[data-activity]').count(), count, 'Polling is not activity');
    await section(page, 'setup');
    const number = page.locator('.session-identity-grid input[type="number"]');
    await number.fill(''); await number.pressSequentially('1e999');
    assert.equal(await number.evaluate(input => input.validity.badInput), true);
    await page.locator('.launch-session-demo').click(); await showHistory();
    await latest().filter({hasText: /Invalid Session number/}).waitFor();
    assert.equal(await latest().getAttribute('data-status'), 'failed');
    assert.equal(requests.filter(entry => entry.operation === 'launch_session').length, 0);
    await section(page, 'session');
    assert.match(await page.locator('.session-information').innerText(), /Local preparation/);
    await section(page, 'setup'); await page.locator('[data-open-setup]').click();
    await number.fill('1');
    await page.locator('#load-inventory').click();
    await page.locator('#inventory-status').filter({hasText: 'inventory confirmed'}).waitFor();
    await page.locator('#session-device-list input').first().check();
    await page.locator('.launch-session-demo').click(); await showHistory();
    await latest().filter({hasText: /synchronization configuration is missing/}).waitFor();
    launchMode = 'rejected'; await section(page, 'setup'); await page.locator('.launch-session-demo').click(); await showHistory();
    await latest().filter({hasText: /Session launch was rejected by Controller/}).waitFor();
    launchMode = 'backend-rejected'; await section(page, 'setup'); await page.locator('.launch-session-demo').click(); await showHistory();
    await latest().filter({hasText: /not accepted for submission/}).waitFor();
    launchMode = 'succeeded'; await section(page, 'setup'); await page.locator('.launch-session-demo').click();
    await page.locator('#panel-session:not([hidden])').waitFor();
    assert.match(await page.locator('.session-information').innerText(), /Controller-confirmed/);
    await page.locator('[data-start-session]:disabled').waitFor();
    assert.equal(requests.filter(entry => entry.operation === 'start_launched_session').length, 1);
    await page.locator('[data-prepare-free-operation]').click();
    assert.equal(await page.locator('.experiment-additional-devices').evaluate(element => element.open), true,
      'Required device selection expands automatically');
    await page.locator('[data-session-experiment-device]').first().check();
    await page.locator('[data-session-navigate="parameters"]').click();
    await page.locator('#experiment-duration').fill('2');
    await page.locator('[data-framework-field="experimentId"]').fill('activity-experiment');
    await page.locator('[data-framework-field="preservationBudget"]').fill('1000000');
    await page.locator('[data-recording-budget]').fill('100000');
    await returnFromParameters(page); await page.locator('[data-launch-experiment]').click();
    await page.locator('#panel-experiment:not([hidden])').waitFor();
    await page.locator('[data-stop-experiment]').click();
    const beforeDismiss = await history.locator('[data-activity]').count();
    await page.keyboard.press('Escape');
    assert.equal(await history.locator('[data-activity]').count(), beforeDismiss);
    await page.locator('[data-stop-experiment]').click(); await page.locator('[data-confirm-stop]').click();
    await showHistory(); await latest().filter({hasText: 'Experiment stopped.'}).waitFor();
    for (const text of ['Session launched successfully.', 'Session started.', 'Experiment started.', 'Experiment prepared locally.']) assert.ok((await history.innerText()).includes(text));
    await section(page, 'session'); await page.locator('[data-stop-session]').click(); await page.locator('[data-confirm-stop]').click();
    await page.locator('[data-release-session]:enabled').waitFor();
    await page.locator('[data-release-session]').click(); await page.locator('[data-confirm-stop]').click();
    await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
    // A presentation failure after a received success cannot replace that success.
    await page.evaluate(() => {
      const native = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
      const previous = (document.querySelector('[data-activity-records]').innerHTML.match(/Session launched successfully\./g) || []).length;
      Object.defineProperty(Element.prototype, 'innerHTML', {...native, set(value) {
        if (this.hasAttribute('data-activity-records') && (String(value).match(/Session launched successfully\./g) || []).length > previous) {
          Object.defineProperty(Element.prototype, 'innerHTML', native);
          throw new Error('Injected one-time feedback rendering failure.');
        }
        native.set.call(this, value);
      }});
    });
    await section(page, 'setup'); await page.locator('.launch-session-demo').click();
    await page.locator('#activity-history [data-activity][data-status="succeeded"]').last().filter({hasText: 'Session launched successfully.'}).waitFor({state: 'attached'});
    await section(page, 'session');
    assert.match(await page.locator('.session-information').innerText(), /Controller-confirmed/);
    await page.locator('[data-stop-session]').click(); await page.locator('[data-confirm-stop]').click();
    await page.locator('[data-release-session]:enabled').waitFor();
    await page.locator('[data-release-session]').click(); await page.locator('[data-confirm-stop]').click();
    await page.locator('.launch-session-demo:enabled').waitFor({state: 'attached'});
    // A synchronous browser send failure is before Controller submission.
    await page.evaluate(() => {
      const native = WebSocket.prototype.send;
      WebSocket.prototype.send = function(data) {
        if (JSON.parse(data).operation === 'view_only') { WebSocket.prototype.send = native; throw new Error('Connection changed before submission.'); }
        return native.call(this, data);
      };
    });
    await page.locator('#view-only').click(); await showHistory();
    await latest().filter({hasText: /before submission/}).waitFor();
    launchMode = 'uncertain'; await section(page, 'setup'); await page.locator('.launch-session-demo').click(); await showHistory();
    await latest().filter({hasText: /Session launch could not be confirmed/}).waitFor();
    const launches = requests.filter(entry => entry.operation === 'launch_session').length;
    await page.waitForTimeout(2200);
    assert.equal(requests.filter(entry => entry.operation === 'launch_session').length, launches, 'Uncertainty never retries execution');
    launchMode = 'pending'; await section(page, 'setup'); await page.locator('.launch-session-demo').click(); await showHistory();
    await latest().filter({hasText: /Session launch.*pending/i}).waitFor();
    await page.locator('[data-start-session]').evaluate(button => button.dispatchEvent(new MouseEvent('click', {bubbles: true})));
    await latest().filter({hasText: /not sent|in progress|pending/i}).waitFor();
    resolveLaunch = true;
    await page.locator('#panel-session:not([hidden])').waitFor();
    await showHistory();
    assert.equal(await page.locator('#operation-results, #control-activity-history').count(), 0);
    assert.doesNotMatch(await history.innerText(), /request_id|instance_id|take_browser_control|launch_session|"status"/);
    assert.ok(await history.locator('time').count());
    assert.match(await history.innerText(), /Browser-local observation/);
    for (const theme of ['light', 'dark']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
      await page.setViewportSize({width: 800, height: 900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({path: `${directory}/activity-history-${theme}.png`, fullPage: true});
    }
    await page.reload(); await page.locator('html[data-control-mode]').waitFor(); await showHistory();
    assert.equal(await history.locator('[data-activity]').count(), 0, 'Page reload has no history persistence requirement');
    assert.deepEqual(errors, []);
    console.log('PASS: unified page-local Activity History; local/Controller/submission failures, pending reconciliation, takeover, Session/Experiment workflow, guards, cancellation, concise timestamps and both themes');
  } finally { await page.close(); }
}
