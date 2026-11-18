import { clone, operations } from './protocol-demo.mjs';
import { experimentView, updateExperiment } from './experiment-demo.mjs';
import { selectedStepContext, sessionProgress } from './session-demo.mjs';
import { activeParameterSnapshot } from './experiment-parameters.mjs';

export function selectParameterContext(state, context) {
  // This descriptor locates existing working objects; it never owns configuration.
  state.parameterContext = context;
}

export function resolveParameterContext(state) {
  const context = state.parameterContext || {kind: state.activeSession ? 'session' : 'setup', origin: state.activeSession ? 'session' : 'setup'};
  if (context.kind === 'experiment') {
    const snapshot = activeParameterSnapshot(state);
    return snapshot ? {kind: 'experiment', step: {name: snapshot.name}, configuration: snapshot.configuration, readOnly: true,
      source: snapshot.source, origin: 'experiment', devices: state.activeSession?.selectedDevices || [], update() { throw new Error('Executed parameters are read-only.'); }} : null;
  }
  if (context.kind === 'session') {
    if (state.connected && !state.activeSession) return null;
    const {step, record} = selectedStepContext(state);
    if (!step || operations.find(item => item.id === step.operation)?.type !== 'Experiment') return null;
    const view = experimentView(state, step, record);
    return {...view, kind: 'session', step, record, source: view.readOnly ? 'Fixed executed configuration' : 'Working configuration in Session',
      origin: 'session', devices: state.activeSession?.selectedDevices || state.selectedDevices,
      update: patch => updateExperiment(state, step, record, patch)};
  }
  const step = context.kind === 'step' ? (context.getStep ? context.getStep() : context.step) : state.protocolId
    ? state.protocols.find(item => item.id === state.protocolId)?.steps.find(item => item.id === state.setupParameterStepId)
    : state.setupOperation;
  if (!step || operations.find(item => item.id === step.operation)?.type !== 'Experiment') return null;
  const saved = Boolean(step.definitionId || context.protected || context.kind === 'setup' && state.protocols.find(item => item.id === state.protocolId)?.protected);
  // Reuse the existing preparation records and Experiment working model, outside
  // activeSession. Merely opening a saved definition must not initialize defaults.
  if (saved) {
    return step.parameters ? {kind: context.kind, step, configuration: clone(step.parameters), readOnly: true, source: 'Immutable saved Step configuration',
      origin: context.origin || 'setup', devices: state.selectedDevices, update() { throw new Error('Copy the saved Step to edit parameters.'); }} : null;
  }
  if (context.kind !== 'step') state.sessionDemo ??= {};
  const preparation = {...state, activeSession: null};
  const records = context.kind === 'step' ? null : sessionProgress(preparation);
  if (records) records.steps[step.id] ??= {status: 'ready', results: [], history: [], attempts: [], reviewReason: ''};
  if (context.kind === 'step' && context.recordStep !== step) {
    context.recordStep = step;
    context.record = {status: 'ready'};
  }
  const record = context.kind === 'step' ? (context.record ??= {status: 'ready'}) : (records.steps[step.id] ??= {status: 'ready'});
  const workingRecord = {...record, status: 'ready', experiment: record.experiment ? {...record.experiment, editing: true} : undefined};
  const view = experimentView(preparation, step, workingRecord);
  record.experiment ??= workingRecord.experiment;
  if (context.kind === 'step') {
    const initialized = !step.parameters;
    step.parameters ??= view.configuration;
    record.experiment.working = workingRecord.experiment.working = step.parameters;
    if (initialized) context.changed?.();
  }
  const update = patch => {
    if (step.definitionId || context.protected) throw new Error('Copy the saved Step before editing.');
    updateExperiment(preparation, step, workingRecord, patch);
    if (context.kind === 'step') context.changed?.();
  };
  return {...view, kind: context.kind, configuration: workingRecord.experiment.working, step, record, source: context.kind === 'step' ? 'Protocol editor working configuration' : 'Future Session working configuration',
    origin: context.origin || 'setup', devices: state.selectedDevices, update};
}

