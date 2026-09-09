import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createPolicy, apply } from './policy.mjs';

function fixture() {
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'work-state-policy-'));
  const goal = path.join(root, 'goal'), index = path.join(root, 'index.json');
  const handoff = path.join(root, 'handoff.md'), result = path.join(root, 'result.json');
  fs.writeFileSync(goal, 'immutable');
  return {root, goal, index, handoff, result};
}
const request = (command, p, name='str_replace_editor') => ({name, arguments:{command, path:p}});

test('writer has exact multiple outputs; unknown tools and readonly writes denied', () => {
  const f = fixture();
  try {
    const policy = createPolicy({role:'writer',chainId:'c',sessionId:'a',sourceVersion:'v',
      readFiles:[f.goal,f.index,f.handoff],writeFiles:[f.index,f.handoff],readMissing:[f.index,f.handoff]});
    assert.equal(policy(request('view',f.goal)),true);
    for (const p of [f.index,f.handoff]) assert.equal(policy(request('create',p)),true);
    for (const req of [request('create',f.goal),request('insert',f.result),request('view',f.root),
      request('view',f.goal,'bash'),request('view',f.goal,'cordis_define'),request('undo_edit',f.index),
      request('view',f.root+'/../'+path.basename(f.root)+'/goal')]) assert.equal(policy(req),false);
  } finally { fs.rmSync(f.root,{recursive:true,force:true}); }
});

test('missing entry reaches native tool ENOENT; denial reveals no paths', async () => {
  const f = fixture();
  try {
    let handler;
    apply({on(_event,callback){handler=callback;}}, {role:'reader',chainId:'c',sessionId:'b',sourceVersion:'v',
      readFiles:[f.goal,f.index],writeFiles:[f.result],readMissing:[f.index]});
    let called=0;
    await assert.rejects(handler(request('view',f.index),async()=>{called++;fs.readFileSync(f.index);}),{code:'ENOENT'});
    assert.equal(called,1);
    const denial=await handler(request('view','/hidden/secret-file'),()=>assert.fail());
    assert.equal(denial.kind,'deny');
    for (const p of [f.goal,f.index,f.result,'/hidden/secret-file']) assert.ok(!denial.reason.includes(p));
    assert.equal((await handler(request('create',f.result),async()=>({kind:'allow'}))).kind,'allow');
    assert.equal((await handler(request('create',f.index),()=>assert.fail())).kind,'deny');
  } finally { fs.rmSync(f.root,{recursive:true,force:true}); }
});

test('links, directories, missing policy and mutable targets stay rejected', () => {
  const f=fixture();
  try {
    const config={role:'reader',chainId:'c',sessionId:'b',sourceVersion:'v',
      readFiles:[f.goal,f.index],writeFiles:[f.result],readMissing:[f.index]};
    const policy=createPolicy(config);
    fs.symlinkSync(f.goal,f.index); assert.equal(policy(request('view',f.index)),false);
    fs.unlinkSync(f.index); fs.linkSync(f.goal,f.index); assert.equal(policy(request('view',f.index)),false);
    fs.unlinkSync(f.index); fs.mkdirSync(f.index); assert.equal(policy(request('view',f.index)),false);
    fs.symlinkSync(f.goal,f.result); assert.equal(policy(request('create',f.result)),false);
    assert.throws(()=>createPolicy({...config,readMissing:[f.result]}));
    assert.throws(()=>createPolicy({...config,writeFiles:[f.result,f.result]}));
    assert.throws(()=>createPolicy({...config,role:'admin'}));
  } finally { fs.rmSync(f.root,{recursive:true,force:true}); }
});

test('read_missing accepts absent nested source, but output parent must exist safely', () => {
  const f=fixture();
  try {
    const absent=path.join(f.root,'absent','note.md');
    const config={role:'reader',chainId:'c',sessionId:'b',sourceVersion:'v',
      readFiles:[absent],writeFiles:[f.result],readMissing:[absent]};
    assert.equal(createPolicy(config)(request('view',absent)),true);
    assert.throws(()=>createPolicy({...config,writeFiles:[absent]}));
    fs.symlinkSync(f.root,path.join(f.root,'absent'));
    assert.equal(createPolicy({...config,readFiles:[f.goal],readMissing:[]})(request('view',absent)),false);
    assert.throws(()=>createPolicy(config));
  } finally { fs.rmSync(f.root,{recursive:true,force:true}); }
});

for (const role of ['writer','reader']) {
  test(`${role} new writable target view reaches native ENOENT without readMissing`, async () => {
    const f=fixture();
    try {
      let handler;
      apply({on(_event,callback){handler=callback;}},{role,chainId:'c',sessionId:role,sourceVersion:'v',
        readFiles:[f.goal,f.result],writeFiles:[f.result],readMissing:[]});
      let calls=0;
      await assert.rejects(handler(request('view',f.result),async()=>{calls++;fs.readFileSync(f.result);}),{code:'ENOENT'});
      assert.equal(calls,1);
      assert.equal((await handler(request('view',f.index),()=>assert.fail())).kind,'deny');
    } finally { fs.rmSync(f.root,{recursive:true,force:true}); }
  });
}
