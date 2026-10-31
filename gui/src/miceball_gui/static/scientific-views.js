import './output-panels.js';
import { state } from './protocol-setup.js';
import { selectedStepContext, monitoredExperiment, requestExperimentStop, finishExperimentStop } from './session-demo.mjs';
import { operations } from './protocol-demo.mjs';
import { traceExamples, distributionExample, scientificImageExample } from './output-examples.mjs';
import { escapeText as escape, executionIdentity, navigate } from './gui-presentation.js';
import { confirmStop } from './stop-confirmation.mjs';
import { executionContext } from './session-context.mjs';
import { tickDeviceValidation, stopDeviceValidation } from './device-validation-demo.mjs';
import { createExperimentParameterDrawer } from './experiment-parameter-drawer.js';

const experimentPanel = document.querySelector('#panel-experiment');
const renderParameters = createExperimentParameterDrawer(experimentPanel, state);
const analysisPanel = document.querySelector('#panel-analysis');
let validationTimer = null;

function outputPanel(id, title, content, caption) {
  return `<section class="output-panel" id="${id}" data-output-title="${escape(title)}" aria-label="${escape(title)}"><header><h3>${escape(title)}</h3><button type="button" data-expand-output aria-expanded="false" aria-label="Expand ${escape(title)}">Expand ↗</button></header><div class="output-content">${content}</div><p class="output-caption">${escape(caption)}</p></section>`;
}
function tracePlot(id) {
  return `<div class="plot-legend">${traceExamples.map((series, index) => `<label><input type="checkbox" data-trace-toggle="${id}-${index}" checked><span style="color:${series.color}">●</span>${series.name}</label>`).join('')}</div><svg class="demo-plot" viewBox="0 0 500 220" role="img" aria-label="Fixed illustrative activity traces"><rect class="plot-surface" x="0" y="0" width="500" height="220"/>${[45,85,125,165].map(y => `<path class="plot-grid" d="M42 ${y}H480"/>`).join('')}${[42,150,260,370,480].map(x => `<path class="plot-grid" d="M${x} 20V182"/>`).join('')}<path class="plot-axis" d="M42 20V182H480"/>${traceExamples.map((series, index) => `<polyline data-trace="${id}-${index}" points="${series.points.map((y, x) => `${45 + x * 22.5},${y}`).join(' ')}" fill="none" stroke="${series.color}" stroke-width="2.5"/>`).join('')}<text class="plot-text" x="190" y="211">Example samples</text><text class="plot-text" x="8" y="34">a.u.</text><text class="plot-text" x="38" y="199">0</text><text class="plot-text" x="467" y="199">20</text></svg>`;
}
function distributionPlot() {
  return `<svg class="demo-plot" viewBox="0 0 500 220" role="img" aria-label="Fixed illustrative distribution"><rect class="plot-surface" width="500" height="220"/>${[45,85,125,165].map(y => `<path class="plot-grid" d="M42 ${y}H480"/>`).join('')}<path class="plot-axis" d="M42 20V182H480"/>${distributionExample.map((height, index) => `<rect x="${53 + index * 41}" y="${182 - height}" width="29" height="${height}" rx="2" fill="#4c91c4"/>`).join('')}<text class="plot-text" x="181" y="211">Example value bins</text><text class="plot-text" x="8" y="34">count</text></svg>`;
}
function imageMarkup(interactive = false) {
  return `${interactive ? '<label class="roi-example-control">Illustrative selection <select aria-label="Example ROI"><option>Example ROI 1</option><option>Example ROI 2</option><option>Example ROI 3</option></select><span class="roi-example-label">Example ROI 1 selected</span></label>' : ''}<img class="scientific-image" src="${scientificImageExample}" alt="Synthetic fluorescence-style field; not acquired scientific data">`;
}

function renderExperiment() {
  const { monitor, record } = monitoredExperiment(state);
  const identity = monitor?.identity || executionIdentity(state);
  const information = [
    ['Animal', identity.animal], ['Session', identity.name], ['Experiment', monitor?.name || 'No demonstration launched'],
    ['Attempt', monitor?.attemptId || 'No demonstration attempt'],
    ['Status', record ? record.stopRequested ? 'Stop requested (demo)' : `${record.status} (demo)` : 'Preview only'], ['Elapsed time', 'Not measured'],
    ['Planned duration', monitor ? `${monitor.configuration.durationSeconds} s` : 'Not selected'],
  ];
  // Keep output DOM nodes alive when monitoring context changes or tabs are revisited.
  if (!experimentPanel.querySelector('.experiment-output-grid')) {
    experimentPanel.innerHTML = `<h2 id="heading-experiment" class="visually-hidden">Experiment</h2><div class="view-heading"><div><h2>Experiment</h2><p>Simulated monitoring · no acquisition or processing</p></div><button type="button" data-science-session>Back to Session</button></div><div class="experiment-output-grid"><div class="experiment-left"><section class="experiment-monitor-information"><dl id="experiment-monitor-fields"></dl><div id="experiment-monitor-progress"></div></section>${outputPanel('experiment-image', 'Live image · simulated', imageMarkup(), 'Fixed synthetic image example; no camera connection. Image colors do not change with theme.')}</div><div class="experiment-right">${outputPanel('experiment-plot-1', 'Plot 1', tracePlot('experiment'), 'Fixed illustrative traces, not real-time scientific measurements.')}${outputPanel('experiment-plot-2', 'Plot 2', distributionPlot(), 'Application-defined output surface · fixed demonstration values.')}</div></div>`;
  }
  experimentPanel.querySelector('#experiment-monitor-fields').innerHTML = information.map(([label, value]) => `<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('');
  experimentPanel.querySelector('#experiment-monitor-progress').innerHTML = record?.status === 'running' ? record.stopRequested
    ? '<div class="experiment-stop-pending" role="status"><strong>Normal Stop requested · local demonstration</strong><p>No distributed cleanup or preservation has been confirmed. The mock run remains pending until the local scenario is finished.</p><button type="button" data-finish-experiment-stop>Complete stop simulation</button></div>'
    : '<label>Simulated progress<progress aria-label="Simulated Experiment progress"></progress></label><button type="button" class="stop-experiment-demo" data-stop-experiment>Stop Experiment <small>Normal Stop · browser-local demonstration</small></button><p>No real stop command, cleanup or preservation is performed.</p>'
    : record?.results.at(-1)?.origin === 'Simulated Normal Stop'
      ? '<p role="status">Local Normal Stop demonstration finished; outputs are retained. No real distributed cleanup or preservation is confirmed.</p>'
      : '<p>Launch is available only in Session. Scientific output shown below is illustrative, including before any demonstration launch.</p>';
  const lastValidation = executionContext(state).lastDeviceValidation;
  if (lastValidation) experimentPanel.querySelector('#experiment-monitor-progress').insertAdjacentHTML('beforeend', `<p class="validation-ended" role="status">Device Validation for ${escape(lastValidation.deviceName)} ended: ${lastValidation.endedBy === 'maximum-duration' ? 'configured maximum duration reached' : 'manual Stop Validation'}. Browser-local only; physical cleanup remains unverified.</p>`);
  renderDeviceValidation();
  // Restore the user's visibility choice after the validation visibility sweep,
  // and refresh the read-only snapshot on every Experiment lifecycle render.
  if (!executionContext(state).deviceValidation) renderParameters();
}

function renderDeviceValidation() {
  const validation = executionContext(state).deviceValidation;
  let panel = experimentPanel.querySelector('#device-validation-view');
  if (!panel) {
    panel = document.createElement('section'); panel.id = 'device-validation-view'; panel.className = 'device-validation-view'; experimentPanel.append(panel);
  }
  for (const child of experimentPanel.children) child.hidden = child === panel ? !validation : !!validation;
  if (!validation) {
    clearInterval(validationTimer); validationTimer = null; panel.replaceChildren(); return;
  }
  if (panel.dataset.device !== validation.deviceId || !panel.children.length) {
    panel.dataset.device = validation.deviceId;
    const output = validation.output === 'image' ? `<section class="output-panel"><h3>Simulated camera preview</h3>${imageMarkup()}<p>Repeated fixed synthetic image, not a camera connection.</p></section>` : validation.output === 'plot' ? `<section class="output-panel"><h3>Simulated position/measurement preview</h3>${tracePlot('device-validation')}<p>Fixed illustrative traces, not sensor measurements.</p></section>` : `<section class="session-detail-box"><h3>${validation.output === 'actuator' ? 'Simulated actuator operation' : 'Device operation'}</h3><p>${validation.output === 'actuator' ? 'Water-delivery operation is represented by status only. No delivery, pulse command or physical action occurs.' : 'No visualization is declared for this device fixture.'}</p></section>`;
    panel.innerHTML = `<div class="view-heading"><div><h2>Device Validation · simulation</h2><p>${escape(validation.deviceName)} · ${escape(validation.deviceId)}</p></div><button type="button" data-science-session>Session</button></div><p class="view-notice">Device-function operation, not readiness-only checking and not a scientific Validation protocol step. No real activation, recording, reservation or safety confirmation. Actual readiness and ownership require future framework integration.</p><p id="device-validation-status" role="status"></p><p id="device-validation-elapsed"></p><button type="button" class="stop-validation-demo" data-stop-validation>Stop Validation</button><button type="button" data-close-validation>Return to Experiment</button><div id="device-validation-output">${output}</div>`;
  }
  const active = validation.status === 'running';
  panel.querySelector('#device-validation-status').textContent = active ? `Active simulated device operation · real readiness/ownership unverified${validation.notice ? ` · ${validation.notice}` : ''}` : `Validation not started: ${validation.reason}`;
  panel.querySelector('#device-validation-elapsed').textContent = active ? `Simulated elapsed: ${validation.elapsedSeconds.toFixed(1)} s · Configured maximum: ${validation.maximumSeconds} s · Preview update: ${validation.updates}` : 'No device activation or Experiment change was simulated.';
  panel.querySelector('[data-stop-validation]').hidden = !active;
  panel.querySelector('[data-close-validation]').hidden = active;
  panel.querySelector('#device-validation-output').hidden = !active;
  if (active && !validationTimer) validationTimer = setInterval(() => {
    tickDeviceValidation(state, performance.now());
    if (!executionContext(state).deviceValidation) renderExperiment();
    else renderDeviceValidation();
  }, 500);
  if (!active) { clearInterval(validationTimer); validationTimer = null; }
}

function renderAnalysis() {
  if (!analysisPanel.querySelector('.analysis-output-grid')) {
    const metrics = '<table class="example-metrics"><caption>Illustrative numerical results</caption><thead><tr><th>Example metric</th><th>Value</th></tr></thead><tbody><tr><td>Regions</td><td>14</td></tr><tr><td>Quality score</td><td>0.87</td></tr><tr><td>Selected examples</td><td>4</td></tr><tr><td>Result status</td><td>Demonstration only</td></tr></tbody></table>';
    analysisPanel.innerHTML = `<h2 id="heading-analysis" class="visually-hidden">Analysis</h2><div class="view-heading"><div><h2>Analysis</h2><p id="analysis-context"></p></div><button type="button" data-science-session>Back to Session</button></div><p class="view-notice">Generic output surfaces with fictional examples, not mandatory Analysis outputs. No algorithms or code execution. Existing result/review actions remain in Session.</p><div class="analysis-output-grid">${outputPanel('analysis-traces', 'Activity traces · example', tracePlot('analysis'), 'Fixed trace data. Legend selections are local display choices.')}${outputPanel('analysis-image', 'Image / interaction · example', imageMarkup(true), 'Selection demonstration only. No ROI identification or neuron-selection algorithm.')}${outputPanel('analysis-metrics', 'Numerical results / table · example', metrics, 'Fictional numbers, not computed scientific metrics.')}${outputPanel('analysis-distribution', 'Distribution · example', distributionPlot(), 'Application-defined output example. Other applications may use different panel contents.')}</div>`;
  }
  const { step, record } = selectedStepContext(state);
  const isAnalysis = step && operations.find(operation => operation.id === step.operation)?.type === 'Analysis';
  const retainedInput = record?.recordedInputs?.findLast(input => input.outcome === 'accepted');
  const inputContext = record?.recordingSelection ? ` · Selected input: ${record.recordingSelection.selection.name} (${record.recordingSelection.review}; no real processing)` : record?.status === 'satisfied' && retainedInput ? ` · Retained accepted input: ${retainedInput.selection.name} (simulated; no real processing)` : '';
  analysisPanel.querySelector('#analysis-context').textContent = isAnalysis ? `Session selection: ${step.name} · ${record.status === 'satisfied' ? 'Satisfied using previous recording (simulated acceptance)' : 'output examples only'}${inputContext}` : 'No Analysis step selected. Select one in Session; generic examples remain available for visual review.';
}

for (const panel of [experimentPanel, analysisPanel]) {
  panel.addEventListener('click', event => {
    if (event.target.closest('[data-stop-validation], [data-close-validation]')) {
      stopDeviceValidation(state); renderExperiment(); return;
    }
    if (event.target.closest('[data-science-session]')) navigate('session');
    if (event.target.closest('[data-stop-experiment], [data-finish-experiment-stop]')) {
      try {
        if (event.target.closest('[data-stop-experiment]')) {
          confirmStop('Experiment', () => {
            try { requestExperimentStop(state); renderExperiment(); }
            catch (error) { experimentPanel.querySelector('#experiment-monitor-progress').textContent = error.message; }
          });
          return;
        }
        else finishExperimentStop(state);
        renderExperiment();
      } catch (error) { experimentPanel.querySelector('#experiment-monitor-progress').textContent = error.message; }
    }
  });
  panel.addEventListener('change', event => {
    const control = event.target;
    if (control.dataset.traceToggle) panel.querySelector(`[data-trace="${control.dataset.traceToggle}"]`).style.display = control.checked ? '' : 'none';
    if (control.matches('.roi-example-control select')) panel.querySelector('.roi-example-label').textContent = `${control.value} selected`;
  });
}
document.addEventListener('gui-section-changed', event => {
  if (event.detail === 'experiment') renderExperiment();
  if (event.detail === 'analysis') renderAnalysis();
});
renderExperiment();
renderAnalysis();
