// Internal keys encode coordinates; framework requests retain the original names.
export const configurationIdentity = (...coordinates) => JSON.stringify(coordinates);

export const scientificOutputIdentity = output => configurationIdentity(
  output.source_node_id, output.source_device_id, output.data_product_id);

// Compare JSON-like declarations without assigning meaning to object-key order.
export function configurationEqual(left, right) {
  if (left === right) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length
      && left.every((value, index) => configurationEqual(value, right[index]));
  }
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length
    && keys.every(key => Object.hasOwn(right, key) && configurationEqual(left[key], right[key]));
}

export function configurationNumber(text, integer = false) {
  const token = String(text).trim();
  const parts = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(token);
  let exactInteger = false;
  if (parts) {
    const fraction = parts[3] ?? parts[4] ?? '';
    const digits = (parts[2] || '') + fraction;
    // Compare decimal places with trailing zeros without expanding an exponent.
    const places = BigInt(fraction.length) - BigInt(parts[5] || '0');
    const zeros = BigInt(digits.length - digits.replace(/0+$/, '').length);
    exactInteger = !/[1-9]/.test(digits) || places <= zeros;
    if (integer && !exactInteger) {
      throw new Error(`Numeric value ${text} is not an exact integer. Enter an integer value.`);
    }
  }
  const value = parts ? Number(token) : NaN;
  if (!parts || !Number.isFinite(value)
      || (Number.isInteger(value) && (!Number.isSafeInteger(value) || !exactInteger))
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
