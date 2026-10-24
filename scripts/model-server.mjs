import { spawn } from 'node:child_process';
import { existsSync, readFileSync, openSync, readSync, closeSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const profiles = JSON.parse(readFileSync(new URL('./model-profiles.json', import.meta.url), 'utf8'));

export function verifyModelFile(filename, profile) {
  if (statSync(filename).size !== profile.bytes) throw new Error('Model size does not match the selected profile. Run setup-inference.py for that model.');
  const hash = createHash('sha256');
  const buffer = Buffer.alloc(1024 * 1024);
  const descriptor = openSync(filename, 'r');
  try { let count; while ((count = readSync(descriptor, buffer, 0, buffer.length, null))) hash.update(buffer.subarray(0, count)); }
  finally { closeSync(descriptor); }
  if (hash.digest('hex') !== profile.sha256) throw new Error('Model checksum mismatch; refusing to start or substitute another model.');
}

export function localModelCommand(root, env = process.env) {
  const id = env.LOCAL_MODEL_PROFILE || Object.keys(profiles).find(id => profiles[id].alias === env.GEMMA_MODEL) || (env.GEMMA_MODEL ? '' : 'qwen');
  const profile = Object.hasOwn(profiles, id) ? profiles[id] : null;
  if (!profile) throw new Error('Unknown local model profile. Select gemma or qwen explicitly.');
  if (env.GEMMA_MODEL && env.GEMMA_MODEL !== profile.alias) throw new Error('GEMMA_MODEL disagrees with LOCAL_MODEL_PROFILE. Run npm run model:select -- ' + id);
  const binary = env.LLAMA_SERVER || path.join(root, '.local', 'llama.cpp', process.platform === 'win32' ? 'llama-server.exe' : 'llama-server');
  const model = path.join(root, '.models', profile.filename);
  if (!existsSync(binary) || !existsSync(model)) throw new Error('Local CPU runtime/model missing. Run .venv Python scripts/setup-inference.py first; see docs/inference-ocr.md.');
  verifyModelFile(model, profile);
  return [binary, ['--model', model, '--alias', profile.alias, '--ctx-size', '4096', '--threads', '2', '--parallel', '1', '--host', '127.0.0.1', '--port', '8081']];
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  if (existsSync(path.join(root, '.env'))) process.loadEnvFile(path.join(root, '.env'));
  const [binary, args] = localModelCommand(root);
  const child = spawn(binary, args, { cwd: root, stdio: 'inherit', windowsHide: true });
  child.on('error', error => { console.error(error.message); process.exitCode = 1; });
  child.on('exit', code => { process.exitCode = code ?? 1; });
  process.on('SIGINT', () => child.kill('SIGTERM'));
  process.on('SIGTERM', () => child.kill('SIGTERM'));
}
