import test from 'node:test'
import assert from 'node:assert/strict'
import { classificationTargetKey, createDocumentClassification, documentClassificationDirty, locateDocumentUnit } from '../src/domain/documentClassification.js'

const unit={unit_key:'unit-1',doc_id:'doc-1',file_id:'file-1',filename:'虚构扫描卷.pdf',page_start:4,page_end:6,doc_type:'judgment',catalog_seq:9,catalog_name:'裁判文书',classification_origin:'auto',reason:''}
const options=[{doc_type:'judgment',catalog_seq:9,label:'裁判文书'},{doc_type:'evidence',catalog_seq:7,label:'证据材料'}]
function response(revision=2,extra={}) { return {revision,source_changed:false,editable:true,blocked_reason:'',documents:[{...unit}],options,...extra} }
function fixture(overrides={}) {
  let state, payloads=[],saved=[]
  const review=createDocumentClassification({
    read:async()=>response(), write:async(id,key,body)=>{payloads.push({id,key,body});return response(3,{task:{id:1,revision:3,status:'awaiting_review',has_archive:false,confirmed_revision:null}})},
    onChange:value=>state=value,onSaved:task=>saved.push(task),...overrides,
  })
  review.reset('task-1')
  return {review,get state(){return state},payloads,saved}
}
async function edit(f) { await f.review.load();f.review.select('unit-1');f.review.updateDraft({target:classificationTargetKey(options[1]),reason:'核对第 4—6 页，确认为证据材料'}) }

test('saves only allowed classification and exact loaded revision; returned task invalidates prior output',async()=>{
  const f=fixture();await edit(f)
  assert.equal(documentClassificationDirty(f.state),true)
  assert.equal(await f.review.save(),true)
  assert.deepEqual(f.payloads,[{id:'task-1',key:'unit-1',body:{expected_revision:2,doc_type:'evidence',catalog_seq:7,reason:'核对第 4—6 页，确认为证据材料'}}])
  assert.equal(f.saved[0].status,'awaiting_review');assert.equal(f.saved[0].has_archive,false)
  assert.equal(f.state.revision,3);assert.equal(documentClassificationDirty(f.state),false)
  assert.match(f.state.message,/更新草稿后即可下载/)
  assert.match(f.state.message,/正式归档仍需最终确认/)
  assert.deepEqual([f.state.documents[0].page_start,f.state.documents[0].page_end],[4,6])
})

test('failed field save / unsaved table guard prevents classification write and preserves draft',async()=>{
  let blocked='请先保存核对草稿'
  const f=fixture({beforeWrite:async()=>blocked});await edit(f)
  assert.equal(await f.review.save(),false);assert.equal(f.payloads.length,0)
  assert.match(f.state.error,/核对草稿/);assert.match(f.state.draft.reason,/证据材料/)
  blocked='';assert.equal(await f.review.save(),true)
})

test('409 preserves input and requires explicit refresh; stale retry never silently uses newer revision',async()=>{
  let revision=2,calls=0
  const f=fixture({read:async()=>response(revision),write:async(_,__,body)=>{calls++;if(calls===1){revision=4;throw {response:{status:409}}}return response(5,{task:{revision:5},saved_revision:body.expected_revision})}})
  await edit(f);assert.equal(await f.review.save(),false)
  assert.equal(f.state.stale,true);assert.match(f.state.error,/刷新文书清单/)
  assert.equal(await f.review.save(),false);assert.equal(calls,1)
  await f.review.load();assert.equal(f.state.revision,4);assert.equal(f.state.stale,false)
  assert.equal(f.state.draft.target,classificationTargetKey(options[1]));assert.match(f.state.draft.reason,/证据材料/)
  assert.equal(await f.review.save(),true);assert.equal(calls,2)
})

test('network failure preserves a retryable draft and never emits completion',async()=>{
  const f=fixture({write:async()=>{throw new Error('offline')}});await edit(f)
  assert.equal(await f.review.save(),false);assert.equal(f.saved.length,0)
  assert.equal(f.state.stale,false);assert.equal(f.state.saving,false);assert.match(f.state.error,/连接/)
  assert.match(f.state.draft.reason,/证据材料/)
})

test('repeat click cannot send a second write while first request is pending',async()=>{
  let resolve,calls=0
  const f=fixture({write:async()=>{calls++;return new Promise(done=>resolve=done)}});await edit(f)
  const pending=f.review.save();await Promise.resolve()
  assert.equal(await f.review.save(),false);assert.equal(calls,1)
  resolve(response(3,{task:{revision:3}}));assert.equal(await pending,true)
})

test('polling a newer revision invalidates draft and a late old read cannot make it editable',async()=>{
  let resolve
  const f=fixture();await edit(f)
  f.review.invalidate(5);assert.equal(await f.review.save(),false);assert.equal(f.payloads.length,0)
  await f.review.load();assert.equal(f.state.stale,true);assert.match(f.state.draft.reason,/证据材料/)
  const g=fixture({read:async()=>new Promise(done=>resolve=done)})
  const loading=g.review.load();g.review.invalidate(6);resolve(response(3));await loading
  assert.equal(g.state.stale,true)
})

test('running task, changed sources, unknown targets, blank or oversized reasons never send a write',async()=>{
  for(const extra of [{editable:false,blocked_reason:'正在处理'},{source_changed:true}]){
    const f=fixture({read:async()=>response(2,extra)});await edit(f)
    assert.equal(await f.review.save(),false);assert.equal(f.payloads.length,0)
  }
  for(const values of [{target:'["arbitrary",999]'},{reason:'   '},{reason:'字'.repeat(1001)}]){
    const f=fixture();await edit(f);f.review.updateDraft(values)
    assert.equal(await f.review.save(),false);assert.equal(f.payloads.length,0)
  }
})

test('switching task aborts an in-flight write and discards late result from the former case',async()=>{
  let resolve,signal
  const f=fixture({write:async(_,__,___,currentSignal)=>{signal=currentSignal;return new Promise(done=>resolve=done)}});await edit(f)
  const pending=f.review.save();await Promise.resolve();f.review.reset('new-task')
  assert.equal(signal.aborted,true);resolve(response(3,{task:{revision:3}}))
  assert.equal(await pending,false);assert.equal(f.saved.length,0);assert.equal(f.state.revision,null)
})

test('a missing updated task cannot be represented as a successful save',async()=>{
  const f=fixture({write:async()=>response(3)});await edit(f)
  assert.equal(await f.review.save(),false);assert.equal(f.saved.length,0)
  assert.equal(f.state.revision,2);assert.match(f.state.draft.reason,/证据材料/)
})

test('idempotent same-revision save does not falsely announce confirmation invalidation',async()=>{
  const f=fixture({write:async()=>response(2,{task:{revision:2,status:'done',has_archive:true}})});await edit(f)
  assert.equal(await f.review.save(),true);assert.match(f.state.message,/确认状态未因本次操作改变/)
  assert.equal(f.saved[0].has_archive,true)
})

test('selecting another row cannot silently discard an in-progress draft; explicit cancel can',async()=>{
  const f=fixture({read:async()=>response(2,{documents:[{...unit},{...unit,unit_key:'unit-2'}]})});await edit(f)
  assert.equal(f.review.select('unit-2'),false);assert.equal(f.state.draft.unit_key,'unit-1')
  f.review.cancel();assert.equal(f.review.select('unit-2'),true);assert.equal(documentClassificationDirty(f.state),false)
})

test('issue location uses exact source identity and inclusive page range without switching the classification draft',async()=>{
  const documents=[{...unit},{...unit,unit_key:'other-file',file_id:'file-2'},{...unit,unit_key:'next-document',page_start:7,page_end:9}]
  const f=fixture({read:async()=>response(2,{documents})});await edit(f)
  assert.equal(locateDocumentUnit(f.state.documents,{file_id:'file-1',page_start:6}).unit_key,'unit-1')
  assert.equal(locateDocumentUnit(f.state.documents,{file_id:'file-1',page:7}).unit_key,'next-document')
  assert.equal(locateDocumentUnit(f.state.documents,{file_id:'file-2',page:4}).unit_key,'other-file')
  assert.equal(f.state.draft.unit_key,'unit-1');assert.match(f.state.draft.reason,/证据材料/)
})

test('missing, invalid or ambiguous source coordinates never highlight an arbitrary document',()=>{
  for(const source of [{filename:unit.filename,page:4},{file_id:'unknown',page:4},{file_id:'file-1',page:0},{file_id:'file-1',page:3.5},{file_id:'file-1',page:8}])assert.equal(locateDocumentUnit([unit],source),null)
  assert.equal(locateDocumentUnit([unit,{...unit,unit_key:'overlapping'}],{file_id:'file-1',page:4}),null)
})

test('save publishes its lock before awaiting editor guard; late edits and revision changes cannot reach write',async()=>{
  let unlock,lockWasPublished=false
  const f=fixture({beforeWrite:async()=>{lockWasPublished=f.state.saving;return new Promise(done=>unlock=done)}});await edit(f)
  const oldReason=f.state.draft.reason,pending=f.review.save()
  assert.equal(lockWasPublished,true)
  f.review.updateDraft({reason:'保存过程中不应接收的新输入'})
  assert.equal(f.state.draft.reason,oldReason)
  f.review.invalidate(3);unlock('')
  assert.equal(await pending,false);assert.equal(f.payloads.length,0);assert.equal(f.state.saving,false)
  assert.match(f.state.error,/任务版本已变化/)
})
