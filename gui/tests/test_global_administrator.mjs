import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {replyArtifactDestinations} from './artifact_destination_fixture.mjs';
const {chromium} = createRequire(import.meta.url)(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || 'msedge'});
const pages = [await browser.newPage(), await browser.newPage()], errors = [], commands = [];
for (const page of pages) {
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/ws', socket => {
    let controlling = false;
    socket.onMessage(raw => {
      const message = JSON.parse(raw);
      if (replyArtifactDestinations(socket, message)) return;
      if (message.operation === 'take_browser_control') { controlling = true; commands.push(message.operation); }
      else assert.equal(message.operation, 'read_controller_state');
      socket.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'controller', result: {status: 'succeeded', outcome: {details: {
        controller_id: 'controller', instance_id: 'controller', control: {controlling, generation: 1},
        configured_nodes: [], configured_services: [], status: {session_id: null}, configuration: null,
        experiments: [], pending_operations: []}}}}));
    });
    socket.send(JSON.stringify({type: 'connected', browser_id: crypto.randomUUID()}));
  });
}
const [page, other] = pages;
const section = (target, name) => target.evaluate(name => document.dispatchEvent(new CustomEvent('gui-section', {detail: name})), name);
const background = target => target.evaluate(() => getComputedStyle(document.body).backgroundColor);
const name = 'Nuria Ω';
async function enter(target) {
  await target.locator('[data-mode="administrator"]').click();
  assert.equal(await target.locator('[data-danger-enter]').isDisabled(), true);
  await target.locator('[data-administrator-entry]').fill('   ');
  assert.equal(await target.locator('[data-danger-enter]').isDisabled(), true);
  await target.locator('[data-administrator-entry]').fill(name);
  await target.locator('[data-danger-enter]').click();
}
try {
  for (const target of pages) {
    await target.goto(process.env.MICEBALL_ADMIN_ORIGIN);
    await target.locator('html[data-control-mode="view-only"]').waitFor();
  }
  for (const theme of ['light', 'dark']) for (const width of [1440, 760, 720]) {
    await page.setViewportSize({width, height: 950});
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    for (const entry of ['services', 'storage', 'parameters']) {
      await section(page, entry);
      const baseline = await background(page);
      const panelColor = await page.locator('.section-panel.is-active').evaluate(element => getComputedStyle(element).backgroundColor);
      const mode = await page.locator('.administrator-mode').boundingBox(), control = await page.locator('.connection-tools').boundingBox();
      assert.ok(mode.y >= control.y + control.height - 1, 'Mode selector is below takeover controls');
      await enter(page);
      assert.equal(await page.locator('html').getAttribute('data-control-mode'), 'view-only');
      assert.notEqual(await background(page), baseline);
      assert.equal(await page.locator('.section-panel.is-active').evaluate(element => getComputedStyle(element).backgroundColor), panelColor);
      for (const tab of ['setup', 'session', 'experiment', 'analysis', 'storage', 'parameters', 'services']) {
        await section(page, tab);
        assert.equal(await page.locator('html').getAttribute('data-administrator'), 'true');
        assert.match(await page.locator('[data-administrator-identity]').textContent(), /Nuria Ω/);
        assert.equal(await page.locator('[data-mode="administrator"]').isVisible(), ['setup', 'services', 'storage', 'parameters'].includes(tab));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${tab} at ${width}px`);
      }
      await section(other, 'services');
      assert.equal(await other.locator('html').getAttribute('data-administrator'), 'false');
      assert.equal(await other.locator('#services-administration').count(), 0);
      await section(page, entry); await page.locator('[data-mode="experimenter"]').click();
      assert.equal(await background(page), baseline);
      assert.doesNotMatch(await page.locator('[data-administrator-identity]').textContent(), /Nuria/);
    }
  }
  await section(page, 'parameters'); await enter(page);
  assert.equal(await page.locator('[data-synchronization-settings]').count(), 1);
  assert.equal(await page.locator('[data-synchronization-settings] input').count(), 7);
  assert.equal(commands.length, 0, 'Mode entry never takes Controller ownership');
  await page.locator('#take-over').click(); await page.locator('html[data-control-mode="controlling"]').waitFor();
  await section(page, 'storage');
  await page.locator('[data-destination-register]').click();
  assert.equal(await page.locator('dialog[open] [name="administrator"]').inputValue(), name);
  assert.equal(await page.locator('dialog[open] [name="administrator"]').getAttribute('readonly'), '');
  await page.locator('[data-destination-cancel]').click();
  const administratorBackground = await background(page);
  await section(other, 'parameters'); await enter(other);
  await page.locator('[data-mode="experimenter"]').click();
  assert.equal(await page.locator('html').getAttribute('data-control-mode'), 'controlling');
  assert.notEqual(await background(page), administratorBackground);
  assert.equal(await other.locator('html').getAttribute('data-administrator'), 'true');
  await page.locator('[data-mode="administrator"]').click(); await page.keyboard.press('Escape');
  assert.equal(await page.locator('html').getAttribute('data-administrator'), 'false');
  assert.deepEqual(errors, []);
  console.log('PASS: global mode/identity, all-tab navigation, browser isolation, per-operation identity reuse without takeover, synchronization editor, tint/restoration, both themes and 720–1440px layouts.');
} catch (error) { console.error(errors); throw error; }
finally { await browser.close(); }
