import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || 'msedge'});
const page = await browser.newPage();
const origin = process.env.MICEBALL_CATALOG_ORIGIN, errors = [];
let configuration = null;
const executed = {experiment_id: 'executed', configuration: {duration_s: 12, participating_devices: {},
  device_configurations: {}, recording_budgets: {}, preservation_budget_bytes: 100}, scientific_outputs: []};
page.on('pageerror', error => errors.push(error.message));
await page.routeWebSocket('**/ws', socket => {
  socket.onMessage(raw => {
    const message = JSON.parse(raw);
    if (replyArtifactDestinations(socket, message)) return;
    assert.equal(message.operation, 'read_controller_state');
    socket.send(JSON.stringify({type: 'result', id: message.id, result: {status: 'succeeded', outcome: {details: {
      controller_id: 'controller', instance_id: 'owner', control: {controlling: true, generation: 1},
      configured_nodes: [], configured_services: [], pending_operations: [], configuration,
      status: {session_id: configuration?.session_id || null, session_state: configuration ? 'running' : null,
        active_experiment_id: null, experiment_lifecycle_evidence: configuration ? [
          {experiment_id: 'executed', event_type: 'experiment_start', sequence: 0, session_time_s: 1},
          {experiment_id: 'executed', event_type: 'experiment_stop', sequence: 1, session_time_s: 13}] : []},
      experiments: configuration ? [executed] : []}}}}));
  });
  socket.send(JSON.stringify({type: 'connected', browser_id: 'catalog-browser'}));
});
const snapshot = async () => (await page.request.get(`${origin}/api/catalog`)).json();
async function put(collection, record, actor = 'e1') {
  const current = await snapshot();
  const response = await page.request.post(`${origin}/api/catalog`, {headers: {Origin: origin},
    data: {collection, record, actor, expected_revision: current.revision}});
  assert.equal(response.status(), 200, await response.text());
}
async function remove(collection, identity) {
  const current = await snapshot();
  const response = await page.request.post(`${origin}/api/catalog`, {headers: {Origin: origin},
    data: {collection, identity, actor: 'Operator', administrator: true, authorized: true, expected_revision: current.revision}});
  assert.equal(response.status(), 200, await response.text());
}
const refresh = () => page.evaluate(async () => (await import('./catalog-client.mjs')).loadCatalog());
const choices = kind => page.locator(`#${kind}-select`).evaluate(select => [...select.options].map(option => ({id: option.value, name: option.textContent, historical: option.dataset.acceptedIdentity === 'true'})));
async function checkNew() {
  for (const kind of ['experimenter', 'project', 'animal']) assert.equal((await choices(kind)).filter(option => option.id === `__new_${kind}`).length, 1);
}
async function create(kind, values) {
  await page.selectOption(`#${kind}-select`, `__new_${kind}`);
  for (const [name, value] of Object.entries(values)) {
    const field = page.locator(`#catalog-form [name="${name}"]`);
    if (await field.evaluate(element => element.tagName === 'SELECT')) await field.selectOption(value);
    else await field.fill(value);
  }
  await page.locator('#catalog-save').click();
  await page.locator('#catalog-dialog').waitFor({state: 'hidden'});
  return page.locator(`#${kind}-select`).inputValue();
}
try {
  await put('experimenters', {id: 'e1', name: 'Scientist'});
  await put('experimenters', {id: 'e2', name: 'Other scientist'});
  await put('projects', {id: 'p1', name: 'Study', primary_experimenter: 'e1'});
  await put('projects', {id: 'p2', name: 'Other study', primary_experimenter: 'e2'});
  const originalAnimal = {id: 'a1', projectId: 'p1', animal_id: 'A1', animal_name: 'Catalog animal', species: 'Mouse', date_of_birth: '2026-01-01'};
  await put('animals', originalAnimal);
  await put('animals', {id: 'a2', projectId: 'p1', animal_id: 'A2'});
  await put('animals', {id: 'a3', projectId: 'p2', animal_id: 'A3'});
  await page.goto(origin);
  await page.locator('#experimenter-select option[value="e1"]').waitFor({state: 'attached'});
  await page.selectOption('#experimenter-select', 'e1'); await page.selectOption('#project-select', 'p1'); await page.selectOption('#animal-select', 'a1');
  await checkNew();
  configuration = {session_id: 'accepted', selected_devices: [], protocol_reference: null,
    session_parameters: {name: 'Accepted', experimenter: 'Scientist', project: 'Study', animal: 'A1',
      catalog_experimenter_id: 'e1', catalog_project_id: 'p1', catalog_animal_id: 'a1',
      catalog_animal_details: {...originalAnimal, animal_name: 'Recorded animal'}}};
  const accepted = structuredClone(configuration);
  await page.waitForFunction(() => document.querySelector('.setup-demo-note').textContent.includes('Accepted Session'));
  await checkNew();
  assert.equal((await choices('animal')).some(option => option.id === 'a3'), false);
  for (const [kind, id] of [['experimenter', 'e1'], ['project', 'p1'], ['animal', 'a1']]) {
    await page.selectOption(`#${kind}-select`, `__new_${kind}`);
    await page.locator('#catalog-dialog').waitFor({state: 'visible'});
    await refresh();
    assert.equal(await page.locator(`#${kind}-select`).inputValue(), `__new_${kind}`);
    await page.locator('[data-dialog-dismiss]').first().click();
    await page.waitForFunction(({kind, id}) => document.querySelector(`#${kind}-select`).value === id, {kind, id});
    assert.equal(await page.locator('#animal-name').textContent(), 'Recorded animal');
  }
  const person = await create('experimenter', {name: 'New scientist'});
  const project = await create('project', {project_name: 'New study', primary_experimenter: person});
  const animal = await create('animal', {animal_id: 'New animal', animal_name: 'New name', species: 'Mouse', strain: 'Example', sex: 'Female', date_of_birth: '2026-02-01'});
  assert.ok(person && project && animal);
  assert.deepEqual(JSON.parse(await page.locator('#accepted-configuration').textContent()), accepted);
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#animal-name').textContent === 'Recorded animal');
  await put('experimenters', {id: 'e1', name: 'Renamed scientist'});
  await put('projects', {id: 'p1', name: 'Renamed study', primary_experimenter: 'e1'});
  await put('animals', {...originalAnimal, animal_id: 'Renamed A1', animal_name: 'Changed catalog animal'});
  await refresh();
  assert.equal(await page.locator('#experimenter-select option:checked').textContent(), 'Scientist');
  assert.equal(await page.locator('#animal-name').textContent(), 'Recorded animal');
  assert.equal((await choices('experimenter')).filter(option => option.id === 'e1').length, 1);
  await page.selectOption('#experimenter-select', 'e2');
  assert.equal((await choices('experimenter')).find(option => option.id === 'e1').name, 'Renamed scientist');
  await page.selectOption('#experimenter-select', 'e1');
  assert.equal(await page.locator('#experimenter-select option:checked').textContent(), 'Renamed scientist');
  assert.deepEqual(JSON.parse(await page.locator('#accepted-configuration').textContent()), accepted);
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#animal-name').textContent === 'Recorded animal');
  await remove('experimenters', 'e1'); await remove('projects', 'p1');
  await put('experimenters', {id: 'e-reused', name: 'Scientist'});
  await put('projects', {id: 'p-reused', name: 'Study', primary_experimenter: 'e-reused'}, 'e-reused');
  await put('animals', {id: 'a-reused', projectId: 'p-reused', animal_id: 'A1', animal_name: 'Reused name animal'}, 'e-reused');
  await refresh(); await checkNew();
  const sameNames = (await choices('experimenter')).filter(option => option.name === 'Scientist');
  assert.deepEqual(sameNames.map(option => option.id).sort(), ['e-reused', 'e1']);
  assert.equal(sameNames.find(option => option.id === 'e1').historical, true);
  assert.equal(sameNames.find(option => option.id === 'e-reused').historical, false);
  assert.equal(await page.locator('#animal-name').textContent(), 'Recorded animal');
  await page.selectOption('#experimenter-select', 'e-reused'); await page.selectOption('#project-select', 'p-reused');
  assert.equal((await choices('animal')).some(option => option.id === 'a1'), false);
  assert.equal((await choices('animal')).some(option => option.id === 'a3'), false);
  await page.selectOption('#animal-select', 'a-reused');
  assert.equal(await page.locator('#animal-name').textContent(), 'Reused name animal');
  assert.deepEqual(JSON.parse(await page.locator('#accepted-configuration').textContent()), accepted);
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'experiment'})));
  await page.locator('[data-experiment-parameters]').click();
  assert.equal(await page.locator('#experiment-duration').inputValue(), '12');
  assert.equal(await page.locator('#experiment-duration').isDisabled(), true);
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-section', {detail: 'setup'})));
  configuration = null;
  await page.waitForFunction(() => document.querySelector('#accepted-configuration').textContent === 'null');
  await checkNew();
  assert.equal(await page.locator('#experimenter-select').inputValue(), 'e-reused');
  assert.equal(await page.locator('#project-select').inputValue(), 'p-reused');
  assert.equal(await page.locator('#animal-select').inputValue(), 'a-reused');
  assert.equal(await page.locator('[data-accepted-identity]').count(), 0);
  configuration = {...accepted, session_id: 'rebound'};
  await page.waitForFunction(() => document.querySelector('#experimenter-select').value === 'e1');
  configuration = null;
  await page.waitForFunction(() => document.querySelector('#accepted-configuration').textContent === 'null');
  for (const kind of ['experimenter', 'project', 'animal']) {
    assert.equal(await page.locator(`#${kind}-select`).inputValue(), '');
    assert.equal((await choices(kind)).some(option => option.historical), false);
  }
  await checkNew();
  assert.equal((await choices('experimenter')).some(option => option.id === 'e-reused'), true);
  assert.deepEqual(errors, []);
  console.log('PASS: all identity selectors retain current/New choices through acceptance, cancellation, creation, refresh, rename, removal, name reuse, explicit project-local working choices and release; accepted and executed configurations remain fixed.');
} finally { await browser.close(); }
