import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { ensureLocalEnvironment } from './setup.mjs';

function workspace(t, template = 'API_KEY=\nVITE_API_KEY=\nEXTRACTION_MODE=demo\n') {
  const root = mkdtempSync(path.join(os.tmpdir(), 'vaultx-setup-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  writeFileSync(path.join(root, '.env.example'), template);
  return root;
}

test('fresh setup generates a unique key and preserves demo settings', t => {
  const root = workspace(t);
  assert.deepEqual(ensureLocalEnvironment(root), { created: true, configured: true });
  const content = readFileSync(path.join(root, '.env'), 'utf8');
  const key = content.match(/^API_KEY=([a-f0-9]{64})$/m)?.[1];
  assert.ok(key);
  assert.ok(content.includes(`VITE_API_KEY=${key}\n`));
  assert.ok(content.includes('EXTRACTION_MODE=demo\n'));
  const other = workspace(t);
  ensureLocalEnvironment(other);
  assert.notEqual(readFileSync(path.join(other, '.env'), 'utf8'), content);
});

test('rerunning setup leaves an existing configured environment byte-for-byte intact', t => {
  const root = workspace(t);
  const original = '# operator settings\r\nAPI_KEY="operator-private-key"\r\nVITE_API_KEY=\r\nGEMMA_MODEL=custom\r\n';
  writeFileSync(path.join(root, '.env'), original);
  assert.deepEqual(ensureLocalEnvironment(root), { created: false, configured: true });
  assert.equal(readFileSync(path.join(root, '.env'), 'utf8'), original);
});

test('copying a configured template still creates the environment file', t => {
  const template = 'API_KEY=operator-provided-key\nVITE_API_KEY=\n';
  const root = workspace(t, template);
  assert.deepEqual(ensureLocalEnvironment(root), { created: true, configured: true });
  assert.equal(readFileSync(path.join(root, '.env'), 'utf8'), template);
});

test('setup fills a missing backend key without replacing existing frontend/provider configuration', t => {
  const root = workspace(t);
  writeFileSync(path.join(root, '.env'), 'API_KEY=\nVITE_API_KEY=manual-entry\nGEMMA_API_KEY=private-provider-token\n');
  ensureLocalEnvironment(root);
  const content = readFileSync(path.join(root, '.env'), 'utf8');
  assert.match(content, /^API_KEY=[a-f0-9]{64}$/m);
  assert.ok(content.includes('VITE_API_KEY=manual-entry\n'));
  assert.ok(content.includes('GEMMA_API_KEY=private-provider-token\n'));
});
