import { clone, devices } from './protocol-demo.mjs';
import { configurationIdentity } from './configuration-values.mjs';

export function applyControllerSnapshot(state, snapshot) {
  state.controllerSnapshot = clone(snapshot);
  const config = snapshot.configuration;
  if (!snapshot.status.session_id || !config) { state.activeSession = null; return; }
  if (state.activeSession?.sessionId !== snapshot.status.session_id) {
    const procedure = state.submittedProcedure?.name === config.protocol_reference ? state.submittedProcedure : null;
    const parameters = config.session_parameters || {};
    state.activeSession = { connected: true, sessionId: snapshot.status.session_id,
      protocolId: procedure?.id ?? (config.protocol_reference == null ? null : 'unavailable-protocol'), protocols: procedure ? [clone(procedure)] : [],
      included: procedure?.included || procedure?.steps.filter(step => step.mandatory).map(step => step.id) || [], selectedDevices: [], freeOperations: [], sessionDemo: {},
      identity: { name: parameters.name || snapshot.status.session_id, date: parameters.date || '',
        experimenter: parameters.experimenter || 'Not recorded', owner: parameters.experimenter || '',
        project: parameters.project || 'Not recorded', animal: parameters.animal || 'Not recorded' },
      sessionValues: clone(parameters), experimentTemplates: [], actions: state.actions };
  }
  const context = state.activeSession;
  const reserved = new Set((config.expected_runtime_participants || []).filter(p => p.component_type === 'acquisition_node').map(p => p.component_id));
  context.selectedDevices = (config.selected_devices || []).flatMap(declaration => {
    const matches = devices.filter(device => reserved.has(device.nodeId) && JSON.stringify(device.declaration) === JSON.stringify(declaration));
    return matches.length === 1 ? [matches[0].id] : [];
  });
  // The Controller descriptors, not working edits or elapsed browser time, define executed attempts.
  const progress = context.sessionDemo[context.protocolId] ??= { selectedId: null, steps: {} };
  for (const descriptor of snapshot.experiments || []) {
    const steps = context.protocols[0]?.steps || context.freeOperations;
    let step = steps.find(item => progress.steps[item.id]?.attempts?.some(attempt => attempt.id === descriptor.experiment_id));
    if (!step && state.submittedExperiment?.experimentId === descriptor.experiment_id) step = steps.find(item => item.id === state.submittedExperiment.stepId);
    if (!step) {
      step = { id: `framework-${descriptor.experiment_id}`, name: descriptor.experiment_id, operation: 'acquisition',
        mandatory: true, required: [], optional: [], description: 'Controller Experiment readback' };
      // A missing application checklist is not reconstructed from a name-only protocol reference.
      if (context.protocolId === null) context.freeOperations.push(step);
    }
    const record = progress.steps[step.id] ??= { results: [], history: [], attempts: [], reviewReason: '' };
    let attemptIndex = record.attempts.findIndex(attempt => attempt.id === descriptor.experiment_id);
    if (attemptIndex < 0) { attemptIndex = record.attempts.length; record.attempts.push({id: descriptor.experiment_id}); }
    record.frameworkExperimentId = descriptor.experiment_id;
    const events = (snapshot.status.experiment_lifecycle_evidence || []).filter(event => event.experiment_id === descriptor.experiment_id);
    const last = events.at(-1)?.event_type || '';
    record.status = snapshot.status.active_experiment_id === descriptor.experiment_id ? 'running'
      : last.includes('fail') ? 'error' : last.includes('stop') || last.includes('complete') ? 'completed' : 'unavailable';
    record.attempts[attemptIndex].status = record.status;
    record.history = (snapshot.status.experiment_lifecycle_evidence || []).filter(event => record.attempts.some(attempt => attempt.id === event.experiment_id))
      .map(event => `${event.experiment_id} / ${event.sequence}: ${event.event_type} · Session time ${event.session_time_s ?? 'unavailable'}`);
    const executed = descriptor.configuration;
    if (executed) {
      const configuration = { durationSeconds: executed.duration_s,
        participants: Object.entries(executed.participating_devices || {}).flatMap(([node, ids]) => ids.map(id => configurationIdentity(node, id))),
        values: Object.fromEntries(Object.entries(executed.device_configurations || {}).flatMap(([node, entries]) => Object.entries(entries).flatMap(([device, values]) => Object.entries(values).map(([key, value]) => [configurationIdentity(node, device, key), value])))),
        experimentId: descriptor.experiment_id, recordingBudgets: clone(executed.recording_budgets || {}),
        preservationBudget: executed.preservation_budget_bytes, outputs: clone(descriptor.scientific_outputs || []) };
      const bundle = record.experiment ??= { working: clone(configuration), startingConfiguration: clone(configuration), editing: false, templateId: '', attempts: [] };
      bundle.attempts[attemptIndex] = configuration;
      if (record.status === 'running') bundle.editing = false;
      if (record.status === 'running' || !context.experimentMonitor) context.experimentMonitor = {
        protocolId: context.protocolId, stepId: step.id, name: step.name, attemptId: descriptor.experiment_id,
        configuration, identity: context.identity };
    }
    progress.selectedId ??= step.id;
  }
}

function freezeSnapshot(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freezeSnapshot);
    Object.freeze(value);
  }
  return value;
}

// Before launch retain the editable preview; afterwards use one fixed context.
export function executionContext(state) {
  return state.activeSession || state;
}

export function executionProtocol(state) {
  const context = executionContext(state);
  return context.protocols.find(item => item.id === context.protocolId) || null;
}

export function executionSteps(state) {
  return executionProtocol(state)?.steps || executionContext(state).freeOperations || [];
}

export function launchSessionDemo(state, identity, sessionValues = {}) {
  if (state.connected) throw new Error('Connected launch requires Controller admission.');
  if (state.activeSession) throw new Error('A demonstration Session is already active. Reload to start another.');
  const protocol = state.protocols.find(item => item.id === state.protocolId);
  if (!protocol && state.protocolId !== null) throw new Error('Select a protocol or None before launching the demonstration Session.');
  const protocolId = protocol?.id ?? null;
  const progress = protocol ? state.sessionDemo?.[protocolId] : null;
  if (Object.values(progress?.steps || {}).some(record => record.status === 'running')) {
    throw new Error('Finish the running preview simulation before launching a demonstration Session.');
  }
  const context = { sessionDemo: progress ? { [protocolId]: clone(progress) } : {} };
  if (!protocol) context.freeOperations = [];
  const fixed = clone({ protocols: protocol ? [protocol] : [], protocolId, included: state.included,
    selectedDevices: state.selectedDevices, identity, sessionValues });
  for (const [key, value] of Object.entries(fixed)) {
    Object.defineProperty(context, key, { value: freezeSnapshot(value), enumerable: true });
  }
  for (const record of Object.values(context.sessionDemo[protocolId]?.steps || {})) {
    record.experiment?.attempts.forEach(freezeSnapshot);
  }
  // Reusable templates are a catalog, not the fixed execution configuration.
  if (state.experimentTemplates) context.experimentTemplates = state.experimentTemplates;
  state.activeSession = context;
  return context;
}
