import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const scenarios = ['success', 'empty', 'unavailable', 'ineligible', 'source-offline', 'failed', 'incomplete', 'uncertain', 'pending', 'view-only', 'disconnect', 'multiple', 'partial-batch', 'takeover', 'recovered', 'mismatched', 'history-only',
  'delete-success', 'delete-failure', 'delete-unconfirmed', 'delete-collection-failure', 'delete-uncertain', 'delete-recovered', 'delete-mismatched', 'delete-cancel', 'delete-scope-change', 'delete-default-reset', 'delete-view-only'];
try {
  for (const scenario of scenarios) {
    console.log(`Storage scenario: ${scenario}`);
    const page = await browser.newPage(), requests = [], errors = [];
    let collected = false, controlling = true, original = null, recover = false;
    const deleting = scenario.startsWith('delete-');
    const multiple = ['multiple', 'partial-batch', 'takeover', 'delete-scope-change', 'delete-default-reset'].includes(scenario);
    const collectionDetails = request => ({session_id: request.session_id,
      collection_outcome: {session_id: request.session_id, archival_confirmed: true,
        artifact_collection_result: {succeeded: true}, collection_evidence: {evidence_id: request.parameters.evidence_id}},
      ...(request.parameters.deletion ? {deletion: {command: 'delete_original_artifacts', succeeded: !['delete-failure', 'delete-unconfirmed'].includes(scenario),
        details: {session_id: request.session_id, operation_id: scenario === 'delete-mismatched' && recover ? 'unrelated-deletion' : request.parameters.deletion.operation_id},
        error: scenario === 'delete-unconfirmed' ? 'Deletion outcome is unconfirmed' : 'Deletion refused'}} : {})});
    const record = id => ({session_id: id, experimenter_name: 'Scientist',
      accepted_session_config: {session_parameters: {name: 'Recorded <Session>', experimenter: 'Scientist'}},
      collection_status: {eligible: scenario !== 'ineligible', collection_available: true, lifecycle_state: 'completed'},
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
          return reply(request, 'succeeded', {sessions: scenario === 'empty' ? [] : multiple ? [record('old'), record('second')] : [record('old')],
            capacity: {ready: true, destinations: [{destination: '/scientific', available_bytes: 123456, ready: true}]}});
        }
        if (request.operation === 'read_storage_session') return reply(request, 'succeeded', {...record('old'),
          nodes: {node: scenario === 'source-offline' ? {confirmed: false, reason: 'Node historical state is unavailable'}
            : {confirmed: true, inventory: {artifacts: [{manifest: {artifact_manifest_id: 'camera-file'}}]}}}});
        if (request.operation === 'collect_saved_session_artifacts_remote') {
          original = request;
          assert.equal(typeof request.parameters.evidence_id, 'string');
          const expectedDeletion = deleting && scenario !== 'delete-cancel' && !(scenario === 'delete-default-reset' && request.session_id === 'second');
          assert.equal('deletion' in request.parameters, expectedDeletion);
          if (expectedDeletion) {
            assert.equal(typeof request.parameters.deletion.operation_id, 'string');
            assert.equal(request.parameters.deletion.experiment_ids, null);
            assert.equal(request.parameters.deletion.confirmed, true);
            assert.equal(request.parameters.deletion.warning_acknowledged, true);
          }
          assert.equal(request.parameters.experimenter_name, 'Scientist');
          if (scenario === 'disconnect') { route.close(); return; }
          if (scenario === 'takeover') { controlling = false; return reply(request, 'failed', {}, 'Browser control changed'); }
          if (scenario === 'partial-batch' && request.session_id === 'old') return reply(request, 'failed', {}, 'First source unavailable; collection incomplete');
          if (['failed', 'incomplete', 'source-offline', 'delete-collection-failure'].includes(scenario)) return reply(request, 'failed',
            {collection_outcome: {artifact_collection_result: {succeeded: false}}}, 'Source unavailable or collection incomplete');
          if (['uncertain', 'recovered', 'mismatched', 'history-only', 'delete-uncertain', 'delete-recovered', 'delete-mismatched'].includes(scenario)) return reply(request, 'uncertain', {}, 'Collection response unconfirmed');
          collected = true;
          return reply(request, ['delete-failure', 'delete-unconfirmed'].includes(scenario) ? 'failed' : scenario === 'pending' ? 'pending' : 'succeeded', collectionDetails(request));
        }
        if (request.operation === 'read_operation_outcome') {
          assert.equal(request.parameters.target_request_id, `browser-${original.id}`);
          assert.equal(request.parameters.instance_id, 'owner');
          const status = scenario === 'pending' || recover && ['recovered', 'mismatched', 'delete-recovered', 'delete-mismatched'].includes(scenario) ? 'succeeded' : 'uncertain';
          return reply(request, 'succeeded', {instance_id: 'owner', status,
            result: {request_id: scenario === 'mismatched' && recover ? 'different-request' : `browser-${original.id}`,
              operation: original.operation, session_id: original.session_id, status,
              outcome: status === 'succeeded' ? {details: collectionDetails(original)} : null}});
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
        if (['view-only', 'ineligible'].includes(scenario)) {
          assert.equal(await page.locator('[data-storage-live-add="old"]').isDisabled(), true);
          assert.equal(await page.locator('[data-storage-live-review]').isDisabled(), true);
        }
        else {
          await page.locator('[data-storage-live-add="old"]').click();
          if (['multiple', 'partial-batch', 'takeover'].includes(scenario)) await page.locator('[data-storage-live-add="second"]').click();
          assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 0);
          if (scenario === 'delete-success') for (const theme of ['light', 'dark']) {
            await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
            assert.notEqual(await page.locator('[data-storage-live-review]').evaluate(button => getComputedStyle(button).backgroundColor),
              await page.locator('[data-storage-live-refresh]').evaluate(button => getComputedStyle(button).backgroundColor));
            await page.screenshot({path: `${process.env.MICEBALL_STORAGE_SCREENSHOTS}/store-primary-${theme}.png`, fullPage: true});
          }
          await page.locator('[data-storage-live-review]').click();
          assert.equal(await page.locator('[data-storage-live-delete]').isChecked(), false);
          assert.equal(await page.locator('[data-storage-live-confirm]').evaluate(button => button.classList.contains('dialog-button--primary')), true);
          if (deleting) {
            await page.locator('[data-storage-live-delete]').check();
            assert.equal(await page.locator('[data-storage-live-confirm]').isDisabled(), true);
            await page.locator('[data-storage-live-confirm]').evaluate(button => button.click());
            assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 0);
            assert.match(await page.locator('.storage-dialog[open]').innerText(), /old.*entire Session, all original scientific artifact files/);
            await page.locator('[data-storage-live-acknowledge]').check();
            if (['delete-cancel', 'delete-scope-change'].includes(scenario)) {
              await page.locator('[data-storage-live-cancel]').click();
              assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 0);
              if (scenario === 'delete-scope-change') await page.locator('[data-storage-live-add="second"]').click();
              await page.locator('[data-storage-live-review]').click();
              assert.equal(await page.locator('[data-storage-live-delete]').isChecked(), false);
              if (scenario === 'delete-scope-change') {
                assert.match(await page.locator('.storage-dialog[open]').innerText(), /second.*entire Session/);
                await page.locator('[data-storage-live-delete]').check();
                await page.locator('[data-storage-live-acknowledge]').check();
              }
            }
            if (scenario === 'delete-view-only') {
              await page.evaluate(() => document.querySelector('#view-only').click());
              await page.locator('html[data-control-mode="view-only"]').waitFor();
              assert.equal(await page.locator('[data-storage-live-confirm]').isDisabled(), true);
              await page.locator('[data-storage-live-confirm]').evaluate(button => button.click());
              assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 0);
              assert.deepEqual(errors, []); continue;
            }
            if (scenario === 'delete-success') for (const theme of ['light', 'dark']) {
              await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
              const primary = await page.locator('[data-storage-live-confirm]').evaluate(button => getComputedStyle(button).backgroundColor);
              const secondary = await page.locator('[data-storage-live-cancel]').evaluate(button => getComputedStyle(button).backgroundColor);
              assert.notEqual(primary, secondary);
              await page.screenshot({path: `${process.env.MICEBALL_STORAGE_SCREENSHOTS}/delete-review-${theme}.png`});
            }
          }
          await page.locator('[data-storage-live-confirm]').evaluate(button => { button.click(); button.click(); });
          await page.waitForFunction(() => document.querySelector('[data-storage-live-feedback]').textContent.match(/succeeded|incomplete|unconfirmed|not fully confirmed|Remaining|context changed/));
          if (scenario !== 'disconnect') await page.locator('[data-storage-live-refresh]:enabled').waitFor();
          const collections = requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote');
          assert.equal(collections.length, ['multiple', 'partial-batch', 'delete-scope-change'].includes(scenario) ? 2 : 1, scenario);
          if (['success', 'pending', 'multiple'].includes(scenario)) {
            await page.locator('[data-storage-live-refresh]').click();
            await page.locator('.storage-session').filter({hasText: '1 verified'}).first().waitFor();
          }
          if (['uncertain', 'recovered', 'mismatched', 'history-only', 'delete-uncertain', 'delete-recovered', 'delete-mismatched'].includes(scenario)) {
            assert.equal(await page.locator('[data-storage-live-review]').isDisabled(), true);
            const lookups = requests.filter(r => r.operation === 'read_operation_outcome').length;
            recover = true; collected = true;
            await page.locator('[data-storage-live-refresh]').click();
            await page.locator('[data-storage-live-feedback]').filter({hasText: 'Discovery is not collection'}).waitFor();
            assert.ok(requests.filter(r => r.operation === 'read_operation_outcome').length > lookups);
            assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 1);
            assert.equal(await page.locator('[data-storage-live-review]').isDisabled(), !['recovered', 'delete-recovered'].includes(scenario));
            assert.match(await page.locator('[data-storage-live-result="old"]').textContent(), ['recovered', 'delete-recovered'].includes(scenario) ? /succeeded/ : /unconfirmed/);
            const entry = await page.evaluate(async () => (await import('/activity-history.mjs')).activities.find(e => e.operation === 'collect_saved_session_artifacts_remote'));
            assert.equal(entry.evidence_id, original.parameters.evidence_id);
            assert.equal(entry.request_id, `browser-${original.id}`);
            assert.equal(entry.session_id, 'old');
            if (deleting) assert.equal(entry.deletion_operation_id, original.parameters.deletion.operation_id);
          }
          if (['delete-failure', 'delete-unconfirmed'].includes(scenario)) assert.match(await page.locator('[data-storage-live-result="old"]').innerText(), /Collection succeeded.*deletion was not fully confirmed/);
          if (scenario === 'delete-collection-failure') assert.doesNotMatch(await page.locator('[data-storage-live-result="old"]').innerText(), /deletion succeeded|Collection succeeded/);
          if (scenario === 'delete-default-reset') {
            await page.locator('[data-storage-live-refresh]').click();
            await page.locator('[data-storage-live-add="second"]:enabled').waitFor();
            await page.locator('[data-storage-live-add="second"]').click();
            await page.locator('[data-storage-live-review]').click();
            assert.equal(await page.locator('[data-storage-live-delete]').isChecked(), false);
            await page.locator('[data-storage-live-confirm]').click();
            await page.locator('[data-storage-live-refresh]:enabled').waitFor();
            assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 2);
          }
          if (scenario === 'disconnect') {
            await page.reload();
            await page.locator('html[data-control-mode="controlling"]').waitFor();
            assert.equal(requests.filter(r => r.operation === 'collect_saved_session_artifacts_remote').length, 1, 'No replay on reconnect');
          }
          if (scenario === 'partial-batch') {
            assert.match(await page.locator('[data-storage-live-result="old"]').textContent(), /failed/);
            assert.match(await page.locator('[data-storage-live-result="second"]').textContent(), /succeeded/);
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
