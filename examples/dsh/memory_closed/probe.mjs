// Operator-only no-model canary. Never include this probe in training profiles.
import fs from 'node:fs';
export const name = 'uni-agent-memory-policy-canary';
export const inject = ['tools'];
export function apply(ctx, config) {
  // Startup composition can still be registering sibling tool entries.
  const timer = setTimeout(async () => {
    try {
      const tools = ctx.tools.schemas().map(tool => tool.name).sort();
      const results = [];
      for (const [index, call] of config.calls.entries()) {
        const result = await ctx.tools.execute({
          callId: `memory-policy-canary-${index}`,
          signal: new AbortController().signal,
          name: call.name, arguments: call.arguments,
        });
        const serialized = JSON.stringify(result);
        results.push({
          label: call.label, isError: result.isError,
          expectedTextPresent: call.expectedText == null ? null : serialized.includes(call.expectedText),
          forbiddenTextPresent: config.forbiddenText != null && serialized.includes(config.forbiddenText),
          policyDenied: serialized.includes('MEMORY_POLICY_DENIED'),
        });
      }
      fs.writeFileSync(config.report, JSON.stringify({tools, results}), {flag:'wx',mode:0o600});
    } catch (error) {
      fs.writeFileSync(config.report, JSON.stringify({error: error.name}), {flag:'wx',mode:0o600});
    }
  }, 500);
  ctx.on('dispose', () => clearTimeout(timer));
}
