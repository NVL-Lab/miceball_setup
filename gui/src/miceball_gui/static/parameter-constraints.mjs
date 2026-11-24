import { configurationIdentity, configurationNumber } from './configuration-values.mjs';

export function configuredParameterValue(state, device, field, sessionId = null) {
  const configured = state.inventory?.[device.nodeId]?.configured_parameters;
  if (!device.available || !configured || configured.scope !== (sessionId ? 'session' : 'installation')
      || configured.session_id !== sessionId) return {available: false};
  if (!configured.values || !Object.hasOwn(configured.values, device.deviceId)) return {available: false};
  const values = configured.values[device.deviceId];
  if (!values || typeof values !== 'object' || Array.isArray(values)) return {available: false};
  if (!Object.hasOwn(values, field.name)) return {available: false, reason: 'Not specified in confirmed configuration; no explicit override'};
  try {
    if (parameterIssue(field, values[field.name])) return {available: false};
  } catch (_) { return {available: false}; }
  return {available: true, value: values[field.name]};
}

export function deviceParameterFields(node, device, definitions) {
  return Object.entries(definitions).map(([name, definition]) => {
    if (!['boolean', 'integer', 'number', 'string'].includes(definition.type)) throw new Error(`Unsupported declared parameter type for ${name}.`);
    return {
    id: configurationIdentity(node, device, name), name, label: name,
    adjustmentScope: definition.adjustment_scope || 'experimenter',
    type: definition.type === 'boolean' ? 'checkbox' : ['integer', 'number'].includes(definition.type) ? 'number' : 'text',
    integer: definition.type === 'integer', min: definition.minimum, max: definition.maximum,
    exclusiveMin: definition.exclusive_minimum, nullable: definition.nullable,
    nullDescription: typeof definition.null_description === 'string' && definition.null_description.trim()
      ? definition.null_description : 'Use the adapter-defined empty value',
    ...(Object.hasOwn(definition, 'allowed_values') ? {allowedValues: definition.allowed_values} : {}),
    };
  });
}

export function parameterIssue(field, value) {
  if (value === null && field.nullable) return '';
  if (field.type === 'number' && (typeof value !== 'number' || !Number.isFinite(value) || field.integer && !Number.isSafeInteger(value))
      || field.type === 'checkbox' && typeof value !== 'boolean'
      || field.type === 'text' && typeof value !== 'string') return `Invalid value for ${field.label}.`;
  if (field.type === 'number') {
    try { configurationNumber(String(value), Boolean(field.integer)); }
    catch (_) { return `Invalid value for ${field.label}.`; }
  }
  if (field.allowedValues && !field.allowedValues.includes(value)
      || field.min !== undefined && value < field.min || field.max !== undefined && value > field.max
      || field.exclusiveMin !== undefined && value <= field.exclusiveMin) return `Value violates the declared constraints for ${field.label}.`;
  return '';
}
