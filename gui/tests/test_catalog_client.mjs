import test from 'node:test';
import assert from 'node:assert/strict';
import {catalogClient, loadCatalog, putCatalog, catalogId} from '../src/miceball_gui/static/catalog-client.mjs';

test('automatic refresh waits for an in-flight catalog save without changing its revision baseline', async () => {
  const oldFetch = globalThis.fetch, oldDocument = globalThis.document;
  globalThis.document = new EventTarget();
  let release, reads = 0, revision = 4;
  globalThis.fetch = async (_url, options) => {
    if (options?.method === 'POST') {
      assert.equal(JSON.parse(options.body).expected_revision, 4);
      await new Promise(resolve => { release = resolve; }); revision = 5;
    } else reads++;
    return new Response(JSON.stringify({version: 1, revision, catalog: {experimenters: []}}), {status: 200});
  };
  try {
    await loadCatalog();
    const draft = {id: 'alice', name: 'Alice'}, before = structuredClone(draft);
    const saving = putCatalog('experimenters', draft, 'alice');
    const refreshing = loadCatalog();
    await Promise.resolve();
    assert.equal(reads, 1);
    release(); await Promise.all([saving, refreshing]);
    assert.equal(reads, 2);
    assert.equal(catalogClient.snapshot.revision, 5);
    assert.deepEqual(draft, before);
  } finally { globalThis.fetch = oldFetch; globalThis.document = oldDocument; }
});

test('stable catalog identities remain available on HTTP origins without randomUUID', () => {
  const original = crypto.randomUUID;
  try {
    crypto.randomUUID = undefined;
    const identity = catalogId();
    assert.match(identity, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.notEqual(catalogId(), identity);
  } finally { crypto.randomUUID = original; }
});

test('catalog read/save preserves typed values and stale or uncertain saves retain the caller draft', async () => {
  const oldFetch = globalThis.fetch, oldDocument = globalThis.document;
  globalThis.document = new EventTarget();
  const snapshot = {version: 1, revision: 3, catalog: {experimentTemplates: []}};
  const draft = {id: catalogId(), name: 'Exact', owner: 'alice', operation: 'acquisition', configuration: {
    values: {['__proto__']: null, text: ' \u03a9\r\n\0\ud800"\\ ', empty: '', null: null, zero: 0, flag: false}, participants: []}};
  const before = structuredClone(draft);
  try {
    globalThis.fetch = async () => new Response(JSON.stringify(snapshot), {status: 200});
    await loadCatalog();
    globalThis.fetch = async (_url, options) => {
      const payload = JSON.parse(options.body);
      assert.equal(payload.expected_revision, 3);
      assert.deepEqual(payload.record, draft);
      return new Response(JSON.stringify({error: 'Stale catalog; review retained draft'}), {status: 409});
    };
    await assert.rejects(putCatalog('experimentTemplates', draft, 'alice'), /Stale/);
    assert.deepEqual(draft, before);
    assert.equal(catalogClient.snapshot.revision, 3);
    globalThis.fetch = async () => { throw new TypeError('Disconnected after submission'); };
    await assert.rejects(putCatalog('experimentTemplates', draft, 'alice'), error => error.catalogStatus === 'uncertain');
    assert.deepEqual(draft, before);
    globalThis.fetch = async () => new Response(JSON.stringify({...snapshot, revision: 4, catalog: {experimentTemplates: [draft]}}), {status: 200});
    await putCatalog('experimentTemplates', draft, 'alice');
    assert.equal(catalogClient.snapshot.revision, 4);
    assert.deepEqual(catalogClient.snapshot.catalog.experimentTemplates[0], draft);
    assert.notEqual(catalogId(), draft.id);
  } finally { globalThis.fetch = oldFetch; globalThis.document = oldDocument; }
});
