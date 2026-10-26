import { devices, operations } from './protocol-demo.mjs';
import { executionContext } from './session-context.mjs';
import { selectedStepContext, monitoredExperiment } from './session-demo.mjs';
import { experimentView } from './experiment-demo.mjs';

// Output examples only, not device SDK operations or authoritative readiness.
export const validationExamples = Object.freeze({ orca: 'image', logitech: 'image', extra: 'image', stage: 'plot', reward: 'actuator', display: 'none' });

export function deviceValidationEligibility(state, deviceId) {
  const context = executionContext(state);
  const device = devices.find(item => item.id === deviceId);
  const { step, record } = selectedStepContext(state);
  const { monitor, record: running } = monitoredExperiment(state);
  const maximumSeconds = context.sessionValues?.maxDeviceValidationSeconds;
  let reason = '';
  if (!state.activeSession) reason = 'Launch a demonstration Session first.';
  else if (!device || !context.selectedDevices.includes(deviceId)) reason = 'Device is outside the fixed Session pool.';
  else if (!step || operations.find(operation => operation.id === step.operation)?.type !== 'Experiment' || !experimentView(state, step, record).configuration.participants.includes(deviceId)) reason = 'Select a participating Experiment device in Session.';
  else if (!device.available) reason = 'This fixture reports the device unavailable; no activation is simulated.';
  else if (!(deviceId in validationExamples)) reason = 'No supported device-function Validation fixture is available.';
  else if (!Number.isFinite(maximumSeconds) || maximumSeconds <= 0) reason = 'No positive maximum Device Validation duration was captured. Configure it in Setup before launching a new demonstration Session.';
  else if (running?.status === 'running' && monitor.configuration.participants.includes(deviceId)) reason = 'This device participates in a running Experiment. Compatible concurrent use is not established by the demo; no Validation activation is simulated and the Experiment is unchanged.';
  return { device, maximumSeconds, output: validationExamples[deviceId], reason, eligible: !reason };
}

export function startDeviceValidation(state, deviceId, nowMs) {
  const context = executionContext(state);
  if (context.deviceValidation?.status === 'running') throw new Error('Stop the current device Validation demonstration first.');
  const eligibility = deviceValidationEligibility(state, deviceId);
  context.deviceValidation = { deviceId, deviceName: eligibility.device?.name || deviceId, output: eligibility.output,
    maximumSeconds: eligibility.maximumSeconds, status: eligibility.eligible ? 'running' : 'not-started', reason: eligibility.reason, startedAtMs: nowMs, elapsedSeconds: 0, updates: 0 };
  return context.deviceValidation;
}

export function stopDeviceValidation(state, reason = 'manual') {
  const context = executionContext(state), validation = context.deviceValidation;
  if (!validation) return;
  if (validation.status === 'running') {
    validation.status = 'stopped'; validation.endedBy = reason;
    context.lastDeviceValidation = { ...validation };
  }
  delete context.deviceValidation;
  return validation;
}

export function tickDeviceValidation(state, nowMs) {
  const validation = executionContext(state).deviceValidation;
  if (validation?.status !== 'running') return validation;
  validation.elapsedSeconds = Math.max(0, (nowMs - validation.startedAtMs) / 1000);
  if (validation.elapsedSeconds >= validation.maximumSeconds) {
    validation.elapsedSeconds = validation.maximumSeconds;
    return stopDeviceValidation(state, 'maximum-duration');
  }
  validation.updates++;
  return validation;
}
