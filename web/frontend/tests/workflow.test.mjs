import test from 'node:test'
import assert from 'node:assert/strict'
import { taskPresentation, unresolvedIssues, isHistoricalTask, importFiles, reconcileImportFailures, createImportRequestKeys, createRequestId, reconcileDecisions, archiveCoverTitle, formatShanghaiTime, canDeferMissing, canLocateEvidence, parseAgentFragmentProgress, canSummarizeCompletedReview } from '../src/domain/workflow.js'

test('completed review may collapse only when its artifacts exist and no unresolved or unsaved work remains', () => {
  const task={status:'done',has_archive:true,formal_ready:false}
  assert.equal(canSummarizeCompletedReview(task,0,false),true)
  assert.equal(canSummarizeCompletedReview(task,1,false),false)
  assert.equal(canSummarizeCompletedReview(task,0,true),false)
  for(const status of ['running','pending','awaiting_review','failed']) assert.equal(canSummarizeCompletedReview({...task,status},0,false),false)
  assert.equal(canSummarizeCompletedReview({...task,has_archive:false},0,false),false)
})

test('completed artifacts without verified rules are experience outputs, never a compliance pass', () => {
  for (const extra of [{}, { formal_ready: false }, { formal_ready: true, preview_draft: true }]) {
    assert.equal(taskPresentation({ status: 'done', has_archive: true, ...extra }).title, '体验归档已完成')
  }
  assert.equal(taskPresentation({ status: 'done', has_archive: true, formal_ready: true }).title, '归档成果已生成')
})

test('only actual completed-fragment events become count progress, never page or total percentages', () => {
  assert.deepEqual(parseAgentFragmentProgress('归档助理：来源核对完成，已处理 58 / 100 个页面片段'), {done:58,total:100})
  assert.deepEqual(parseAgentFragmentProgress('归档助理：来源核对完成，已处理 3 / 100 个页面片段'), {done:3,total:100})
  for (const text of ['正在阅读 58 个页面片段', '已完成 58 页', '来源核对完成，已处理 101 / 100 个页面片段', '来源核对完成，已处理 0 / 0 个页面片段', null]) assert.equal(parseAgentFragmentProgress(text),null)
})
test('blocking conflicts require a reason and cannot be hidden by acknowledging another conflict', () => {
  const issues = [{ id:'a', blocking:true }, { id:'b', blocking:true }, { id:'c', blocking:false }]
  assert.deepEqual(unresolvedIssues(issues, { a: { action:'acknowledged', reason:'核对原文' }, b: { action:'acknowledged', reason:'  ' } }).map(i=>i.id), ['b'])
})
test('supplemented source and earlier tasks mark outputs as historical', () => {
  assert.equal(isHistoricalTask({id:1, source_changed:true}, 1), true)
  assert.equal(isHistoricalTask({id:1}, 2), true)
  assert.equal(isHistoricalTask({id:2}, 2), false)
})
test('partial import records exact failures and does not retry successful files', async () => {
  const files = [{name:'a.pdf',size:100},{name:'b.doc',size:100},{name:'c.pdf',size:100},{name:'d.pdf',size:3e6}]
  const called=[]
  const result=await importFiles(files,{supported_extensions:['.pdf'],max_upload_mb:1},async file=>{
    called.push(file.name)
    if(file.name==='c.pdf')throw {response:{data:{detail:'文件已加密'}}}
  })
  assert.deepEqual(called,['a.pdf','c.pdf'])
  assert.deepEqual(result.imported.map(f=>f.name),['a.pdf'])
  assert.deepEqual(result.failed.map(f=>f.name),['b.doc','c.pdf','d.pdf'])
  assert.equal(result.failed[1].message,'文件已加密')
})

test('import retries clear only the attempted File identities and preserve an unattempted same-name file',()=>{
  const first=new File(['first contents'],'同名.pdf'),other=new File(['other contents'],'同名.pdf'),fresh=new File(['new'],'新材料.pdf')
  const failed=[{file:first,name:first.name,message:'旧错误'},{file:other,name:other.name,message:'另一个文件失败'}]
  const afterNew=reconcileImportFailures(failed,[fresh],[])
  assert.deepEqual(afterNew,failed)
  const retryFailed=reconcileImportFailures(afterNew,[first],[{file:first,name:first.name,message:'新的错误'}])
  assert.equal(retryFailed.length,2);assert.equal(retryFailed.find(item=>item.file===first).message,'新的错误')
  const retrySucceeded=reconcileImportFailures(retryFailed,[first],[])
  assert.equal(retrySucceeded.length,1);assert.equal(retrySucceeded[0].file,other)
  assert.equal(failed[0].message,'旧错误')
})

test('queued upload keys survive retries without combining newly selected same-name files',()=>{
  const keyFor=createImportRequestKeys(),first=new File(['same bytes'],'相同.pdf'),second=new File(['same bytes'],'相同.pdf')
  const original=keyFor(first)
  assert.match(original,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
  assert.equal(keyFor(first),original);assert.notEqual(keyFor(second),original)
})

test('request IDs retain secure randomness in LAN contexts without randomUUID and fail clearly without crypto',()=>{
  let calls=0
  const id=createRequestId({getRandomValues(bytes){calls++;bytes.fill(255);return bytes}})
  assert.equal(calls,1);assert.equal(id,'ffffffff-ffff-4fff-bfff-ffffffffffff')
  assert.throws(()=>createRequestId({}),error=>error.code==='secure_random_unavailable'&&/安全请求编号/.test(error.message))
})
test('polling accepts server conflict resolution while preserving locally edited reasons', () => {
  const baseline={a:{action:'pending',reason:''},b:{action:'pending',reason:''}}
  const current={...baseline,b:{action:'acknowledged',reason:'正在核对'}}
  const incoming={a:{action:'acknowledged',reason:'人工修正了字段'},b:{action:'pending',reason:''}}
  const result=reconcileDecisions(['a','b'],current,baseline,incoming)
  assert.equal(result.draft.a.action,'acknowledged')
  assert.equal(result.draft.b.reason,'正在核对')
  assert.equal(result.saved.b.action,'pending')
})
test('non-litigation and counsel covers never use a litigation title', () => {
  assert.equal(archiveCoverTitle('nonlit'),'律师业务档案卷宗（非诉讼类）')
  assert.equal(archiveCoverTitle('counsel'),'律师业务档案卷宗（非诉讼类）')
  assert.equal(archiveCoverTitle('criminal'),'律师业务档案卷宗（诉讼类）')
  assert.equal(archiveCoverTitle(undefined),'律师业务档案卷宗')
})
test('naive backend UTC timestamps and explicit offsets show the same Shanghai time', () => {
  assert.equal(formatShanghaiTime('2026-10-22T18:11:00'),'2026-10-23 02:11')
  assert.equal(formatShanghaiTime('2026-10-22T18:11:00Z'),'2026-10-23 02:11')
  assert.equal(formatShanghaiTime('2026-10-23T02:11:00+08:00'),'2026-10-23 02:11')
})
test('bulk draft deferral cannot exempt verified required legal material', () => {
  assert.equal(canDeferMissing({requirement:'required',legal_requirement_verified:true}),false)
  assert.equal(canDeferMissing({requirement:'unknown',legal_requirement_verified:false}),true)
})
test('human values have no fabricated original-page button', () => {
  assert.equal(canLocateEvidence({method:'human',page:null,url:null,value:'人工输入'}),false)
  assert.equal(canLocateEvidence({method:'human',file_id:'old',page:1}),false)
  assert.equal(canLocateEvidence({method:'model',file_id:'source',page:2,historical:true}),true)
})
