import { clone } from './protocol-demo.mjs';

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
