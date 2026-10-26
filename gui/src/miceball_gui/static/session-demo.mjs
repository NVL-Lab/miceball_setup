// Presentation scenarios only: no execution, dependency policy or scientific results.
import { clone, declaredCoverage, operations } from './protocol-demo.mjs';
import { experimentView, experimentIssues, captureExperiment } from './experiment-demo.mjs';
import { executionContext, executionProtocol, executionSteps } from './session-context.mjs';

export function freeOperationChoices(state) {
  const context = executionContext(state);
  return operations.map(operation => {
    const missing = declaredCoverage(operation.required, context.selectedDevices).filter(row => !row.providers.length).map(row => row.capability);
    return { operation, missing, compatible: missing.length === 0 };
  });
}

export function prepareFreeOperation(state, operationId) {
  const context = executionContext(state);
  if (!state.activeSession || context.protocolId !== null) throw new Error('Launch a Free Mode demonstration Session first.');
  const choice = freeOperationChoices(context).find(item => item.operation.id === operationId);
  if (!choice?.compatible) throw new Error('Operation requirements are not compatible with this Session device pool.');
  const occurrence = Object.freeze({ ...clone(choice.operation), id: `free-${context.freeOperations.length + 1}`, operation: operationId, mandatory: true,
    required: Object.freeze([...choice.operation.required]), optional: Object.freeze([...choice.operation.optional]), configuration: '' });
  context.freeOperations.push(occurrence);
  sessionProgress(context).selectedId = occurrence.id;
  return occurrence;
}

export function sessionProgress(state) {
  state = executionContext(state);
  const protocol = executionProtocol(state);
  const steps = executionSteps(state);
  state.sessionDemo ??= {};
  const progress = state.sessionDemo[state.protocolId] ??= { selectedId: null, steps: {} };
  steps.forEach((step, index) => {
    if (progress.steps[step.id]) return;
    const completed = !!protocol && index < 2 && (step.mandatory || state.included.includes(step.id));
    progress.steps[step.id] = {
      status: completed ? 'completed' : index === 2 ? 'ready' : 'not-started',
      results: completed ? [{ name: step.name, operation: step.operation, summary: 'Illustrative existing result — no scientific artifact.', origin: 'Initial mock scenario' }] : [],
      history: [completed ? 'Illustrative completed result supplied by the mock scenario; nothing was executed.' : 'No demonstration run yet.'],
      reviewReason: '',
      attempts: [],
    };
  });
  if (!steps.some(step => step.id === progress.selectedId)) progress.selectedId = steps.find((step, index) => index >= 2 && (step.mandatory || state.included.includes(step.id)))?.id || steps[0]?.id;
  return progress;
}

export function sessionStepView(state, step) {
  state = executionContext(state);
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
  const supports = { run: !!operation, load: !!operation?.recordedInput, skip: !step.mandatory };
  const running = Object.values(progress.steps).some(item => item.status === 'running');
  const actions = [];
  if (included && status !== 'skipped' && status !== 'running' && ready && !running && operation) {
    actions.push(record.results.length || status === 'error' ? 'repeat' : 'run');
    // Fixture-declared input support, never scientific suitability inferred from a file.
    if (supports.load) actions.push('load');
    if (supports.load && record.recordingSelection?.review === 'unreviewed') actions.push('accept-recording', 'reject-recording');
  }
  if (included && status === 'needs-review' && (record.results.length || record.recordedInputs?.some(input => input.outcome === 'accepted')) && !running) actions.push('validate');
  if (included && !step.mandatory && !running && !['completed', 'satisfied', 'needs-review', 'skipped'].includes(status)) actions.push('skip');
  if (status === 'running') actions.push('complete', 'error');
  return { record, status, stopPending: !!record.stopRequested, operation, experiment, issues, supports, required, optional, ready, included, actions, running };
}

export function selectedStepContext(state) {
  state = executionContext(state);
  const protocol = executionProtocol(state);
  const progress = sessionProgress(state);
  const step = executionSteps(state).find(item => item.id === progress.selectedId);
  return { protocol, step, record: step ? progress.steps[step.id] : null };
}

export function selectRecording(state, stepId, selection) {
  const step = executionSteps(state).find(item => item.id === stepId);
  if (!step || !sessionStepView(state, step).actions.includes('load')) throw new Error('This occurrence does not currently support recorded-input selection.');
  if (!selection?.name || !['file', 'folder'].includes(selection.kind) || !selection.entries?.length) throw new Error('Choose a file or a nonempty recording folder.');
  const record = sessionProgress(state).steps[stepId];
  record.recordingSelectionSequence = (record.recordingSelectionSequence || 0) + 1;
  record.recordingSelection = { id: `${stepId}-input-${record.recordingSelectionSequence}`, selection: clone(selection), review: 'unreviewed' };
  // Selection is not an execution attempt, result, suitability decision or history event.
  return record.recordingSelection;
}

export function clearRecordingSelection(state, stepId) {
  const record = sessionProgress(state).steps[stepId];
  if (record) delete record.recordingSelection;
}

export function actOnSessionStep(state, stepId, action) {
  state = executionContext(state);
  const protocol = executionProtocol(state);
  const step = executionSteps(state).find(item => item.id === stepId);
  if (!step) throw new Error('Select a current protocol step.');
  const view = sessionStepView(state, step);
  if (!view.actions.includes(action)) throw new Error('This demonstration action is not available for the selected step.');
  const record = view.record;
  if (action === 'load') throw new Error('Select a recording first, then choose an explicit simulated scientific-application outcome.');
  if (action === 'run' || action === 'repeat') {
    if (view.experiment) captureExperiment(state, step, record);
    record.attempts ??= [];
    record.attempts.push({ id: `${step.id}-attempt-${record.attempts.length + 1}`, status: 'running' });
    if (view.experiment) state.experimentMonitor.attemptId = record.attempts.at(-1).id;
    record.status = 'running';
    record.history.push(action === 'repeat' ? 'Repeat simulation started; earlier mock results retained.' : 'Run simulation started; no framework command sent.');
  } else if (action === 'complete') {
    if (record.attempts?.length) record.attempts.at(-1).status = 'completed';
    if (view.experiment) record.stopRequested = false;
    record.status = 'completed';
    record.reviewReason = '';
    record.results.push({ name: step.name, operation: step.operation, attemptId: record.attempts?.at(-1)?.id, summary: 'Illustrative result only — no data acquired or processed.', origin: 'Completed simulation' });
    record.history.push('Simulation completed; a new mock result was added without replacing earlier results.');
  } else if (action === 'accept-recording' || action === 'reject-recording') {
    const input = record.recordingSelection;
    const accepted = action === 'accept-recording';
    record.recordedInputs ??= [];
    record.recordedInputs.push({ id: `${step.id}-input-review-${record.recordedInputs.length + 1}`, inputId: input.id, selection: clone(input.selection), outcome: accepted ? 'accepted' : 'rejected' });
    input.review = accepted ? 'accepted' : 'rejected';
    if (accepted) { record.status = 'satisfied'; record.reviewReason = ''; }
    record.history.push(`Simulated scientific-application ${accepted ? 'acceptance' : 'rejection'} of previous recording “${input.selection.name}”. ${accepted ? 'Satisfied using previous recording; no new execution, acquisition or scientific output.' : 'Existing execution status and results are unchanged.'} No real suitability check, import or processing.`);
  } else if (action === 'validate') {
    record.status = record.reviewOutcome || 'completed';
    record.reviewReason = '';
    record.history.push('Experimenter confirmed the existing mock result remains acceptable. No Controller acceptance or persistence.');
  } else if (action === 'skip') {
    record.status = 'skipped';
    record.history.push('Optional step skipped in this preview; Setup inclusion and earlier mock results are unchanged.');
  } else if (action === 'error') {
    if (record.attempts?.length) record.attempts.at(-1).status = 'error';
    if (view.experiment) record.stopRequested = false;
    record.status = 'error';
    record.history.push('Simulated error: no new result produced. Earlier mock results are retained.');
  }
  // One review mechanism for repeats, first completions and replacement results.
  if (protocol && ['repeat', 'complete', 'accept-recording'].includes(action)) {
    const progress = sessionProgress(state);
    const change = { repeat: 'was repeated', complete: 'was completed', 'accept-recording': 'was satisfied using a previous recording (simulated acceptance)' }[action];
    protocol.steps.slice(protocol.steps.indexOf(step) + 1).forEach(later => {
      const downstream = progress.steps[later.id];
      if (!later.mandatory && !state.included.includes(later.id)) return;
      if ((!downstream.results.length && !downstream.recordedInputs?.some(input => input.outcome === 'accepted')) || !['completed', 'satisfied', 'needs-review'].includes(downstream.status)) return;
      if (downstream.status !== 'needs-review') downstream.reviewOutcome = downstream.status;
      downstream.status = 'needs-review';
      downstream.reviewReason = `Earlier step “${step.name}” ${change} in this design simulation. Its existing result is retained; this is not automatic scientific invalidation.`;
      downstream.history.push(downstream.reviewReason);
    });
  }
  return sessionStepView(state, step);
}

export function monitoredExperiment(state) {
  state = executionContext(state);
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
  state = executionContext(state);
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
