// Operator-owned, hash-pinned policy. Controlled file tree only; NOT an OS sandbox.
import fs from 'node:fs';
import path from 'node:path';
export const name = 'uni-agent-rsi-closed-policy';
export const inject = ['tools'];
const supported = new Set(['str_replace_editor','cordis_inspect_list']);
function regular(value) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || path.normalize(value) !== value) return false;
  try {
    let cursor = path.parse(value).root;
    const parts = value.slice(cursor.length).split(path.sep);
    for (const [index, part] of parts.entries()) {
      cursor = path.join(cursor,part);
      const info = fs.lstatSync(cursor);
      if (info.isSymbolicLink()) return false;
      if (index < parts.length - 1 ? !info.isDirectory() : !info.isFile() || info.nlink !== 1) return false;
    }
    return true;
  } catch { return false; }
}
export function createPolicy(config) {
  const fields=['allowedTools','readFiles','candidateSha256','contentSha256','activeSha256','policySha256'];
  if (!config || typeof config !== 'object' || Object.keys(config).sort().join() !== fields.sort().join()
    || !['candidateSha256','contentSha256','activeSha256','policySha256'].every(key=>/^sha256:[a-f0-9]{64}$/.test(config[key]))
    || !Array.isArray(config.allowedTools) || !config.allowedTools.length
    || !config.allowedTools.every(name=>supported.has(name)) || new Set(config.allowedTools).size !== config.allowedTools.length
    || !Array.isArray(config.readFiles) || !config.readFiles.length || !config.readFiles.every(regular)
    || new Set(config.readFiles).size !== config.readFiles.length) throw new Error('Invalid RSI policy configuration');
  const allowed=new Set(config.allowedTools), files=new Set(config.readFiles);
  return exec => {
    if (!allowed.has(exec.name) || !exec.arguments || typeof exec.arguments !== 'object' || Array.isArray(exec.arguments)) return false;
    if (exec.name === 'cordis_inspect_list') return Object.keys(exec.arguments).length === 0;
    return Object.keys(exec.arguments).sort().join() === 'command,path'
      && exec.arguments.command === 'view' && files.has(exec.arguments.path) && regular(exec.arguments.path);
  };
}
export function apply(ctx,config) {
  const permits=createPolicy(config);
  ctx.tools.guard(exec => permits(exec) ? undefined : 'RSI_POLICY_DENIED');
  ctx.on('tools/pre-execute',async (exec,next)=>permits(exec) ? next() : {kind:'deny',reason:'RSI_POLICY_DENIED'});
}
