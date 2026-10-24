import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function ensureLocalEnvironment(root) {
  const destination = path.join(root, '.env');
  const existed = existsSync(destination);
  let content = readFileSync(existed ? destination : path.join(root, '.env.example'), 'utf8');
  const current = content.match(/^API_KEY[\t ]*=[\t ]*([^\r\n]*)/m)?.[1]?.trim().replace(/^(['"])(.*)\1$/, '$2');
  if (current) {
    if (!existed) writeFileSync(destination, content, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    return { created: !existed, configured: true };
  }
  const key = randomBytes(32).toString('hex');
  const update = (name, value) => {
    const pattern = new RegExp(`^${name}[\\t ]*=[^\\r\\n]*`, 'm');
    content = pattern.test(content) ? content.replace(pattern, `${name}=${value}`) : `${content}\n${name}=${value}\n`;
  };
  update('API_KEY', key);
  // Local-only convenience. Hosted builds use the runtime reviewer-key screen.
  if (!existed) update('VITE_API_KEY', key);
  writeFileSync(destination, content, { encoding: 'utf8', mode: 0o600, flag: existed ? 'w' : 'wx' });
  return { created: !existed, configured: true };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const result = ensureLocalEnvironment(root);
  console.log(result.created ? 'Created private .env with a unique local reviewer key. Keep this local configuration private.' : 'Existing configuration preserved; a missing API_KEY was generated if necessary.');
}
