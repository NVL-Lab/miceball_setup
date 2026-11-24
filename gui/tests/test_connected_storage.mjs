import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const scenarios = ['success', 'empty', 'unavailable', 'source-offline', 'failed', 'incomplete', 'uncertain', 'pending', 'view-only', 'disconnect', 'multiple', 'partial-batch', 'takeover', 'recovered', 'mismatched', 'history-only'];
try {
  for (const scenario of scenarios) {
    console.log(`Storage scenario: ${scenario}`);
    const page = await browser.newPage(), requests = [], errors = [];
    let collected = false, controlling = true, original = null, recover = false;
    const record = id => ({session_id: id, experimenter_name: 'Scientist',
      accepted_session_config: {session_parameters: {name: 'Recorded <Session>', experimenter: 'Scientist'}},
      collection_status: {eligible: true, collection_available: true, lifecycle_state: 'completed'},
      experiments: [{experiment_id: 'free-1', name: 'Recorded Experiment'}],
      collection_progress: {artifact_count: 1, outcome_archived: collected},
      collection_history: collected ? [{payload: {artifact_results: [{artifact_manifest_id: 'camera-file', verification_status: 'verified'}]}}] : []});
    await page.routeWebSocket('**/ws', route => {
      const reply = (request, status, details = {}, error = '') => route.send(JSON.stringify({type: 'result', id: request.id,
        instance_id: 'owner', result: {request_id: `browser-${request.id}`, status, error, outcome: {details}}}));
      route.onMessage(raw => {
        const request = JSON.parse(raw); requests.push(request);
        if (replyArtifactDestinations(route, request)) return;
        if (request.operation === 'read_controller_state') return reply(request, 'succeeded', {controller_id: 'controller', instance_id: 'owner',
          control: {controlling, generation: 1}, status: {session_id: null, session_state: null, active_experiment_id: null},
          configuration: null,
          configured_nodes: [], configured_services: [], experiments: [], pending_operations: []});
        if (request.operation === 'view_only') { controlling = false; return reply(request, 'succeeded'); }
        if (request.operation === 'read_storage_sessions') {
          assert.equal(request.session_id, null);
          if (scenario === 'unavailable') return reply(request, 'failed', {}, 'StorageManager readback unavailable');
          return reply(request, 'succeeded', {sessions: scenario === 'empty' ? [] : ['multiple', 'partial-batch', 'takeover'].includes(scenario) ? [record('old'), record('second')] : [record('old')],
            capacity: {ready: true, destinations: [{destination: '/scientific', available_bytes: 123456, ready: true}]}});
        }
        if (request.operation === 'read_storage_session') return reply(request, 'succeeded', {...record('old'),
          nodes: {node: scenario === 'source-offline' ? {confirmed: false, reason: 'Node historical state is unavailable'}
            : {confirmed: true, inventory: {artifacts: [{manifest: {artifact_manifest_id: 'camera-file'}}]}}}});
        if (request.operation === 'collect_saved_session_artifacts_remote') {
          original = request;
          assert.equal(typeof request.parameters.evidence_id, 'string');
          assert.equal('deletion' in request.parameters, false);
          assert.equal(request.parameters.experimenter_name, 'Scientist');
          if (scenario === 'disconnect') { route.close(); return; }
          if (scenario === 'takeover') { controlling = false; return reply(request, 'failed', {}, 'Browser control changed'); }
          if (scenario === 'partial-batch' && request.session_id === 'old') return reply(request, 'failed', {}, 'First source unavailable; collection incomplete');
          if (['failed', 'incomplete', 'source-offline'].includes(scenario)) return reply(request, 'failed',
            {collection_outcome: {artifact_collection_result: {succeeded: false}}}, 'Source unavailable or collection incomplete');
          if (['uncertain', 'recovered', 'mismatched', 'history-only'].includes(scenario)) return reply(request, 'uncertain', {}, 'Collection response unconfirmed');
          collected = true;
          return reply(request, scenario === 'pending' ? 'pending' : 'succeeded', {session_id: request.session_id,
            collection_outcome: {archival_confirmed: true, artifact_collection_result: {succeeded: true}}});
        }
        if (request.operation === 'read_operation_outcome') {
          assert.equal(request.parameters.target_request_id, `browser-${original.id}`);
          assert.equal(request.parameters.instance_id, 'owner');
          const status = scenario === 'pending' || recover && ['recovered', 'mismatched'].includes(scenario) ? 'succeeded' : 'uncertain';
          return reply(request, 'succeeded', {instance_id: 'owner', status,
            result: {request_id: scenario === 'mismatched' && recover ? 'different-request' : `browser-${original.id}`,
              operation: original.operation, session_id: original.session_id, status,
              outcome: status === 'succeeded' ? {details: {collection_outcome: {archival_confirmed: true,
                collection_evidence: {evidence_id: original.parameters.evidence_id}}}} : null}});
        }
        throw new Error(`Unexpected operation ${request.operation}`);
      });
      route.send(JSON.stringify({type: 'connected', browser_id: 'storage-browser'}));
    });
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(process.env.MICEBALL_STORAGE_ORIGIN);
      await page.locator('html[data-control-mode="controlling"], html[data-control-mode="view-only"]').waitFor();
      await page.locator('#experimenter-select option[value="scientist"]').waitFor({state: 'attached'});
      await page.locator('#experimenter-select').selectOption('scientist');
      if (scenario === 'view-only') {
        await page.locator('#view-only').click();
        await page.locator('html[data-control-mode="view-only"]').waitFor();
      }
      await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'storage'})));
      await page.locator('[data-storage-live-refresh]:enabled').waitFor();
      await page.locator('[data-storage-live-refresh]').click();
      if (scenario === 'empty') {
        await page.getByText('No matching historical Sessions in the confirmed readback.').waitFor();
      } else if (scenario === 'unavailable') {
        await page.locator('[data-storage-live-feedback]').filter({hasText: 'StorageManager readback unavailable'}).waitFor();
        assert.equal(await page.locator('[data-storage-live-review]').isDisabled(), true);
      } else {
        await page.locator('[data-storage-live-add="old"]').waitFor();
        assert.match(await page.locator('[data-storage-live-capacity]').textContent(), /123456/);
        await page.locator('details[data-storage-detail="old"] summary').click();
        await page.locator('[data-storage-live-inspect="old"]').click();
        await page.locator('[data-storage-live-feedback]').filter({hasText: 'Session details received'}).waitFor();
        assert.match(await page.locator('details[data-storage-detail="old"]').textContent(), scenario === 'source-offline' ? /Node historical state is unavailable/ : /camera-file/);
        if (scenario === 'view-only') assert.equal(await page.locator('[data-storage-live-add="old"]').isDisabled(), true);
        else {
          await page.locator('[data-storage-live-add="old"]').click();
          if (['multiple', 'partial-batch', 'takeover'].includes(scenario)) await page.locator('[data-storage-live-add="second"]').click();
          assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 0);
          await page.locator('[data-storage-live-review]').click();
          await page.locator('[data-storage-live-confirm]').evaluate(button => { button.click(); button.click(); });
          await page.waitForFunction(() => document.querySelector('[data-storage-live-feedback]').textContent.match(/outcome confirmed|incomplete|unconfirmed|Remaining|context changed/));
          if (scenario !== 'disconnect') await page.locator('[data-storage-live-refresh]:enabled').waitFor();
          const collections = requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote');
          assert.equal(collections.length, ['multiple', 'partial-batch'].includes(scenario) ? 2 : 1, scenario);
          if (['success', 'pending', 'multiple'].includes(scenario)) {
            await page.locator('[data-storage-live-refresh]').click();
            await page.locator('.storage-session').filter({hasText: '1 verified'}).first().waitFor();
          }
          if (['uncertain', 'recovered', 'mismatched', 'history-only'].includes(scenario)) {
            assert.equal(await page.locator('[data-storage-live-review]').isDisabled(), true);
            const lookups = requests.filter(r => r.operation === 'read_operation_outcome').length;
            recover = true; collected = true;
            await page.locator('[data-storage-live-refresh]').click();
            await page.locator('[data-storage-live-feedback]').filter({hasText: 'Discovery is not collection'}).waitFor();
            assert.ok(requests.filter(r => r.operation === 'read_operation_outcome').length > lookups);
            assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 1);
            assert.equal(await page.locator('[data-storage-live-review]').isDisabled(), scenario !== 'recovered');
            assert.match(await page.locator('[data-storage-live-result="old"]').textContent(), scenario === 'recovered' ? /outcome confirmed/ : /unconfirmed/);
            const entry = await page.evaluate(async () => (await import('/activity-history.mjs')).activities.find(e => e.operation === 'collect_saved_session_artifacts_remote'));
            assert.equal(entry.evidence_id, original.parameters.evidence_id);
            assert.equal(entry.request_id, `browser-${original.id}`);
            assert.equal(entry.session_id, 'old');
          }
          if (scenario === 'disconnect') {
            await page.reload();
            await page.locator('html[data-control-mode="controlling"]').waitFor();
            assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 1, 'No replay on reconnect');
          }
          if (scenario === 'partial-batch') {
            assert.match(await page.locator('[data-storage-live-result="old"]').textContent(), /failed/);
            assert.match(await page.locator('[data-storage-live-result="second"]').textContent(), /outcome confirmed/);
          }
        }
      }
      assert.deepEqual(errors, [], scenario);
      assert.equal(requests.some(r => /delete|release_session|normal_stop/.test(r.operation)), false);
      await page.screenshot({path: `${process.env.MICEBALL_STORAGE_SCREENSHOTS}/${scenario}.png`, fullPage: true});
    } finally { await page.close(); }
  }
  console.log(`PASS: ${scenarios.length} production-browser historical Storage scenarios`);
} finally { await browser.close(); }
