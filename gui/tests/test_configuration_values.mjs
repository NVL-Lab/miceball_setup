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
