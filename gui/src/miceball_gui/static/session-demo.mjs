// Presentation scenarios only: no execution, dependency policy or scientific results.
import { declaredCoverage, operations } from './protocol-demo.mjs';
import { experimentView, experimentIssues, captureExperiment } from './experiment-demo.mjs';

export function sessionProgress(state) {
  const protocol = state.protocols.find(item => item.id === state.protocolId);
  state.sessionDemo ??= {};
  const progress = state.sessionDemo[protocol.id] ??= { selectedId: null, steps: {} };
  protocol.steps.forEach((step, index) => {
    if (progress.steps[step.id]) return;
    const completed = index < 2 && (step.mandatory || state.included.includes(step.id));
    progress.steps[step.id] = {
      status: completed ? 'completed' : index === 2 ? 'ready' : 'not-started',
      results: completed ? [{ name: step.name, operation: step.operation, summary: 'Illustrative existing result — no scientific artifact.', origin: 'Initial mock scenario' }] : [],
      history: [completed ? 'Illustrative completed result supplied by the mock scenario; nothing was executed.' : 'No demonstration run yet.'],
      reviewReason: '',
    };
  });
  if (!protocol.steps.some(step => step.id === progress.selectedId)) progress.selectedId = protocol.steps.find((step, index) => index >= 2 && (step.mandatory || state.included.includes(step.id)))?.id || protocol.steps[0]?.id;
  return progress;
}

export function sessionStepView(state, step) {
  const progress = sessionProgress(state);
  const record = progress.steps[step.id];
  const operation = operations.find(item => item.id === step.operation);
  const experiment = operation?.type === 'Experiment' ? experimentView(state, step, record) : null;
  const rows = capabilities => declaredCoverage(capabilities, experiment ? experiment.configuration.participants : state.selectedDevices);
  const required = rows(step.required), optional = rows(step.optional);
  const issues = experiment ? experimentIssues(state, step, experiment.configuration) : [];
  const ready = !issues.length && required.every(row => row.providers.some(device => device.available));
  const included = step.mandatory || state.included.includes(step.id);
  let status = record.status;
  if (!included) status = 'skipped';
  else if (!ready && ['ready', 'not-started'].includes(status)) status = 'unavailable';
  const supports = { run: !!operation, load: ['roi', 'calibrate'].includes(operation?.id), skip: !step.mandatory };
  const running = Object.values(progress.steps).some(item => item.status === 'running');
  const actions = [];
  if (included && status !== 'skipped' && status !== 'running' && ready && !running && operation) {
    actions.push(record.results.length || status === 'error' ? 'repeat' : 'run');
    // Illustrative application support, not a framework-wide result-loading contract.
    if (supports.load) actions.push('load');
  }
  if (included && status === 'needs-review' && record.results.length && !running) actions.push('validate');
  if (included && !step.mandatory && !running && !['completed', 'needs-review', 'skipped'].includes(status)) actions.push('skip');
  if (status === 'running') actions.push('complete', 'error');
  return { record, status, stopPending: !!record.stopRequested, operation, experiment, issues, supports, required, optional, ready, included, actions, running };
}

export function selectedStepContext(state) {
  const protocol = state.protocols.find(item => item.id === state.protocolId);
  const progress = sessionProgress(state);
  const step = protocol.steps.find(item => item.id === progress.selectedId);
  return { protocol, step, record: step ? progress.steps[step.id] : null };
}

export function actOnSessionStep(state, stepId, action) {
  const protocol = state.protocols.find(item => item.id === state.protocolId);
  const step = protocol.steps.find(item => item.id === stepId);
  if (!step) throw new Error('Select a current protocol step.');
  const view = sessionStepView(state, step);
  if (!view.actions.includes(action)) throw new Error('This demonstration action is not available for the selected step.');
  const record = view.record;
  if (action === 'run' || action === 'repeat') {
    if (view.experiment) captureExperiment(state, step, record);
    record.status = 'running';
    record.history.push(action === 'repeat' ? 'Repeat simulation started; earlier mock results retained.' : 'Run simulation started; no framework command sent.');
  } else if (action === 'complete' || action === 'load') {
    if (view.experiment) record.stopRequested = false;
    record.status = 'completed';
    record.reviewReason = '';
    record.results.push({ name: step.name, operation: step.operation, summary: 'Illustrative result only — no data acquired or processed.', origin: action === 'load' ? 'Simulated previous result' : 'Completed simulation' });
    record.history.push(action === 'load' ? 'Previous-result example loaded locally; no file accessed.' : 'Simulation completed; a new mock result was added without replacing earlier results.');
  } else if (action === 'validate') {
    record.status = 'completed';
    record.reviewReason = '';
    record.history.push('Experimenter confirmed the existing mock result remains acceptable. No Controller acceptance or persistence.');
  } else if (action === 'skip') {
    record.status = 'skipped';
    record.history.push('Optional step skipped in this preview; Setup inclusion and earlier mock results are unchanged.');
  } else if (action === 'error') {
    if (view.experiment) record.stopRequested = false;
    record.status = 'error';
    record.history.push('Simulated error: no new result produced. Earlier mock results are retained.');
  }
  // One review mechanism for repeats, first completions and replacement results.
  if (['repeat', 'complete', 'load'].includes(action)) {
    const progress = sessionProgress(state);
    const change = { repeat: 'was repeated', complete: 'was completed', load: 'loaded a replacement result' }[action];
    protocol.steps.slice(protocol.steps.indexOf(step) + 1).forEach(later => {
      const downstream = progress.steps[later.id];
      if (!later.mandatory && !state.included.includes(later.id)) return;
      if (!downstream.results.length || !['completed', 'needs-review'].includes(downstream.status)) return;
      downstream.status = 'needs-review';
      downstream.reviewReason = `Earlier step “${step.name}” ${change} in this design simulation. Its existing result is retained; this is not automatic scientific invalidation.`;
      downstream.history.push(downstream.reviewReason);
    });
  }
  return sessionStepView(state, step);
}

export function monitoredExperiment(state) {
  const monitor = state.experimentMonitor;
  return { monitor, record: monitor ? state.sessionDemo?.[monitor.protocolId]?.steps[monitor.stepId] : null };
}
export function requestExperimentStop(state) {
  const { record } = monitoredExperiment(state);
  if (!record || record.status !== 'running') throw new Error('No running demonstration Experiment to stop.');
  if (!record.stopRequested) {
    record.stopRequested = true;
    record.history.push('Normal Stop requested in the browser demo. No Controller command, cleanup or preservation confirmation.');
  }
  return record;
}
export function finishExperimentStop(state) {
  const { monitor, record } = monitoredExperiment(state);
  if (!record?.stopRequested || record.status !== 'running') throw new Error('Request a demonstration Normal Stop first.');
  // Reuse completion with the monitored protocol context, not the current UI selection.
  // Records are shared references; this does not navigate or create parallel state.
  actOnSessionStep({ ...state, protocolId: monitor.protocolId }, monitor.stepId, 'complete');
  const result = record.results.at(-1);
  result.origin = 'Simulated Normal Stop';
  result.summary = 'Local early-stop example only; no acquisition, distributed cleanup or preservation was performed.';
  record.history.push('Local Normal Stop scenario finished. Real cleanup and preservation remain unverified; earlier mock results and output views are retained.');
  return record;
}
