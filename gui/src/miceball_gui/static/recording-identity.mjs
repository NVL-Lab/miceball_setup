// Only browser-provided metadata is copied; File contents are never accessed.
export function describeRecordingSelection(files, kind) {
  const entries = Array.from(files, file => ({ name: file.name, relativePath: file.webkitRelativePath || null, size: file.size, lastModified: file.lastModified }));
  if (!entries.length) return null;
  const name = kind === 'folder' ? entries[0].relativePath?.split('/')[0] || 'Selected folder' : entries[0].name;
  return { kind, name, entries };
}
