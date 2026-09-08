// Trusted operator plugin; closed model tool policy, NOT an OS sandbox.
import fs from 'node:fs';
import path from 'node:path';

export const name = 'uni-agent-memory-closed-policy';
export const inject = ['tools'];

function regularPath(value, missing = false) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || path.normalize(value) !== value) return false;
  try {
    let part = path.parse(value).root;
    const pieces = value.slice(part.length).split(path.sep);
    for (let i = 0; i < pieces.length; i++) {
      part = path.join(part, pieces[i]);
      let stat;
      try { stat = fs.lstatSync(part); }
      catch (error) { return missing && i === pieces.length - 1 && error.code === 'ENOENT'; }
      if (stat.isSymbolicLink()) return false;
      if (i < pieces.length - 1 ? !stat.isDirectory() : !stat.isFile() || stat.nlink !== 1) return false;
    }
    return true;
  } catch { return false; }
}

export function createPolicy(config) {
  if (!config || !['writer', 'reader'].includes(config.role)
    || !['chainId', 'sessionId', 'sourceVersion'].every(key => typeof config[key] === 'string' && config[key].length > 0)
    || !Array.isArray(config.readFiles) || config.readFiles.length < 1
    || new Set(config.readFiles).size !== config.readFiles.length
    || !config.readFiles.every(p => regularPath(p, p === config.writeFile))
    || (config.writeFile !== null && !regularPath(config.writeFile, true))) {
    throw new Error('Invalid closed memory policy configuration');
  }
  const readable = new Set(config.readFiles);
  const writable = config.writeFile;
  return exec => {
    const args = exec.arguments;
    if (exec.name !== 'str_replace_editor' || !args || typeof args !== 'object') return false;
    const writing = ['create', 'str_replace', 'insert'].includes(args.command);
    if (args.command === 'view' ? !readable.has(args.path) : !writing || args.path !== writable) return false;
    return regularPath(args.path, args.command === 'create');
  };
}

export function apply(ctx, config) {
  const permits = createPolicy(config);
  // Only operator-declared allowlist paths appear here; never echo rejected args.
  const readOnly = config.readFiles.filter(file => file !== config.writeFile);
  const writable = config.writeFile;
  const reason = 'MEMORY_POLICY_DENIED. Allowed tool: str_replace_editor. '
    + `Read-only sources (view only; do not modify): ${JSON.stringify(readOnly)}. `
    + (writable === null
      ? 'No writable target in this reader session.'
      : `Only writable target: ${JSON.stringify(writable)}. For a new file use command="create", `
        + `path=${JSON.stringify(writable)}, file_text=<your memory JSON>. `
        + 'Use str_replace/insert only on that existing target, never on a source.');
  ctx.on('tools/pre-execute', async (exec, next) => permits(exec)
    ? next() : { kind: 'deny', reason });
}
