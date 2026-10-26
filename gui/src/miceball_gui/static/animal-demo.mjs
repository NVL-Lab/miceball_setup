// Fictional page-memory examples, not an authoritative animal catalog schema.
export function createAnimalCatalog() {
  return new Map([
    ['M1023', { animal_id: 'M1023', animal_name: 'Pip', species: 'Mus musculus', strain: 'C57BL/6J', sex: 'Male', date_of_birth: 'Sep 16, 2026', notes: '' }],
    ['M1041', { animal_id: 'M1041', animal_name: 'Juniper', species: 'Mus musculus', strain: 'BALB/cJ', sex: 'Female', date_of_birth: 'Aug 24, 2026', notes: 'Fictional demonstration animal.' }],
  ]);
}

export function saveAnimalDemo(catalog, values) {
  const key = `demo-animal-${catalog.size}`;
  catalog.set(key, { ...values });
  return key;
}
