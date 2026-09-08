// Trusted CPU canary only. NEVER include this probe in a student training profile.
import fs from 'node:fs';
import crypto from 'node:crypto';
export const name='uni-agent-rsi-runtime-canary';
export const inject=['tools'];
export function apply(ctx,config) {
  const timer=setTimeout(async ()=>{
    try {
      const inventory=ctx.tools.schemas().map(tool=>tool.name).sort(), results=[];
      for (const [index,call] of config.calls.entries()) {
        const result=await ctx.tools.execute({callId:`rsi-canary-${index}`,signal:new AbortController().signal,name:call.name,arguments:call.arguments});
        const text=JSON.stringify(result);
        results.push({label:call.label,isError:result.isError,policyDenied:text.includes('RSI_POLICY_DENIED'),
          expectedTextPresent:call.expectedText == null ? null : text.includes(call.expectedText),
          forbiddenTextPresent:text.includes(config.forbiddenText),
          resultSha256:'sha256:'+crypto.createHash('sha256').update(text).digest('hex')});
      }
      fs.writeFileSync(config.report,JSON.stringify({candidateSha256:config.candidateSha256,policySha256:config.policySha256,inventory,results}),{flag:'wx',mode:0o600});
    } catch (error) {
      fs.writeFileSync(config.report,JSON.stringify({error:error.name}),{flag:'wx',mode:0o600});
    }
  },500);
  ctx.on('dispose',()=>clearTimeout(timer));
}
