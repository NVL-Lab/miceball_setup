// Controlled Controller readback for existing presentation workflows.
export function replyArtifactDestinations(socket, message) {
  if (message.operation === 'estimate_experiment_storage') {
    const {configuration, scientific_outputs, storage_location} = message.parameters;
    socket.send(JSON.stringify({type: 'result', id: message.id, instance_id: 'integrity-instance', result: {
      status: 'succeeded', outcome: {details: {configuration, scientific_outputs, storage_location,
        session_id: message.session_id, expected_bytes: null,
        recording: Object.keys(configuration.participating_devices || {}).map(node_id => ({node_id,
          valid: true, estimated_bytes: null, products: [], unavailable: ['No estimation metadata in this controlled fixture']})),
        preservation: {available: false, destinations: [], reason: 'Explicit preservation budget required'}}}}}));
    return true;
  }
  if (message.operation !== 'list_artifact_destinations') return false;
  socket.send(JSON.stringify({type: 'result', id: message.id, result: {status: 'succeeded', outcome: {details: {
    storage_id: 'storage', default_destination_id: 'default', destinations: [{destination_id: 'default',
      name: 'Installation default', root: '/test-artifacts', enabled: true,
      validation: {status: 'unverified', available_bytes: null}}]}}}}));
  return true;
}
