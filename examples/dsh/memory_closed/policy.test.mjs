import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createPolicy } from './policy.mjs';

test('exact closed file permissions, aliases and default deny', () => {
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'memory-policy-'));
  try {
    const read = path.join(root, 'handoff');
    const secret = path.join(root, 'secret');
    const output = path.join(root, 'answer');
    fs.writeFileSync(read, 'allowed'); fs.writeFileSync(secret, 'SECRET');
    const policy = createPolicy({role:'reader', chainId:'c', sessionId:'b', sourceVersion:'v', readFiles:[read], writeFile:output});
    const check = (command, target, name='str_replace_editor') => policy({name, arguments:{command,path:target}});
    assert.equal(check('view',read),true);
    assert.equal(check('create',output),true);
    for (const [cmd,p] of [['view',secret],['view',root],['view',`${root}/../${path.basename(root)}/handoff`],['str_replace',read],['undo_edit',output],['view','handoff']]) assert.equal(check(cmd,p),false);
    for (const tool of ['bash','cordis_define','run_code','future_tool']) assert.equal(check('view',read,tool),false);
    fs.unlinkSync(read); fs.symlinkSync(secret,read); assert.equal(check('view',read),false);
    fs.unlinkSync(read); fs.linkSync(secret,read); assert.equal(check('view',read),false);
    assert.throws(()=>createPolicy({role:'reader'}));
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
});

test('deny before tool body, config failure is fatal and output links cannot be written', async () => {
  const { apply } = await import('./policy.mjs');
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'memory-policy-'));
  try {
    const input = path.join(root, 'input'); const output = path.join(root, 'output');
    fs.writeFileSync(input, 'private');
    const config = {role:'writer',chainId:'c',sessionId:'a',sourceVersion:'v',readFiles:[input,output],writeFile:output};
    let handler; apply({on(event, callback) { assert.equal(event,'tools/pre-execute'); handler=callback; }},config);
    let bodyCalls=0;
    const next=async()=>{bodyCalls++;return {kind:'allow'};};
    assert.equal((await handler({name:'bash',arguments:{}},next)).kind,'deny');
    assert.equal(bodyCalls,0);
    assert.equal((await handler({name:'str_replace_editor',arguments:{command:'create',path:output}},next)).kind,'allow');
    assert.equal(bodyCalls,1);
    fs.symlinkSync(input,output);
    assert.equal((await handler({name:'str_replace_editor',arguments:{command:'create',path:output}},next)).kind,'deny');
    assert.equal(bodyCalls,1);
    assert.throws(()=>createPolicy({...config,readFiles:[input,input]}));
    assert.throws(()=>createPolicy({...config,role:'unknown'}));
    fs.unlinkSync(output); fs.mkdirSync(output);
    assert.throws(()=>createPolicy(config));
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
});

test('denial explains public allowed actions and never echoes reader rejected path', async () => {
  const { apply } = await import('./policy.mjs');
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'memory-feedback-'));
  try {
    const input = path.join(root,'input'); const memory = path.join(root,'memory');
    fs.writeFileSync(input,'facts');
    let handler;
    const ctx = {on(_event, callback) {handler=callback;}};
    apply(ctx,{role:'writer',chainId:'c',sessionId:'a',sourceVersion:'v',readFiles:[input,memory],writeFile:memory});
    let result = await handler({name:'str_replace_editor',arguments:{command:'str_replace',path:input}},()=>assert.fail());
    assert.equal(result.kind,'deny');
    assert.match(result.reason,/read-only/i); assert.match(result.reason,/create/);
    assert.ok(result.reason.includes(memory)); assert.ok(result.reason.includes('file_text'));
    apply(ctx,{role:'reader',chainId:'c',sessionId:'b',sourceVersion:'v',readFiles:[input],writeFile:null});
    result = await handler({name:'str_replace_editor',arguments:{command:'view',path:'/private/A-secret-NEVER-ECHO'}},()=>assert.fail());
    assert.match(result.reason,/No writable target/);
    assert.ok(result.reason.includes(input)); assert.ok(!result.reason.includes('A-secret-NEVER-ECHO'));
    assert.ok(!result.reason.includes(memory));
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});
