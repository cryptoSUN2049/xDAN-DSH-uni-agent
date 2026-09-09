// Closed DSH model-tool policy. This is not an operating-system sandbox.
import fs from 'node:fs';
import path from 'node:path';

export const name = 'uni-agent-work-state-closed-policy';
export const inject = ['tools'];

function regularPath(value, missing = false, missingParents = false) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || path.normalize(value) !== value) return false;
  try {
    let part = path.parse(value).root;
    const pieces = value.slice(part.length).split(path.sep);
    for (let i = 0; i < pieces.length; i++) {
      part = path.join(part, pieces[i]);
      let stat;
      try { stat = fs.lstatSync(part); }
      catch (error) { return missing && error.code === 'ENOENT' && (missingParents || i === pieces.length - 1); }
      if (stat.isSymbolicLink()) return false;
      if (i < pieces.length - 1 ? !stat.isDirectory() : !stat.isFile() || stat.nlink !== 1) return false;
    }
    return true;
  } catch { return false; }
}

export function createPolicy(config) {
  if (!config || !['writer', 'reader'].includes(config.role)
    || !['chainId', 'sessionId', 'sourceVersion'].every(k => typeof config[k] === 'string' && config[k].length > 0)
    || !['readFiles', 'writeFiles', 'readMissing'].every(k => Array.isArray(config[k])
      && config[k].length <= 64 && new Set(config[k]).size === config[k].length)) {
    throw new Error('Invalid work-state file policy');
  }
  const reads = new Set(config.readFiles), writes = new Set(config.writeFiles), missing = new Set(config.readMissing);
  if (![...missing].every(p => reads.has(p))
    || ![...writes].every(p => regularPath(p, true))
    || ![...reads].every(p => regularPath(p, writes.has(p) || missing.has(p), missing.has(p)))) {
    throw new Error('Invalid work-state file policy');
  }
  return exec => {
    const args = exec.arguments;
    if (exec.name !== 'str_replace_editor' || !args || typeof args !== 'object' || Array.isArray(args)) return false;
    if (args.command === 'view') return reads.has(args.path) && regularPath(args.path, writes.has(args.path) || missing.has(args.path), missing.has(args.path));
    if (!['create', 'str_replace', 'insert'].includes(args.command) || !writes.has(args.path)) return false;
    return regularPath(args.path, args.command === 'create');
  };
}

export function apply(ctx, config) {
  const permits = createPolicy(config);
  ctx.on('tools/pre-execute', async (exec, next) => permits(exec) ? next() : {
    kind: 'deny',
    reason: 'WORK_STATE_POLICY_DENIED. Use str_replace_editor only on the exact files granted in your task. '
      + 'Read-only inputs cannot be changed. Use create for a new writable file; str_replace/insert for an existing one.',
  });
}
