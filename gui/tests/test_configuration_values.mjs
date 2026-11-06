import {test} from 'node:test';
import assert from 'node:assert/strict';
import {configurationIdentity, scientificOutputIdentity, configurationEqual, configurationNumber, parseConfigurationJSON, stringifyConfiguration, configurationStringText, parseConfigurationString} from '../src/miceball_gui/static/configuration-values.mjs';

test('string representation preserves exact control characters, escapes and Unicode code units', () => {
  const cases = [['alpha\nbeta', '"alpha\\nbeta"'], ['alpha\rbeta', '"alpha\\rbeta"'],
    ['alpha\r\nbeta', '"alpha\\r\\nbeta"'], ['plain & "quoted"', '"plain & \\"quoted\\""'],
    ['', '""'], ['\\n', '"\\\\n"'], ['\0\t\b\f\v\x1b\x7f\x85', '"\\u0000\\t\\b\\f\\u000b\\u001b\\u007f\\u0085"'],
    ['\u03a9\ud83d\ude00\u2028\u2029\ufeff\ud800', '"\\u03a9\\ud83d\\ude00\\u2028\\u2029\\ufeff\\ud800"']];
  for (const [value, text] of cases) {
    assert.equal(configurationStringText(value), text);
    assert.equal(parseConfigurationString(text), value);
    assert.match(text, /^[\x20-\x7e]*$/);
  }
});

test('invalid string edits are explicit drafts, not accepted string values', () => {
  for (const text of ['unquoted', '"alpha\nbeta"', '"alpha\rbeta"', '"alpha\r\nbeta"', 'null', 'true', '42', '{}', '[]']) {
    assert.throws(() => parseConfigurationString(text));
    assert.equal(configurationStringText({invalidString: text}), text);
  }
});

test('scientific-output identity uses exact coordinates independent of record property order', () => {
  const canonical = {source_device_id: 'b/c', source_node_id: 'a', data_product_id: 'frames'};
  const reordered = {data_product_id: 'frames', source_node_id: 'a', source_device_id: 'b/c'};
  assert.equal(scientificOutputIdentity(canonical), scientificOutputIdentity(reordered));
  const distinct = [canonical, {source_node_id: 'a/b', source_device_id: 'c', data_product_id: 'frames'},
    {...canonical, data_product_id: 'frames/preview'}, {...canonical, source_device_id: 'b/c '},
    {source_node_id: '__proto__', source_device_id: 'quotes" & <device>', data_product_id: ''}];
  assert.equal(new Set(distinct.map(scientificOutputIdentity)).size, distinct.length);
  assert.deepEqual(JSON.parse(scientificOutputIdentity(canonical)), ['a', 'b/c', 'frames']);
});

test('configuration equality preserves declaration values, array order, null and own-property identity', () => {
  const first = JSON.parse('{"__proto__":{"name":"x","products":[{"id":"frames","schema":{}}]},"enabled":false,"capabilities":null}');
  const second = JSON.parse('{"capabilities":null,"enabled":false,"__proto__":{"products":[{"schema":{},"id":"frames"}],"name":"x"}}');
  assert.equal(configurationEqual(first, second), true);
  assert.equal(configurationEqual(first, {...second, capabilities: []}), false);
  assert.equal(configurationEqual(first, {...second, enabled: 0}), false);
  assert.equal(configurationEqual([1, 2], [2, 1]), false);
  assert.equal(configurationEqual([], {}), false);
  assert.equal(configurationEqual({x: null}, {}), false);
  assert.equal(configurationEqual(first, {enabled: false, capabilities: null}), false);
});

test('configuration coordinate identities preserve distinct nodes, devices and parameter names', () => {
  const coordinates = [['a', 'b/c'], ['a/b', 'c'], ['node', 'a.b', 'c'], ['node', 'a', 'b.c'],
    ['__proto__', 'constructor', ''], ['node', 'device', '0'], ['node', 'device', '01'],
    ['node', 'device', 'quotes" and \u03a9']];
  const keys = coordinates.map(parts => configurationIdentity(...parts));
  assert.equal(new Set(keys).size, coordinates.length);
  assert.deepEqual(keys.map(JSON.parse), coordinates);
});

test('configuration JSON preserves own keys, explicit empty/null values and ordinary numerical values', () => {
  const intended = Object.fromEntries(['__proto__', 'constructor', 'prototype', 'toString', 'hasOwnProperty', '0', '01', ''].map(key => [key, {zero: 0, flag: false, empty: '', nullable: null, values: [1.25, 1e-20, 9007199254740991]}]));
  const read = parseConfigurationJSON(stringifyConfiguration(intended));
  assert.deepEqual(read, intended);
  for (const key of Object.keys(intended)) assert.equal(Object.hasOwn(read, key), true);
});

test('unsupported numeric representations fail explicitly rather than silently round or substitute', () => {
  for (const text of ['9007199254740993', '-9007199254740993', '1e100', '1e999', '1e-999', '-0', 'NaN', 'Infinity', '']) {
    assert.throws(() => configurationNumber(text), /cannot be represented faithfully/);
  }
  for (const text of ['9007199254740993', '1e999', '1e-999', '-0']) {
    assert.throws(() => parseConfigurationJSON(`{"nested":[${text}]}`), /cannot be represented faithfully/);
  }
  for (const value of [NaN, Infinity, -0, 9007199254740992]) assert.throws(() => stringifyConfiguration({value}), /cannot be represented faithfully/);
  for (const text of ['0', '1.25', '1e-20', '9007199254740991']) assert.equal(configurationNumber(text), Number(text));
});

test('integer input is established from the original token before conversion', () => {
  const valid = [['7', 7], ['0', 0], ['-7', -7], ['7.0', 7], ['.0', 0], ['1e3', 1000],
    ['100e-2', 1], ['1.25e2', 125], ['9007199254740991', 9007199254740991],
    ['-9007199254740991', -9007199254740991], ['90071992547409910e-1', 9007199254740991]];
  for (const [text, expected] of valid) assert.equal(configurationNumber(text, true), expected);
  for (const text of ['1.5', '1.0000000000000001', '9007199254740991.1', '-1.0000000000000001',
    '10000000000000001e-16', '1e-20', '1e-999999999999999999999']) {
    assert.throws(() => configurationNumber(text, true), /not an exact integer/);
  }
  for (const text of ['9007199254740992', '-9007199254740992', '1e999', '-0', 'NaN', 'Infinity', '0x10', '']) {
    assert.throws(() => configurationNumber(text, true), /cannot be represented faithfully/);
  }
  for (const text of ['1.5', '1e-20', '-0.25']) assert.equal(configurationNumber(text, false), Number(text));
  for (const text of ['1.0000000000000001', '9007199254740991.1']) {
    assert.throws(() => configurationNumber(text, false), /cannot be represented faithfully/);
    assert.throws(() => parseConfigurationJSON(`{"overrides":{"count":${text}}}`), /cannot be represented faithfully/);
  }
});
