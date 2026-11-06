// Invoked by the Python fixture so every UI command reaches real isolated owners.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
const require = createRequire(import.meta.url);
if (!process.env.MICEBALL_BROWSER_ORIGIN) {
  console.log('Rendered integration requires the disposable Python fixture.');
} else {
  const { chromium } = require(process.env.LAB_SYNC_PLAYWRIGHT_MODULE || 'playwright');
  const browser = await chromium.launch({headless: true, channel: process.env.LAB_SYNC_BROWSER_CHANNEL || undefined});
  const directory = process.env.MICEBALL_BROWSER_EVIDENCE;
  await mkdir(directory, {recursive: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  const submitted = [];
  const submittedData = [];
  let lastState;
  page.on('pageerror', error => errors.push(error.message));
  page.on('websocket', socket => {
    socket.on('framesent', frame => {
      try { const data = JSON.parse(frame.payload); submitted.push(data.operation); submittedData.push(data); } catch (_) {}
    });
    socket.on('framereceived', frame => {
      try { const details = JSON.parse(frame.payload).result?.outcome?.details; if (details?.experiments) lastState = details; } catch (_) {}
    });
  });
  const config = JSON.parse(process.env.MICEBALL_BROWSER_CONFIGURATION);
  const section = async name => {
    await page.locator('#navigation-toggle').click();
    await page.locator(`.nav-item[data-section="${name}"]`).click();
    await page.waitForTimeout(250); // Compare settled layout, not the sidebar transition.
  };
  const shots = [];
  const shot = async name => {
    await page.screenshot({path: `${directory}/${name}.png`, fullPage: true});
    shots.push({name, viewport: page.viewportSize(), theme: await page.locator('html').getAttribute('data-theme'), url: page.url()});
  };
  try {
    await page.goto(process.env.MICEBALL_BROWSER_ORIGIN);
    await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
    assert.equal(await page.locator('.setup-disclosure').count(), 9);
    await page.locator('[data-close-setup]').click();
    assert.equal(await page.locator('.setup-disclosure[open]').count(), 0);
    await shot('connected-setup-collapsed');
    await page.locator('[data-open-setup]').click();
    await shot('connected-setup-expanded');
    await page.locator('#take-over').click();
    await page.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    await page.locator('#load-inventory').click();
    await page.locator('#session-device-list input').waitFor();
    await page.locator('#session-device-list input').check();
    await page.locator('.session-identity-grid textarea[data-configuration-string]').fill(JSON.stringify('Browser Session'));
    await page.locator('.session-identity-grid input[type="date"]').fill('2026-11-03');
    await page.locator('.session-identity-grid input[type="number"]').fill('1');
    for (const [kind, values] of Object.entries({experimenter: {name: 'Browser Scientist'}, project: {project_name: 'Browser Project', primary_experimenter: 'Browser Scientist'}, animal: {animal_id: 'Browser Animal', animal_name: 'Animal', species: 'Mouse', strain: 'Lab', date_of_birth: '2026-01-01'}})) {
      await page.locator(`#${kind}-select`).selectOption(`__new_${kind}`);
      for (const [key, value] of Object.entries(values)) await page.locator(`#catalog-fields [name="${key}"]`).fill(value);
      await page.locator('#catalog-save').click();
    }
    await page.locator('[aria-labelledby="storage-title"] textarea[data-configuration-string]:not(#error-evidence-location)').fill(JSON.stringify(config.storage));
    await page.locator('#error-evidence-location').fill(JSON.stringify(config.errors));
    await page.locator('details').filter({has: page.locator('#session-framework-fields')}).last().evaluate(element => element.open = true);
    await page.locator('#session-framework-fields').fill(JSON.stringify(config.fields));
    await page.locator('.launch-session-demo').click();
    await page.locator('[data-start-session]').waitFor();
    await page.locator('[data-start-session]').click();
    await page.locator('[data-prepare-free-operation]').click();
    await page.locator('.experiment-additional-devices').evaluate(element => element.open = true);
    await page.locator('[data-session-experiment-device]').first().check();
    await page.locator('[data-session-navigate="parameters"]').click();
    await page.locator('#experiment-duration').fill('30');
    await page.locator('[data-framework-field="experimentId"]').fill(JSON.stringify('browser-recording'));
    await page.locator('[data-framework-field="preservationBudget"]').fill('1000000');
    await page.locator('[data-recording-budget]').fill('1000000');
    await page.locator('[data-scientific-output]').first().check();
    await page.locator('[data-example-value]').nth(0).fill('1');
    await page.locator('[data-example-value]').nth(3).fill('1');
    await page.locator('[data-example-value]').nth(3).fill('');
    await shot('connected-parameters');
    await page.locator('[data-return-session]').click();
    await shot('connected-session');
    await page.locator('[data-launch-experiment]').click();
    await page.locator('[data-stop-experiment]').waitFor();
    const intendedOverrides = {node: {device: {frames_per_collect: 1, fps: null}}};
    assert.deepEqual(submittedData.find(message => message.operation === 'start_launched_experiment').parameters.configuration.device_configurations, intendedOverrides);
    assert.deepEqual(lastState.experiments.find(experiment => experiment.experiment_id === 'browser-recording').configuration.device_configurations, intendedOverrides);
    const observer = await browser.newPage();
    await observer.goto(process.env.MICEBALL_BROWSER_ORIGIN);
    await observer.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
    assert.equal(await observer.locator('.launch-session-demo').isDisabled(), true);
    await observer.locator('[data-close-setup]').click();
    assert.equal(await observer.locator('.setup-disclosure[open]').count(), 0);
    await observer.locator('#take-over').click();
    await observer.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
    assert.equal(await page.locator('[data-stop-experiment]').isDisabled(), true);
    assert.ok((await page.locator('#experiment-monitor-fields').textContent()).includes('running'));
    await page.locator('#take-over').click();
    await page.locator('#connection-state').filter({hasText: 'Controlling'}).waitFor();
    await observer.close();
    await page.locator('[data-show-experiment-parameters]').click();
    assert.match(await page.locator('#experiment-parameters-drawer').innerText(), /fps: null/);
    await shot('connected-experiment-drawer');
    await page.locator('[data-show-experiment-parameters]').click();
    await page.locator('[data-stop-experiment]').click();
    await shot('connected-stop-dialog');
    await page.getByRole('button', {name: 'Confirm Stop', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#experiment-monitor-fields')?.textContent.includes('completed'));
    assert.equal(await page.locator('#experiment-parameters-drawer').isVisible(), false);
    await page.locator('[data-show-experiment-parameters]').click();
    await page.locator('#experiment-parameters-drawer').filter({hasText: 'Fixed executed-attempt configuration'}).waitFor();
    for (const mode of ['connected', 'demo']) {
      if (mode === 'demo') await page.goto(process.env.MICEBALL_DEMO_ORIGIN);
      for (const [width, height, size] of [[1440,1000,'desktop'], [800,900,'narrow']]) {
        await page.setViewportSize({width,height});
        for (const theme of ['light','dark']) {
          if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
          await section('setup');
          await page.locator('[data-close-setup]').click(); await shot(`${mode}-${size}-${theme}-setup-collapsed`);
          await page.locator('[data-open-setup]').click(); await shot(`${mode}-${size}-${theme}-setup-expanded`);
          for (const name of ['session','experiment','analysis','storage','services']) {
            await section(name); await shot(`${mode}-${size}-${theme}-${name}`);
            if (name === 'session') {
              await page.locator('[data-session-navigate="parameters"]').first().click();
              await shot(`${mode}-${size}-${theme}-parameters`);
            }
            if (name === 'experiment') {
              const drawer = page.locator('#experiment-parameters-drawer');
              if (!await drawer.isVisible()) await page.locator('[data-show-experiment-parameters]').click();
              await shot(`${mode}-${size}-${theme}-drawer`);
              await page.locator('[data-show-experiment-parameters]').click();
            }
            if (name === 'storage') {
              for (const workspace of ['deletion', 'history']) {
                await page.locator(`[data-storage-workspace="${workspace}"]`).click();
                await shot(`${mode}-${size}-${theme}-storage-${workspace}`);
              }
              await page.locator('[data-storage-workspace="collection"]').click();
            }
            if (name === 'services') {
              await page.locator('[data-mode="administrator"]').click();
              await shot(`${mode}-${size}-${theme}-administrator-dialog`);
              await page.locator('[data-danger-enter]').click();
              await shot(`${mode}-${size}-${theme}-administrator`);
              if (mode === 'connected') assert.equal(await page.locator('[data-shutdown-framework]').isDisabled(), true);
              await page.locator('[data-mode="experimenter"]').click();
            }
          }
          await section('setup');
          await page.locator('#experimenter-select').selectOption('__new_experimenter');
          await shot(`${mode}-${size}-${theme}-catalog-dialog`);
          await page.locator('[data-dialog-dismiss]').first().click();
          await page.locator('#navigation-toggle').click();
          await page.waitForTimeout(250);
          await shot(`${mode}-${size}-${theme}-navigation`);
          await page.locator('#navigation-toggle').click();
        }
      }
      if (mode === 'connected') {
        await section('session');
        await page.locator('[data-session-navigate="parameters"]').click();
        assert.equal(await page.locator('[data-scientific-output]').first().isChecked(), true);
        assert.equal(await page.locator('[data-scientific-output]').first().isDisabled(), true);
        await page.locator('[data-return-session]').click();
        await page.locator('[data-prepare-experiment]').click();
        await page.locator('[data-session-navigate="parameters"]').click();
        const output = page.locator('[data-scientific-output]').first();
        assert.equal(await output.isChecked(), true);
        await output.uncheck(); await output.check();
        // Allow pending command/readback polling to observe the running controls.
        await page.locator('#experiment-duration').fill('10');
        await page.locator('[data-framework-field="experimentId"]').fill(JSON.stringify('browser-expiry'));
        await page.locator('[data-return-session]').click();
        await page.locator('[data-launch-experiment]').click();
        await page.locator('[data-reconcile-expiry]').waitFor();
        await page.waitForTimeout(1500);
        await page.locator('[data-reconcile-expiry]').click();
        await page.waitForFunction(() => document.querySelector('#experiment-monitor-fields')?.textContent.includes('completed'));
        await section('session');
        await page.locator('[data-prepare-experiment]').click();
        await page.locator('[data-session-navigate="parameters"]').click();
        assert.equal(await output.isChecked(), true);
        await output.uncheck(); await output.check(); await output.uncheck();
        await page.locator('#experiment-duration').fill('30');
        await page.locator('[data-framework-field="experimentId"]').fill(JSON.stringify('browser-outputless'));
        await page.locator('[data-return-session]').click();
        await page.locator('[data-launch-experiment]').click();
        await page.locator('[data-stop-experiment]').waitFor();
        assert.deepEqual(submittedData.filter(message => message.operation === 'start_launched_experiment').at(-1).parameters.scientific_outputs, []);
        assert.deepEqual(lastState.experiments.find(experiment => experiment.experiment_id === 'browser-outputless').scientific_outputs, []);
        await page.locator('[data-stop-experiment]').click();
        await page.getByRole('button', {name: 'Confirm Stop', exact: true}).click();
        await page.waitForFunction(() => document.querySelector('#experiment-monitor-fields')?.textContent.includes('completed'));
        await section('session');
        await page.locator('[data-stop-session]').click();
        await page.locator('[data-confirm-stop]').click();
        await page.locator('[data-release-session]').click();
        await page.locator('[data-confirm-stop]').click();
        await page.waitForFunction(() => document.querySelector('.launch-session-demo')?.disabled === false);
        await section('setup');
        await page.locator('.launch-session-demo').click();
        await page.locator('[data-start-session]').waitFor();
        assert.equal(submitted.filter(operation => operation === 'launch_session').length, 2);
        assert.equal(submitted.filter(operation => operation === 'start_launched_experiment').length, 3);
        assert.equal(submitted.filter(operation => operation === 'stop_launched_experiment').length, 2);
        assert.equal(submitted.filter(operation => operation === 'reconcile_launched_experiment_expiry').length, 1);
        await page.reload();
        await page.locator('#connection-state').filter({hasText: 'View Only'}).waitFor();
        assert.equal(submitted.filter(operation => operation === 'launch_session').length, 2);
        assert.equal(await page.locator('.launch-session-demo').isDisabled(), true);
        assert.equal(JSON.parse(await page.locator('.session-identity-grid textarea[data-configuration-string]').inputValue()), 'Browser Session');
        assert.equal(await page.locator('.session-identity-grid input[type="date"]').inputValue(), '2026-11-03');
        assert.equal(await page.locator('.session-identity-grid textarea[data-configuration-string]').getAttribute('readonly'), '');
      }
    }
    await page.goto(process.env.MICEBALL_DEMO_CURRENT_ORIGIN);
    await page.locator('.setup-disclosure').first().waitFor();
    for (const name of ['session', 'experiment', 'analysis', 'storage', 'services']) await section(name);
    await section('setup');
    await page.locator('#copy-protocol').click();
    await page.locator('#copy-step').click();
    await shot('current-demo-protocol-copy');
    await page.locator('#cancel-protocol').click();
    const discard = page.locator('dialog[aria-labelledby="discard-title"]');
    if (await discard.isVisible()) await discard.locator('button[value="discard"]').click();
    assert.deepEqual(errors, []);
    await writeFile(`${directory}/comparison.json`, JSON.stringify({screenshots: shots, submitted, result: 'PASS'}, null, 2));
    console.log('PASS: real Controller launch/start/acquisition/Stop/release/reuse; two-browser takeover; reconnect without replay; matched workspaces, Parameters, drawers, dialogs and navigation in both themes and viewports');
  } catch (error) {
    await shot('failure');
    console.error('Browser errors:', errors, '\nConnection:', await page.locator('#connection-state').textContent().catch(() => ''), '\nSetup:', await page.locator('.setup-demo-note').textContent().catch(() => ''));
    throw error;
  } finally { await browser.close(); }
}
