import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {createPolicy, apply} from './policy.mjs';

test('parent/candidate policy controls actual tool names and fixed read paths', () => {
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'rsi-policy-'));
  try {
    const file = path.join(root, 'input.txt'); fs.writeFileSync(file, 'evidence');
    const config = {allowedTools:['str_replace_editor'], readFiles:[file], candidateSha256:'sha256:'+'a'.repeat(64), policySha256:'sha256:'+'b'.repeat(64), activeSha256:'sha256:'+'c'.repeat(64), contentSha256:'sha256:'+'d'.repeat(64)};
    const parent = createPolicy(config);
    assert.equal(parent({name:'str_replace_editor', arguments:{command:'view',path:file}}), true);
    assert.equal(parent({name:'cordis_inspect_list',arguments:{}}), false);
    const candidate = createPolicy({...config,allowedTools:['cordis_inspect_list','str_replace_editor']});
    assert.equal(candidate({name:'cordis_inspect_list',arguments:{}}), true);
    for (const call of [
      {name:'bash',arguments:{command:'echo leak'}},
      {name:'cordis_define',arguments:{code:{host:'return 1'}}},
      {name:'str_replace_editor',arguments:{command:'create',path:file,file_text:'changed'}},
      {name:'str_replace_editor',arguments:{command:'view',path:root}},
      {name:'str_replace_editor',arguments:{command:'view',path:'input.txt'}},
      {name:'str_replace_editor',arguments:{command:'view',path:file,view_range:[1,1]}},
    ]) assert.equal(candidate(call), false);
    const alias = path.join(root,'alias'); fs.symlinkSync(file,alias);
    assert.throws(()=>createPolicy({...config,readFiles:[alias]}));
    assert.throws(()=>createPolicy({...config,allowedTools:['cordis_define']}));
    assert.throws(()=>createPolicy({...config,extra:'untrusted'}));
    fs.unlinkSync(file); fs.symlinkSync('/etc/passwd',file);
    assert.equal(parent({name:'str_replace_editor', arguments:{command:'view',path:file}}), false);
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
});

test('operator policy registers a final monotonic guard plus pre-execute denial', async () => {
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'rsi-guard-'));
  try {
    const file=path.join(root,'input');fs.writeFileSync(file,'ok');
    let guard,listener;
    apply({tools:{guard:g=>{guard=g;}},on:(_name,cb)=>{listener=cb;}}, {
      allowedTools:['str_replace_editor'],readFiles:[file],candidateSha256:'sha256:'+'a'.repeat(64),
      policySha256:'sha256:'+'b'.repeat(64),activeSha256:'sha256:'+'c'.repeat(64),contentSha256:'sha256:'+'d'.repeat(64),
    });
    const call={name:'bash',arguments:{}};
    assert.equal(guard(call),'RSI_POLICY_DENIED');
    assert.deepEqual(await listener(call,()=>assert.fail('denial must not delegate')),{kind:'deny',reason:'RSI_POLICY_DENIED'});
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});
