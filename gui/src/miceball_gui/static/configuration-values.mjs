// Internal keys encode coordinates; framework requests retain the original names.
export const configurationIdentity = (...coordinates) => JSON.stringify(coordinates);

export function configurationNumber(text) {
  const value = Number(text);
  if (!String(text).trim() || !Number.isFinite(value)
      || (Number.isInteger(value) && !Number.isSafeInteger(value))
      || Object.is(value, -0)
      || (value === 0 && /[1-9]/.test(String(text).split(/[eE]/)[0]))) {
    throw new Error(`Numeric value ${text} cannot be represented faithfully by this GUI. Use a supported value or an authorized framework client.`);
  }
  return value;
}

export function parseConfigurationJSON(text) {
  return JSON.parse(text, (key, value, context) => {
    if (typeof value === 'number') {
      if (!context?.source) throw new Error('This browser cannot verify JSON numeric precision. Use a current browser.');
      configurationNumber(context.source);
    }
    return value;
  });
}

export function stringifyConfiguration(value) {
  return JSON.stringify(value, (key, item) => {
    if (typeof item === 'number') {
      if (Object.is(item, -0)) configurationNumber('-0');
      configurationNumber(String(item));
    }
    return item;
  });
}
