import test from 'node:test'
import assert from 'node:assert/strict'
import {createAssistantDraft} from '../src/domain/assistantDraft.js'
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve()}
const record=(extra={})=>({content:'',version:0,revision:7,source_version:'s1',task_revision:7,task_source_version:'s1',writable:true,notice:'',consumed_request_id:null,...extra})
function harness({saved=record(),read,write,delay=60000}={}){
  let remote=structuredClone(saved),state,context={revision:7,source_version:'s1'},reads=0
  const writes=[]
  const draft=createAssistantDraft({delay,getContext:()=>context,onChange:value=>state=value,
    read:async(...args)=>{reads++;return read?read(...args):structuredClone(remote)},
    write:async(id,body,signal)=>{writes.push(structuredClone(body));if(write)return write(id,body,signal)
      if(body.expected_version!==remote.version)throw {response:{status:409}}
      remote=record({...remote,content:body.content,version:remote.version+1,revision:body.expected_revision,source_version:body.source_version,consumed_request_id:null})
      return structuredClone(remote)
    }})
  return {draft,writes,get state(){return state},get reads(){return reads},get remote(){return remote},setRemote(value){remote=value},setContext(value){context=value;draft.updateContext()}}
}

test('saved unsent text restores exactly without a model request or another write',async()=>{
  const h=harness({saved:record({content:'  全虚构未发送文字\n第二行  ',version:4})})
  h.draft.reset('task');await tick()
  assert.equal(h.state.content,'  全虚构未发送文字\n第二行  ');assert.equal(h.state.dirty,false);assert.equal(h.state.version,4);assert.deepEqual(h.writes,[]);h.draft.dispose()
})

test('typing auto-saves to the workstation after a bounded debounce, without changing task revision',async()=>{
  const h=harness({delay:5});h.draft.reset('task');await tick();h.draft.edit('第一稿');h.draft.edit('最后一稿')
  assert.equal(h.state.dirty,true);await new Promise(resolve=>setTimeout(resolve,20))
  assert.equal(h.writes.length,1);assert.equal(h.remote.content,'最后一稿');assert.equal(h.remote.revision,7);assert.equal(h.state.dirty,false);h.draft.dispose()
})

test('late GET after a failed initial read cannot erase local edits and offers both texts',async()=>{
  let first=true,release
  const h=harness({read:async()=>{if(first){first=false;throw new Error('offline')}return new Promise(resolve=>release=resolve)}})
  h.draft.reset('task');await tick();h.draft.edit('本机初稿');const reading=h.draft.reload();h.draft.edit('本机后续稿')
  release(record({content:'工作站另一份',version:2}));await reading
  assert.equal(h.state.content,'本机后续稿');assert.equal(h.state.remote.content,'工作站另一份');assert.equal(h.state.conflict,true);assert.equal(h.state.dirty,true);assert.equal(await h.draft.flush(),false);h.draft.dispose()
})

test('save acknowledgement updates only baseline while later typing remains visible and unsynced',async()=>{
  let release
  const h=harness({write:async(_,body)=>new Promise(resolve=>release=()=>resolve(record({content:body.content,version:body.expected_version+1})))})
  h.draft.reset('task');await tick();h.draft.edit('请求A');const saving=h.draft.flush();await tick();h.draft.edit('新输入B');release();assert.equal(await saving,false)
  assert.equal(h.state.content,'新输入B');assert.equal(h.state.version,1);assert.equal(h.state.dirty,true);h.draft.dispose()
})

test('CAS conflict preserves local and remote until explicit selection; adopting local uses the remote version',async()=>{
  const h=harness();h.draft.reset('task');await tick();h.draft.edit('本机文本');h.setRemote(record({content:'另标签文本',version:1}))
  assert.equal(await h.draft.flush(),false);assert.equal(h.state.content,'本机文本');assert.equal(h.state.remote.content,'另标签文本');assert.equal(h.state.conflict,true)
  assert.equal(await h.draft.flush(),false);assert.equal(h.writes.length,1)
  h.draft.chooseLocal();assert.equal(await h.draft.flush(),true);assert.equal(h.writes[1].expected_version,1);assert.equal(h.remote.content,'本机文本');h.draft.dispose()
})

test('explicit use of workstation conflict text does not write and clears navigation dirtiness',async()=>{
  const h=harness();h.draft.reset('task');await tick();h.draft.edit('本机文本');h.setRemote(record({content:'工作站文本',version:1}));await h.draft.flush()
  h.draft.useRemote();assert.equal(h.state.content,'工作站文本');assert.equal(h.state.dirty,false);assert.equal(h.writes.length,1);h.draft.dispose()
})

test('old draft context and subsequent prop changes require explicit continuation without resetting input',async()=>{
  const h=harness({saved:record({content:'旧上下文稿',version:1,revision:6})});h.draft.reset('task');await tick()
  assert.equal(h.state.contextChanged,true);assert.equal(h.state.dirty,false);assert.equal(await h.draft.flush(),false)
  h.draft.continueCurrentContext();assert.equal(await h.draft.flush(),true);assert.equal(h.remote.revision,7)
  h.draft.edit('尚未同步的新文字');h.setContext({revision:8,source_version:'s2'})
  assert.equal(h.state.content,'尚未同步的新文字');assert.equal(h.state.contextChanged,true);assert.equal(await h.draft.flush(),false);h.draft.dispose()
})

test('reset for the same task after account switch discards late responses and cancels the old debounce',async()=>{
  let reads=0,release
  const h=harness({read:async()=>++reads===1?new Promise(resolve=>release=resolve):record({content:'新账号稿',version:2})})
  h.draft.reset('same-task');h.draft.reset('same-task');await tick();release(record({content:'旧账号稿',version:9}));await tick()
  assert.equal(h.state.content,'新账号稿');assert.equal(h.state.version,2);assert.deepEqual(h.writes,[]);h.draft.dispose()
})

test('read-only historical draft remains visible but cannot edit, save, or send',async()=>{
  const h=harness({saved:record({content:'历史未发送稿',version:1,writable:false,notice:'历史任务只读'})});h.draft.reset('task');await tick()
  assert.equal(h.draft.edit('修改'),false);assert.equal(await h.draft.flush(),false);assert.equal(h.draft.snapshot(),null);assert.equal(h.state.content,'历史未发送稿');assert.deepEqual(h.writes,[]);h.draft.dispose()
})

test('lost save acknowledgement retries the exact CAS body and accepts the one-version acknowledgement',async()=>{
  let first=true,saved
  const h=harness({write:async(_,body)=>{if(first){first=false;saved=record({content:body.content,version:body.expected_version+1});throw new Error('ACK lost')}return saved}})
  h.draft.reset('task');await tick();h.draft.edit('已落盘未回执');assert.equal(await h.draft.flush(),false);assert.equal(h.state.unknown,true)
  assert.equal(await h.draft.flush(),true);assert.deepEqual(h.writes[0],h.writes[1]);assert.equal(h.state.dirty,false);h.draft.dispose()
})

test('atomic request consumption clears unchanged local input only after its matching readback, never by a second PUT',async()=>{
  const h=harness({saved:record({content:'发送问题',version:2})});h.draft.reset('task');await tick()
  const sent=h.draft.beginSend(h.draft.snapshot(),'request-1');assert.equal(h.state.dirty,true)
  h.setRemote(record({content:'',version:3,consumed_request_id:'request-1'}));assert.equal(await h.draft.finishSend(sent),true)
  assert.equal(h.state.content,'');assert.equal(h.state.dirty,false);assert.deepEqual(h.writes,[]);h.draft.dispose()
})

test('typing and changing back during send is new input, saved only after consumed-version readback',async()=>{
  const h=harness({saved:record({content:'原问题',version:2})});h.draft.reset('task');await tick()
  const sent=h.draft.beginSend(h.draft.snapshot(),'request-1');h.draft.edit('改过');h.draft.edit('原问题')
  assert.equal(await h.draft.flush(),false);assert.deepEqual(h.writes,[])
  h.setRemote(record({content:'',version:3,consumed_request_id:'request-1'}));await h.draft.finishSend(sent)
  assert.equal(h.state.content,'原问题');assert.equal(h.state.dirty,true);assert.equal(await h.draft.flush(),true)
  assert.equal(h.writes[0].expected_version,3);assert.equal(h.remote.content,'原问题');h.draft.dispose()
})

test('another tab writing after consumption cannot be erased or silently replaced by the sending tab',async()=>{
  const h=harness({saved:record({content:'原问题',version:2})});h.draft.reset('task');await tick();const sent=h.draft.beginSend(h.draft.snapshot(),'request-1')
  h.setRemote(record({content:'另标签新稿',version:4,consumed_request_id:null}));assert.equal(await h.draft.finishSend(sent),false)
  assert.equal(h.state.content,'原问题');assert.equal(h.state.remote.content,'另标签新稿');assert.equal(h.state.conflict,true);assert.equal(await h.draft.flush(),false);assert.deepEqual(h.writes,[]);h.draft.dispose()
})

test('failed post-send read keeps text dirty and blocks resending until matching consumption is read',async()=>{
  let fail=false
  const h=harness({read:async()=>{if(fail)throw new Error('offline');return record({content:fail?'':'问题',version:2})}})
  h.draft.reset('task');await tick();const sent=h.draft.beginSend(h.draft.snapshot(),'request-1');fail=true
  assert.equal(await h.draft.finishSend(sent),false);assert.equal(h.state.content,'问题');assert.equal(h.state.dirty,true);assert.equal(h.draft.snapshot(),null);assert.equal(await h.draft.flush(),false)
  h.draft.dispose()
})
