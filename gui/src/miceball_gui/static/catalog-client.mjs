import { parseConfigurationJSON, stringifyConfiguration } from './configuration-values.mjs';

// Reusable application data only. Execution state never enters this interface.
export const catalogClient = { snapshot: null, pending: false };
let pendingCompletion = Promise.resolve();
export function catalogId() {
  // getRandomValues also works on HTTP laboratory origins where randomUUID is
  // unavailable. Never substitute array lengths or weak random identifiers.
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function responseSnapshot(response) {
  const value = parseConfigurationJSON(await response.text());
  if (!response.ok) {
    const error = new Error(value.error || 'Catalog request failed. Your draft is retained.');
    if (response.status >= 500) error.catalogStatus = 'uncertain';
    throw error;
  }
  catalogClient.snapshot = value;
  document.dispatchEvent(new CustomEvent('gui-catalog-changed'));
  return value;
}

export async function loadCatalog() {
  // Never replace the revision beneath an in-flight mutation.
  if (catalogClient.pending) { await pendingCompletion; return loadCatalog(); }
  catalogClient.pending = true;
  let finished;
  pendingCompletion = new Promise(resolve => { finished = resolve; });
  try { return await responseSnapshot(await fetch('api/catalog', {cache: 'no-store'})); }
  finally { catalogClient.pending = false; finished(); }
}

export async function putCatalog(collection, record, actor, expectedRevision = catalogClient.snapshot?.revision) {
  if (catalogClient.pending) throw new Error('Another catalog request is pending. Your draft is retained.');
  if (!catalogClient.snapshot) throw new Error('Load the durable catalog before saving. Your draft is retained.');
  catalogClient.pending = true;
  let finished;
  pendingCompletion = new Promise(resolve => { finished = resolve; });
  try {
    let response;
    try {
      response = await fetch('api/catalog', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: stringifyConfiguration({collection, record, actor, expected_revision: expectedRevision}),
      });
    } catch (_) {
      const error = new Error('Catalog save could not be confirmed. Your draft is retained; reload and review before retrying.');
      error.catalogStatus = 'uncertain'; throw error;
    }
    return await responseSnapshot(response);
  } finally { catalogClient.pending = false; finished(); }
}
