import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
const origin = process.env.MICEBALL_CATALOG_ORIGIN;
const errors = [];
const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
const page = await context.newPage();
const second = await context.newPage();
for (const target of [page, second]) target.on('pageerror', error => errors.push(error.message));
const waitFor = async predicate => { for (let i = 0; i < 100; i++) { if (await predicate()) return; await new Promise(resolve => setTimeout(resolve, 50)); } throw new Error('Browser condition did not converge'); };
const section = (target, name) => target.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
async function create(target, kind, values) {
  await target.selectOption(`#${kind}-select`, `__new_${kind}`);
  for (const [name, value] of Object.entries(values)) {
    const control = target.locator(`#catalog-form [name="${name}"]`);
    if (await control.evaluate(element => element.tagName === 'SELECT')) await control.selectOption(value);
    else await control.fill(value);
  }
  await target.locator('#catalog-save').click();
  await waitFor(() => target.locator('#catalog-dialog').evaluate(element => !element.open));
  return target.locator(`#${kind}-select`).inputValue();
}
try {
  await page.goto(origin);
  await waitFor(() => page.getByRole('status').filter({hasText: 'Catalogs loaded.'}).count());
  const alice = await create(page, 'experimenter', {name: 'Alice'});
  const project = await create(page, 'project', {project_name: 'Study', primary_experimenter: alice});
  const animal = await create(page, 'animal', {animal_id: 'M1', animal_name: 'Pip', species: 'Mouse', strain: 'Example', sex: 'Female', date_of_birth: '2026-10-24'});
  assert.notEqual(alice, 'Alice'); assert.notEqual(project, 'Study'); assert.notEqual(animal, 'M1');
  assert.equal(await page.locator('#animal-name').innerText(), 'Pip');
  await page.locator('#new-protocol').click();
  await page.locator('#protocol-name').fill('Study procedure');
  await page.locator('#add-step').click();
  await page.locator('#step-form [name="name"]').fill('Saved acquisition');
  await page.locator('#save-reusable-step').click();
  await waitFor(() => page.locator('#step-definition-status').innerText().then(text => text.includes('read-only')));
  await page.locator('#save-protocol').click();
  await waitFor(() => page.locator('#panel-setup').isVisible());
  const protocol = await page.locator('#protocol-select').inputValue();
  assert.ok(protocol);
  await second.goto(origin);
  await waitFor(() => second.locator('#experimenter-select option').filter({hasText: /^Alice$/}).count());
  await second.selectOption('#experimenter-select', alice);
  await second.selectOption('#project-select', project);
  assert.equal(await second.locator('#protocol-select option').filter({hasText: 'Study procedure'}).count(), 1);
  await second.selectOption('#animal-select', animal);
  assert.equal(await second.locator('#animal-name').innerText(), 'Pip');

  // Two pages loaded the same revision; the second one's newer save fences the first.
  await page.locator('#edit-protocol').click();
  await page.locator('#protocol-name').fill('Retained working draft');
  await create(second, 'experimenter', {name: 'Bob'});
  await page.locator('#save-protocol').click();
  await waitFor(() => page.locator('#editor-message').innerText().then(text => text.includes('another browser')));
  assert.equal(await page.locator('#protocol-name').inputValue(), 'Retained working draft');
  assert.equal(await page.locator('#panel-protocol-editor').isVisible(), true);
  const committed = await (await context.request.get(`${origin}/api/catalog`)).json();
  assert.equal(committed.catalog.protocols[0].name, 'Study procedure');

  // Explicitly reload the accepted catalog without discarding the editor draft.
  await section(page, 'setup');
  await waitFor(() => page.locator('#experimenter-select option').filter({hasText: /^Bob$/}).count());
  await page.locator('#edit-protocol').click();
  await page.locator('#save-protocol').click();
  await waitFor(() => page.locator('#editor-message').innerText().then(text => text.includes('another browser')));
  assert.equal(await page.locator('#protocol-name').inputValue(), 'Retained working draft');
  await section(page, 'setup');
  assert.equal(await page.getByRole('button', {name: 'Reload catalogs', exact: true}).count(), 0);
  await page.evaluate(() => document.dispatchEvent(new Event('gui-control-acquired')));
  await page.locator('#edit-protocol').click();
  assert.equal(await page.locator('#protocol-name').inputValue(), 'Retained working draft');
  await page.locator('#save-protocol').click();
  await waitFor(() => page.locator('#editor-message').innerText().then(text => text.includes('another browser')));
  // A refresh never blesses the stale draft. Start a fresh edit explicitly.
  await page.locator('#cancel-protocol').click();
  await page.locator('button[value="discard"]').click();
  await page.locator('#edit-protocol').click();
  await page.locator('#protocol-name').fill('Retained working draft');
  await page.locator('#save-protocol').click();
  await waitFor(() => page.locator('#panel-setup').isVisible());

  // Project-scoped records do not leak into a different project.
  await page.selectOption('#experimenter-select', alice);
  const otherProject = await create(page, 'project', {project_name: 'Another study', primary_experimenter: alice});
  assert.equal(await page.locator('#protocol-select option').count(), 1);
  assert.equal(await page.locator('#animal-select option').count(), 2);
  await page.selectOption('#project-select', project);
  await page.selectOption('#protocol-select', protocol);
  assert.equal(await page.locator('#protocol-select option:checked').innerText(), 'Retained working draft');

  // An uncertain storage reply retains the actual form, and dismissal cannot
  // discard its fields while the save is awaiting a response.
  let releaseReply;
  await page.route('**/api/catalog', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await new Promise(resolve => { releaseReply = resolve; });
    await route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({error: 'Catalog save could not be confirmed. Your draft is retained.'})});
  });
  await page.selectOption('#experimenter-select', '__new_experimenter');
  await page.locator('#catalog-fields [name="name"]').fill('Retained unsaved scientist');
  await page.locator('#catalog-save').click();
  await waitFor(() => Boolean(releaseReply));
  assert.equal(await page.locator('#catalog-save').isDisabled(), true);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#catalog-dialog').evaluate(element => element.open), true);
  releaseReply();
  await waitFor(() => page.locator('#catalog-save').isEnabled());
  assert.equal(await page.locator('#catalog-fields [name="name"]').inputValue(), 'Retained unsaved scientist');
  assert.ok((await page.locator('[data-catalog-error]').innerText()).includes('could not be confirmed'));
  await page.locator('[data-dialog-dismiss]').first().click();
  await page.unroute('**/api/catalog');

  const directory = process.env.MICEBALL_CATALOG_EVIDENCE;
  await mkdir(directory, {recursive: true});
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    await section(page, 'services');
    await waitFor(() => page.locator('[data-gui-backend]').innerText().then(text => text.includes('Catalog available')));
    const backend = page.locator('[data-gui-backend]');
    if (!await backend.locator('details').evaluate(element => element.open)) await backend.locator('summary').click();
    assert.ok((await backend.innerText()).includes('catalog.sqlite3'));
    await backend.locator('summary').focus();
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('gui-notifications-changed')));
    assert.equal(await backend.locator('summary').evaluate(element => document.activeElement === element), true);
    assert.equal(await backend.locator('[data-stop-service], [data-live-kill], [data-administrative]').count(), 0);
    await page.screenshot({path: `${directory}/catalog-services-${theme}.png`, fullPage: true});
    await page.setViewportSize({width: 800, height: 700});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await section(page, 'setup');
    await page.screenshot({path: `${directory}/catalog-setup-narrow-${theme}.png`, fullPage: true});
    await page.setViewportSize({width: 1440, height: 1000});
  }
  assert.deepEqual(errors, []);
  console.log('PASS: real catalog forms, stable identities, shared browsers, project filtering, reusable Step/protocol save, stale-draft retention and explicit reload, backend Services, light/dark and narrow layout; no browser exceptions.');
} catch (error) {
  console.error('Browser exceptions:', errors);
  console.error('Page:', await page.locator('body').innerText());
  throw error;
} finally { await browser.close(); }
