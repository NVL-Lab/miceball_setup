// Controlled Controller readback for existing presentation workflows.
export function replyArtifactDestinations(socket, message) {
  if (message.operation !== 'list_artifact_destinations') return false;
  socket.send(JSON.stringify({type: 'result', id: message.id, result: {status: 'succeeded', outcome: {details: {
    storage_id: 'storage', default_destination_id: 'default', destinations: [{destination_id: 'default',
      name: 'Installation default', root: '/test-artifacts', enabled: true,
      validation: {status: 'unverified', available_bytes: null}}]}}}}));
  return true;
}
