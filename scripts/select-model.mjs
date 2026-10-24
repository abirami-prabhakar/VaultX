import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { profiles } from './model-server.mjs';
import { ensureLocalEnvironment } from './setup.mjs';

export function selectModel(root, id) {
  const profile = Object.hasOwn(profiles, id) ? profiles[id] : null;
  if (!profile) throw new Error('Choose gemma or qwen; no model substitution is performed.');
  ensureLocalEnvironment(root);
  const filename = path.join(root, '.env');
  let content = readFileSync(filename, 'utf8');
  const values = { LOCAL_MODEL_PROFILE: id, LOCAL_MODEL_ENABLED: 'true', EXTRACTION_MODE: 'gemma',
    GEMMA_MODEL: profile.alias, GEMMA_BASE_URL: 'http://127.0.0.1:8081/v1', GEMMA_SUPPORTS_VISION: 'false' };
  for (const [key, value] of Object.entries(values)) {
    const pattern = new RegExp(`^${key}[\\t ]*=[^\\r\\n]*`, 'gm');
    content = pattern.test(content) ? content.replace(pattern, `${key}=${value}`) : `${content}\n${key}=${value}\n`;
  }
  writeFileSync(filename, content, { encoding: 'utf8', mode: 0o600 });
  return profile;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const profile = selectModel(root, process.argv[2]);
  console.log(`Selected ${profile.alias}. Restart the app to load this model. Existing keys, OCR and data settings were preserved.`);
}
