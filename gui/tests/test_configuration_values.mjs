import {test} from 'node:test';
import assert from 'node:assert/strict';
import {configurationIdentity, configurationNumber, parseConfigurationJSON, stringifyConfiguration} from '../src/miceball_gui/static/configuration-values.mjs';

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
