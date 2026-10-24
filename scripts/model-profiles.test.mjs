import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { localModelCommand, profiles, verifyModelFile } from './model-server.mjs';
import { selectModel } from './select-model.mjs';

function directory(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'vaultx-profile-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}

test('explicit model selection preserves reviewer/provider keys and OCR/data configuration', t => {
  const root = directory(t);
  writeFileSync(path.join(root, '.env'), 'API_KEY=synthetic-reviewer-secret\nGEMMA_API_KEY=synthetic-provider-secret\nOCR_ENABLED=true\nSTORAGE_DIR=private-storage\nGEMMA_MODEL=qwen2.5-0.5b-instruct\n');
  selectModel(root, 'gemma');
  let content = readFileSync(path.join(root, '.env'), 'utf8');
  assert.match(content, /^LOCAL_MODEL_PROFILE=gemma$/m);
  assert.ok(content.includes('GEMMA_MODEL=' + profiles.gemma.alias));
  for (const line of ['API_KEY=synthetic-reviewer-secret', 'GEMMA_API_KEY=synthetic-provider-secret', 'OCR_ENABLED=true', 'STORAGE_DIR=private-storage']) assert.ok(content.includes(line));
  selectModel(root, 'qwen');
  content = readFileSync(path.join(root, '.env'), 'utf8');
  assert.match(content, /^LOCAL_MODEL_PROFILE=qwen$/m);
  assert.ok(content.includes('GEMMA_MODEL=' + profiles.qwen.alias));
  assert.equal((content.match(/^GEMMA_MODEL=/gm) || []).length, 1);
});

test('unknown model selection cannot mutate existing configuration', t => {
  const root = directory(t);
  writeFileSync(path.join(root, '.env'), 'API_KEY=synthetic-key\n');
  for (const id of ['unavailable', '__proto__', 'constructor']) assert.throws(() => selectModel(root, id), /Choose gemma or qwen/);
  assert.equal(readFileSync(path.join(root, '.env'), 'utf8'), 'API_KEY=synthetic-key\n');
});

test('runtime rejects profile/alias mismatches instead of serving Qwen as Gemma', t => {
  assert.throws(() => localModelCommand(directory(t), { LOCAL_MODEL_PROFILE: 'gemma', GEMMA_MODEL: profiles.qwen.alias }), /disagrees/);
  assert.throws(() => localModelCommand(directory(t), { LOCAL_MODEL_PROFILE: 'unknown' }), /Unknown/);
});

test('missing Gemma file cannot automatically fall back to Qwen', t => {
  assert.throws(() => localModelCommand(directory(t), { LOCAL_MODEL_PROFILE: 'gemma', GEMMA_MODEL: profiles.gemma.alias }), /missing/);
});

test('startup verifies content integrity, including same-size substitutions', t => {
  const filename = path.join(directory(t), 'synthetic.gguf');
  writeFileSync(filename, 'trusted synthetic weights');
  const profile = { bytes: 25, sha256: createHash('sha256').update('trusted synthetic weights').digest('hex') };
  verifyModelFile(filename, profile);
  writeFileSync(filename, 'changed synthetic weights');
  assert.throws(() => verifyModelFile(filename, profile), /checksum mismatch/);
  writeFileSync(filename, 'short');
  assert.throws(() => verifyModelFile(filename, profile), /size/);
});
