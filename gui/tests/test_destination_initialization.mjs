// Production modules and disposable backend; only Controller transport is controlled.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || 'msedge'});
const origin = process.env.MICEBALL_DESTINATION_ORIGIN;
try {
  for (const initial of ['delayed', 'failed']) {
    const page = await browser.newPage();
    page.setDefaultTimeout(10000);
    const errors = [], commands = [];
    page.on('pageerror', error => errors.push(error.message));
    let releaseCatalog, holdReply, activeSocket, reconnected, available = false;
    let catalogCalls = 0;
    const gate = new Promise(resolve => { releaseCatalog = resolve; });
    await page.route('**/api/catalog', async route => {
      if (route.request().method() !== 'GET' || catalogCalls++ > 0) return route.continue();
      if (initial === 'delayed') { await gate; return route.continue(); }
      return route.fulfill({status: 503, contentType: 'application/json', body: '{"error":"Catalog temporarily unavailable"}'});
    });
    let sockets = 0;
    await page.routeWebSocket('**/ws', route => {
      sockets++;
      activeSocket = route;
      if (sockets > 1) reconnected?.();
      route.onMessage(raw => {
        const message = JSON.parse(raw); commands.push(message.operation);
        const reply = (status, details = {}, error = '') => route.send(JSON.stringify({type: 'result', id: message.id,
          result: {status, error, outcome: {details}}}));
        if (message.operation === 'read_controller_state') reply('succeeded', {
          controller_id: 'controller', instance_id: 'instance', control: {controlling: false},
          configuration: null, status: {session_id: null}, experiments: [], configured_nodes: [],
          configured_services: [], pending_operations: []});
        else if (message.operation === 'list_artifact_destinations') {
          if (holdReply) holdReply(() => reply('failed', {}, 'Destination readback unavailable'));
          else if (available) reply('succeeded', {storage_id: 'storage', default_destination_id: null, destinations: []});
          else reply('failed', {}, 'Destination readback unavailable');
        } else throw new Error(`Unexpected operation: ${message.operation}`);
      });
      route.send(JSON.stringify({type: 'connected', browser_id: 'browser'}));
    });
    await page.goto(origin);
    await page.locator('#artifact-destination').waitFor({state: 'attached'});
    await page.waitForFunction(async () => (await import('./activity-history.mjs')).activities.some(
      entry => entry.operation === 'destination_discovery' && entry.status === 'unknown'));
    assert.ok(commands.includes('read_controller_state'));
    assert.ok(commands.includes('list_artifact_destinations'));
    assert.equal(await page.evaluate(async () => Array.isArray((await import('./protocol-setup.js')).state.experimentTemplates)), true);
    assert.equal(await page.evaluate(async () => (await import('./catalog-client.mjs')).catalogClient.snapshot === null), true);
    // The final Parameters event handler must be registered even before catalog hydration.
    await page.evaluate(() => document.dispatchEvent(new Event('gui-administrator-changed')));
    assert.deepEqual(errors, []);
    const entries = () => page.evaluate(async () => (await import('./activity-history.mjs')).activities.filter(
      entry => entry.operation === 'destination_discovery').map(({activity_id, status}) => ({activity_id, status})));
    for (let attempt = 0; attempt < 2; attempt++) {
      const before = await entries();
      let finish;
      holdReply = callback => { finish = callback; };
      await page.getByRole('button', {name: 'Refresh destinations', exact: true}).click();
      await page.waitForFunction(async () => (await import('./activity-history.mjs')).activities.at(-1)?.status === 'pending');
      assert.match(await page.locator('#artifact-destination-info').innerText(), /pending|requested|Refreshing/i);
      const pending = await entries();
      assert.equal(pending.length, before.length + 1);
      assert.equal(pending.at(-1).status, 'pending');
      assert.ok(finish);
      const submitted = commands.length;
      await page.getByRole('button', {name: 'Refresh destinations', exact: true}).click();
      assert.equal(commands.length, submitted, 'a pending request is not duplicated');
      assert.deepEqual(await entries(), pending);
      finish(); holdReply = null;
      await page.waitForFunction(async () => (await import('./activity-history.mjs')).activities.at(-1)?.status === 'unknown');
      assert.equal((await entries()).length, pending.length, 'completion updates the same request');
      assert.match(await page.locator('#artifact-destination-info').innerText(), /unavailable|could not be confirmed/i);
    }
    const beforeBackground = await entries();
    await page.evaluate(async () => {
      const {refreshArtifactDestinations} = await import('./artifact-destinations.js');
      await refreshArtifactDestinations(); await refreshArtifactDestinations();
    });
    assert.deepEqual(await entries(), beforeBackground, 'background failures still coalesce');
    available = true;
    await page.getByRole('button', {name: 'Refresh destinations', exact: true}).click();
    await page.waitForFunction(async () => (await import('./activity-history.mjs')).activities.at(-1)?.status === 'succeeded');
    assert.equal((await entries()).length, beforeBackground.length + 1);
    releaseCatalog();
    await page.evaluate(async () => (await import('./catalog-client.mjs')).loadCatalog());
    assert.equal(await page.evaluate(async () => Array.isArray((await import('./catalog-client.mjs')).catalogClient.snapshot.catalog.experimentTemplates)), true);
    let snapshot = await (await page.request.get(`${origin}/api/catalog`)).json();
    if (!snapshot.catalog.experimenters.some(item => item.id === 'alice')) {
      const created = await page.request.post(`${origin}/api/catalog`, {headers: {Origin: origin}, data: {
        expected_revision: snapshot.revision, actor: 'alice', collection: 'experimenters', record: {id: 'alice', name: 'Alice'}}});
      assert.equal(created.status(), 200, await created.text());
      snapshot = await created.json();
    }
    const id = `template-${initial}`;
    const saved = await page.request.post(`${origin}/api/catalog`, {headers: {Origin: origin}, data: {
      expected_revision: snapshot.revision, actor: 'alice', collection: 'experimentTemplates',
      record: {id, name: id, owner: 'alice', operation: 'acquisition', configuration: {durationSeconds: 12, participants: [], values: {}}}}});
    assert.equal(saved.status(), 200, await saved.text());
    const reconnect = new Promise(resolve => { reconnected = resolve; });
    await activeSocket.close();
    await Promise.race([reconnect, new Promise((_, reject) => {
      const timer = setTimeout(() => reject(new Error('Browser did not reconnect')), 10000);
      timer.unref();
    })]);
    await page.waitForFunction(async id => (await import('./protocol-setup.js')).state.experimentTemplates.some(item => item.id === id), id);
    assert.deepEqual(errors, []);
    assert.equal(sockets, 2);
    await page.close();
    console.log(`PASS: ${initial} initial catalog, complete module startup, destination requests, two explicit failures and success, background deduplication, populated hydration after socket reconnection.`);
  }
} finally { await browser.close(); }
