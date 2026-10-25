// Fictional application data and browser-memory preparation state.
export const operations = [
  { id: 'initial', name: 'Initial imaging', type: 'Experiment', description: 'Acquire initial imaging for ROI identification.', required: ['imaging_camera'], optional: ['behavior_video'] },
  { id: 'roi', name: 'Suite2p ROI identification', type: 'Analysis', description: 'Identify ROIs using the application-supplied Suite2p operation.', required: [], optional: [] },
  { id: 'baseline', name: 'Baseline recording', type: 'Experiment', description: 'Record baseline activity.', required: ['imaging_camera'], optional: ['behavior_video'] },
  { id: 'holo', name: 'Holographic stimulation', type: 'Experiment', description: 'Optional holographic stimulation demonstration.', required: ['imaging_camera', 'holographic_stimulation'], optional: [] },
  { id: 'neurons', name: 'Neuron selection', type: 'Analysis', description: 'Select neurons for the cursor.', required: [], optional: [] },
  { id: 'calibrate', name: 'Cursor calibration', type: 'Analysis', description: 'Calibrate the neural cursor.', required: [], optional: [] },
  { id: 'loop', name: 'Closed-loop acquisition', type: 'Experiment', description: 'Run the application-supplied closed-loop operation.', required: ['imaging_camera', 'visual_stimulation', 'reward_delivery'], optional: ['behavior_video'] },
];
export const devices = [
  { id: 'orca', name: 'Camera (ORCA-Fusion)', detail: 'S/N 123456', capabilities: ['imaging_camera'], available: true },
  { id: 'display', name: 'Stimulus display (XB273U)', detail: '2560 × 1440', capabilities: ['visual_stimulation'], available: true },
  { id: 'reward', name: 'Reward solenoid (NI)', detail: 'NI-01', capabilities: ['reward_delivery'], available: true },
  { id: 'logitech', name: 'Camera (Logitech)', detail: 'USB-01', capabilities: ['behavior_video'], available: true },
  { id: 'behavior', name: 'Behavior module (NI)', detail: 'NI-02', capabilities: ['behavior_io'], available: false },
  { id: 'holograph', name: 'Holographic stimulator', detail: 'Holo-01', capabilities: ['holographic_stimulation'], available: false },
  { id: 'extra', name: 'Extra camera (USB)', detail: 'USB-02', capabilities: ['behavior_video'], available: true },
  { id: 'stage', name: 'Stage (ASI Tiger)', detail: 'S/N 987654', capabilities: ['positioning'], available: true },
];
export const clone = value => JSON.parse(JSON.stringify(value));
const freezeDefinition = value => Object.freeze({ ...value, required: Object.freeze([...value.required]), optional: Object.freeze([...value.optional]) });
export function preparedSteps(state, owner) {
  return state.definitions.filter(step => step.owner === null || step.owner === owner);
}
export function savedOccurrence(state, definitionId, id) {
  const definition = state.definitions.find(step => step.id === definitionId);
  if (!definition) throw new Error('Saved step not found.');
  return { ...clone(definition), id, definitionId };
}
export function copyStepToEdit(state, step, otherSteps = []) {
  const names = [...state.definitions, ...otherSteps].map(item => item.name.toLowerCase());
  const base = `${step.name} - copy`;
  let name = base, suffix = 2;
  while (names.includes(name.toLowerCase())) name = `${base} ${suffix++}`;
  const copy = clone(step);
  delete copy.definitionId;
  delete copy.owner;
  return { ...copy, name };
}
export function saveReusableStep(state, step, owner) {
  if (step.definitionId) throw new Error('Copy saved steps before editing.');
  const name = step.name.trim();
  if (!name || !operations.some(op => op.id === step.operation)) throw new Error('Provide a step name and scientific operation.');
  if (state.definitions.some(item => item.name.toLowerCase() === name.toLowerCase())) throw new Error('A saved step with this name already exists. Choose a unique name.');
  const id = `personal-step-${state.definitions.length}`;
  const definition = freezeDefinition({ ...clone(step), id, name, owner });
  state.definitions.push(definition);
  return savedOccurrence(state, id, step.id);
}
export function moveStep(steps, stepId, targetId, after = false) {
  if (stepId === targetId) return;
  const from = steps.findIndex(step => step.id === stepId);
  if (from < 0 || !steps.some(step => step.id === targetId)) return;
  const [step] = steps.splice(from, 1);
  const target = steps.findIndex(item => item.id === targetId);
  steps.splice(target + (after ? 1 : 0), 0, step);
}
export function assignCapability(step, kind, capability, selected) {
  step[kind] = step[kind].filter(value => value !== capability);
  if (selected) {
    step[kind].push(capability);
    const other = kind === 'required' ? 'optional' : 'required';
    step[other] = step[other].filter(value => value !== capability);
  }
}
export function createDemo() {
  const steps = operations.map((op, i) => ({ ...clone(op), id: `step-${i}`, operation: op.id, mandatory: op.id !== 'holo', configuration: '' }));
  const definitions = steps.map(step => freezeDefinition({ ...clone(step), id: `shared-${step.operation}`, owner: null }));
  steps.forEach(step => { step.definitionId = `shared-${step.operation}`; });
  return {
    definitions,
    protocols: [
      { id: 'cabmi', name: 'CaBMI Closed-Loop Protocol', description: 'Initial imaging, ROI identification, baseline recording, neuron selection, cursor calibration, and closed-loop acquisition. Includes optional holographic stimulation.', protected: false, steps },
      { id: 'reference', name: 'Lab reference — imaging', description: 'Protected laboratory reference. Copy to make a personal protocol.', protected: true, steps: clone(steps.slice(0, 3)) },
    ],
    templates: [
      { id: 'standard', protocol: 'cabmi', name: 'My Standard CaBMI Setup', description: 'Standard imaging, reward and visual stimulation. Holographic stimulation is skipped.', included: steps.filter(s => s.mandatory).map(s => s.id), devices: ['orca', 'display', 'reward', 'logitech'] },
      { id: 'holographic', protocol: 'cabmi', name: 'CaBMI with holography', description: 'Includes the optional holographic step; select a suitable demonstration device.', included: steps.map(s => s.id), devices: ['orca', 'display', 'reward', 'logitech'] },
      { id: 'reference-template', protocol: 'reference', name: 'Lab imaging defaults', description: 'Imaging-only demonstration defaults.', included: steps.slice(0, 3).map(s => s.id), devices: ['orca'] },
    ],
    protocolId: 'cabmi', templateId: '', included: steps.filter(s => s.mandatory).map(s => s.id), selectedDevices: ['orca', 'display', 'logitech', 'extra', 'stage'],
  };
}
export function selectProtocol(state, id) {
  state.protocolId = id;
  state.templateId = '';
  state.included = state.protocols.find(p => p.id === id).steps.filter(s => s.mandatory).map(s => s.id);
}
export function selectTemplate(state, id) {
  const template = state.templates.find(t => t.id === id && t.protocol === state.protocolId);
  state.templateId = template ? id : '';
  if (!template) return;
  const protocol = state.protocols.find(p => p.id === state.protocolId);
  state.included = protocol.steps.filter(s => s.mandatory || template.included.includes(s.id)).map(s => s.id);
  state.selectedDevices = [...template.devices];
}
export function coverage(state) {
  const protocol = state.protocols.find(p => p.id === state.protocolId);
  const steps = protocol.steps.filter(s => s.mandatory || state.included.includes(s.id));
  const required = [...new Set(steps.flatMap(s => s.required))];
  const optional = [...new Set(steps.flatMap(s => s.optional))].filter(c => !required.includes(c));
  const selected = devices.filter(d => state.selectedDevices.includes(d.id));
  const rows = capabilities => capabilities.map(capability => ({ capability, providers: selected.filter(d => d.capabilities.includes(capability)) }));
  return { required: rows(required), optional: rows(optional), unavailable: selected.filter(d => !d.available), skipped: protocol.steps.filter(s => !s.mandatory && !state.included.includes(s.id)).length };
}
export function saveProtocol(state, draft) {
  const existing = state.protocols.find(p => p.id === draft.id);
  if (existing?.protected) throw new Error('Copy protected references before editing.');
  const saved = clone(draft);
  // References are authoritative; occurrence-local edits cannot mutate a saved definition.
  saved.steps = saved.steps.map(step => step.definitionId ? savedOccurrence(state, step.definitionId, step.id) : step);
  if (existing) state.protocols[state.protocols.indexOf(existing)] = saved;
  else state.protocols.push(saved);
  selectProtocol(state, draft.id);
}
