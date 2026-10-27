// Independent state-transition probes. No browser, HTTP, storage, or model.
import test from 'node:test'
import assert from 'node:assert/strict'
import {createAssistantDraft} from '../src/domain/assistantDraft.js'

const tick=()=>new Promise(resolve=>setImmediate(resolve))
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
const initial=()=>({content:'',version:0,revision:3,source_version:'synthetic-source',task_revision:3,
  task_source_version:'synthetic-source',updated_at:null,writable:true,notice:'',consumed_request_id:null})
async function harness(options={}){
  let remote=initial(),state,writes=[]
  const getRemote=()=>({...remote}),setRemote=value=>{remote={...remote,...value}}
  const write=async(_id,body)=>{
    writes.push({...body})
    if(body.expected_version!==remote.version)throw {response:{status:409}}
    remote={...remote,content:body.content,version:remote.version+1,revision:body.expected_revision,
      source_version:body.source_version,consumed_request_id:null}
    return getRemote()
  }
  const control=createAssistantDraft({read:options.read||(()=>Promise.resolve(getRemote())),
    write:options.write||write,getContext:()=>({revision:3,source_version:'synthetic-source'}),
    onChange:value=>{state=value},delay:1000000})
  control.reset('synthetic-task');await tick()
  return {control,get state(){return state},getRemote,setRemote,writes}
}

test('a late save acknowledgement cannot replace the text typed while saving',async()=>{
  const pending=deferred();let submitted
  const h=await harness({write:async(_id,body)=>{submitted=body;return pending.promise}})
  try{
    h.control.edit('虚构先保存A');const saving=h.control.flush();await tick()
    h.control.edit('虚构新编辑B')
    pending.resolve({...initial(),content:submitted.content,version:1})
    assert.equal(await saving,false)
    assert.equal(h.state.content,'虚构新编辑B');assert.equal(h.state.version,1);assert.equal(h.state.dirty,true)
  }finally{h.control.dispose()}
})

test('atomic consumption preserves and safely saves edits made during sending',async()=>{
  const h=await harness()
  try{
    h.control.edit('虚构发送A');assert.equal(await h.control.flush(),true)
    const sent=h.control.beginSend(h.control.snapshot(),'synthetic-send-A')
    assert.ok(sent)
    h.control.edit('发送期间虚构新输入B')
    assert.equal(await h.control.flush(),false)
    h.setRemote({content:'',version:2,consumed_request_id:'synthetic-send-A'})
    assert.equal(await h.control.finishSend(sent),true)
    assert.equal(h.state.content,'发送期间虚构新输入B');assert.equal(h.state.dirty,true)
    assert.equal(await h.control.flush(),true)
    assert.equal(h.getRemote().content,'发送期间虚构新输入B');assert.equal(h.getRemote().version,3)
  }finally{h.control.dispose()}
})

test('typing back the same string is a new edit and must not be consumed by equality',async()=>{
  const h=await harness()
  try{
    h.control.edit('虚构发送A');await h.control.flush()
    const sent=h.control.beginSend(h.control.snapshot(),'synthetic-send-A')
    h.control.edit('虚构改B');h.control.edit('虚构发送A')
    h.setRemote({content:'',version:2,consumed_request_id:'synthetic-send-A'})
    assert.equal(await h.control.finishSend(sent),true)
    assert.equal(h.state.content,'虚构发送A');assert.equal(h.state.dirty,true)
  }finally{h.control.dispose()}
})

test('unknown consumption blocks another send until its marker can be read',async()=>{
  let fail=false,current=initial()
  const h=await harness({read:async()=>{if(fail)throw Error('offline');return {...current}},
    write:async(_id,body)=>{current={...current,content:body.content,version:1};return {...current}}})
  try{
    h.control.edit('虚构丢响应要求');await h.control.flush()
    const sent=h.control.beginSend(h.control.snapshot(),'synthetic-lost-ack')
    fail=true
    assert.equal(await h.control.finishSend(sent),false)
    assert.equal(h.state.unknown,true);assert.equal(h.control.snapshot(),null)
    assert.equal(await h.control.flush(),false)
    assert.equal(h.state.content,'虚构丢响应要求')
    fail=false;current={...current,content:'',version:2,consumed_request_id:'synthetic-lost-ack'}
    assert.equal(await h.control.reload(),true)
    assert.equal(h.state.content,'');assert.equal(h.state.dirty,false)
  }finally{h.control.dispose()}
})

test('a second tab changing the consumed draft produces a conflict, never a forced overwrite',async()=>{
  const h=await harness()
  try{
    h.control.edit('虚构发送A');await h.control.flush()
    const sent=h.control.beginSend(h.control.snapshot(),'synthetic-send-A')
    h.setRemote({content:'另一标签的虚构B',version:3,consumed_request_id:null})
    assert.equal(await h.control.finishSend(sent),false)
    assert.equal(h.state.content,'虚构发送A');assert.equal(h.state.remote.content,'另一标签的虚构B')
    assert.equal(h.state.conflict,true);assert.equal(await h.control.flush(),false)
    const writes=h.writes.length
    assert.equal(h.control.useRemote(),true)
    assert.equal(h.state.content,'另一标签的虚构B');assert.equal(h.writes.length,writes)
  }finally{h.control.dispose()}
})

test('an account reset on the same task ignores an earlier account save response',async()=>{
  const pending=deferred();let account='first'
  const h=await harness({read:async()=>({...initial(),content:account==='first'?'':'另账号的虚构草稿',version:account==='first'?0:7}),
    write:async()=>pending.promise})
  try{
    h.control.edit('前账号私有虚构要求');const saving=h.control.flush();await tick()
    account='second';h.control.reset('synthetic-task');await tick()
    assert.equal(h.state.content,'另账号的虚构草稿')
    pending.resolve({...initial(),content:'前账号私有虚构要求',version:1})
    assert.equal(await saving,false)
    assert.equal(h.state.content,'另账号的虚构草稿');assert.equal(h.state.version,7)
  }finally{h.control.dispose()}
})

test('an uncommitted send retains the exact original unsent composition',async()=>{
  const h=await harness()
  try{
    h.control.edit('虚构尚未登记的要求');await h.control.flush()
    const sent=h.control.beginSend(h.control.snapshot(),'synthetic-not-committed')
    assert.equal(await h.control.finishSend(sent),true)
    assert.equal(h.state.content,'虚构尚未登记的要求');assert.equal(h.state.version,1)
    assert.equal(h.state.dirty,false)
  }finally{h.control.dispose()}
})

test('clearing old-context text settles after one save across multiple debounce intervals',async()=>{
  let context={revision:3,source_version:'synthetic-source'},state
  let remote={...initial(),content:'虚构旧版本文字',version:1},writes=[]
  const control=createAssistantDraft({delay:5,getContext:()=>context,
    read:async()=>({...remote}),write:async(_id,body)=>{
      writes.push({...body})
      assert.equal(body.expected_version,remote.version)
      remote={...remote,content:body.content,version:remote.version+1,
        revision:body.expected_revision,source_version:body.source_version,task_revision:4}
      return {...remote}
    },onChange:value=>{state=value}})
  try{
    control.reset('synthetic-task');await tick()
    context={revision:4,source_version:'synthetic-source'};control.updateContext()
    assert.equal(state.contextChanged,true)
    control.edit('');await control.flush()
    await new Promise(resolve=>setTimeout(resolve,45))
    assert.equal(writes.length,1,'empty text must not cause repeated version-only writes')
    assert.equal(remote.content,'');assert.equal(remote.revision,4)
    assert.equal(state.dirty,false);assert.equal(state.contextChanged,false)
    await new Promise(resolve=>setTimeout(resolve,25))
    assert.equal(writes.length,1,'saved clear must stay stable after later debounce intervals')
  }finally{control.dispose()}
})

test('reading an empty old-context tombstone never schedules an automatic write',async()=>{
  let state,writes=0
  const remote={...initial(),version:8,revision:3,task_revision:4,content:''}
  const control=createAssistantDraft({delay:5,getContext:()=>({revision:4,source_version:'synthetic-source'}),
    read:async()=>({...remote}),write:async(_id,body)=>{
      writes++
      return {...remote,version:9,revision:body.expected_revision}
    },onChange:value=>{state=value}})
  try{
    control.reset('synthetic-task');await tick()
    await new Promise(resolve=>setTimeout(resolve,45))
    assert.equal(writes,0,'GET and empty context difference cannot create a write')
    assert.equal(state.content,'');assert.equal(state.version,8);assert.equal(state.dirty,false)
    assert.equal(await control.flush(),true)
    await new Promise(resolve=>setTimeout(resolve,25))
    assert.equal(writes,0,'explicit flush of unchanged empty text remains read-only')
  }finally{control.dispose()}
})
