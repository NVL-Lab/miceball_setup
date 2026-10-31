import { clone, operations } from './protocol-demo.mjs';

export function activeParameterSnapshot(state) {
  const context = state.activeSession;
  if (!context) return null;
  const monitor = context.experimentMonitor;
  const monitoredRecord = monitor ? context.sessionDemo?.[monitor.protocolId]?.steps[monitor.stepId] : null;
  if (monitor && monitoredRecord?.status === 'running') {
    return { name: monitor.name, source: 'Fixed executing-attempt configuration', configuration: clone(monitor.configuration) };
  }
  const progress = context.sessionDemo?.[context.protocolId];
  const steps = context.protocols.find(item => item.id === context.protocolId)?.steps || context.freeOperations || [];
  const step = steps.find(item => item.id === progress?.selectedId);
  if (!step || operations.find(item => item.id === step.operation)?.type !== 'Experiment') return null;
  const record = progress.steps[step.id];
  const bundle = record?.experiment;
  if (!bundle) return null; // Reading the drawer must not create default configuration.
  const readOnly = record.status === 'running' || (!bundle.editing && bundle.attempts.length > 0);
  const configuration = readOnly ? bundle.attempts.at(-1) : bundle.working;
  return configuration ? { name: step.name, source: readOnly ? 'Fixed executed-attempt configuration' : 'Prepared configuration in the active Session', configuration: clone(configuration) } : null;
}
