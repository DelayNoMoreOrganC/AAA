import test from 'node:test'
import assert from 'node:assert/strict'
import {caseTaskSummary,caseTaskPresentation} from '../src/domain/taskExperience.js'
import {buildDecisionQueue} from '../src/domain/decisionQueue.js'
import {createAssistantConversation,normalizeAssistantHistory} from '../src/domain/assistant.js'
import {createProposalApplication} from '../src/domain/assistantProposal.js'
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve()}
const proposal={id:'stored-proposal',field:'委托人名称',before:'虚构甲',after:'虚构乙',reason:'明确人工修改',revision:7,source_version:'source-v1',expires_at:'2099-01-01T00:00:00Z'}
const context=()=>({revision:7,source_version:'source-v1'})

test('case surfaces use artifact availability rather than treating every awaiting_review as a download or mandatory review',()=>{
  const record={last_task_id:3,last_task_status:'awaiting_review',last_task_summary:{id:3,status:'awaiting_review',delivery_kind:'draft',has_archive:true}}
  assert.equal(caseTaskPresentation(caseTaskSummary(record)).label,'草稿可下载')
  assert.equal(caseTaskPresentation({...record.last_task_summary,source_changed:true}).label,'补件待整理')
  assert.equal(caseTaskPresentation({...record.last_task_summary,status:'running'}).label,'正在整理')
  assert.equal(caseTaskPresentation({...record.last_task_summary,status:'failed'}).label,'需要处理')
  assert.equal(caseTaskPresentation(caseTaskSummary({last_task_id:3,last_task_status:'awaiting_review'})).label,'已整理，可查看')
  assert.equal(caseTaskPresentation(null).action,'开始归档')
})

test('associated review reasons remain individually unresolved and unrelated material absence cannot disappear',()=>{
  const a={id:'a',kind:'field_conflict',detail:{field:'案号',file_id:'f',page:2},message:'两个案号',blocking:true}
  const b={id:'b',kind:'fact_review',detail:{field:'案号',file_id:'f',page:2},message:'同字段来源需要核验',blocking:true}
  const c={id:'c',kind:'field_conflict',detail:{field:'法院收案号'},message:'另一案号字段',blocking:true}
  const task={issues:[a,b,c],catalog_status:[{seq:3,name:'合同待核',found:false}],review_queue:[{key:'field-case',kind:'issue',title:'核对案号',field:'案号',issue_ids:['a','b'],field_targets:[{template_name:'送达材料清单',field:'法院收案号'}],sources:[{file_id:'f',page:2}]}]}
  const queue=buildDecisionQueue(task,{}, {a:{action:'acknowledged',reason:'人工已核对'}})
  const group=queue.find(item=>item.key==='field-case')
  assert.equal(group.members.length,2);assert.equal(group.reasons.length,2);assert.equal(group.sources.length,1);assert.equal(group.resolved,false)
  assert.deepEqual(group.field_targets,[{template_name:'送达材料清单',field:'法院收案号'}])
  assert.equal(queue.length,3);assert.ok(queue.some(item=>item.kind==='missing'))
  assert.equal(task.issues[1].blocking,true)
  const explanations={a:{action:'acknowledged',reason:'核对'},b:{action:'acknowledged',reason:'核对'}}
  assert.equal(buildDecisionQueue(task,{},explanations)[0].resolved,false)
  const decided=structuredClone(task);decided.issues[0].detail.fact_resolved=true
  assert.equal(buildDecisionQueue(decided,{},explanations)[0].resolved,true)
})

test('legacy queue groups only identical fields, retaining every reason without acknowledging or merging distinct case-number fields',()=>{
  const issues=['案号','案号','法院收案号'].map((field,index)=>({id:String(index),kind:'field_conflict',message:'来源'+index,blocking:true,detail:{field}}))
  const result=buildDecisionQueue({issues})
  assert.equal(result.length,2);assert.equal(result[0].members.length,2);assert.equal(result[0].resolved,false)
  assert.equal(result[1].field,'法院收案号')
})

test('server bounded review anchors take precedence over an unverified legacy issue source',()=>{
  const result=buildDecisionQueue({issues:[{id:'a',kind:'classification',blocking:true,message:'待核对',detail:{file_id:'unverified',page:99}}],review_queue:[{key:'bounded',kind:'issue',issue_ids:['a'],sources:[]}]})
  assert.deepEqual(result[0].sources,[]);assert.equal(result[0].members.length,1)
})

test('persistent history restores used and expired proposals without bearer tokens and does not call a model',async()=>{
  let state,calls=0
  const chat=createAssistantConversation({getContext:context,readHistory:async()=>({has_more:true,messages:[{id:1,role:'user',content:'明确改值',status:'completed'},{id:2,role:'assistant',content:'已采用的修改',status:'completed',tool:'propose_field_change',proposal,proposal_state:'applied'}]}),request:async()=>{calls++},onChange:value=>state=value})
  chat.reset('task');await flush()
  assert.equal(state.historyReady,true);assert.equal(state.historyLimited,true);assert.equal(state.messages[1].proposal.state,'applied');assert.equal(state.messages[1].proposal.proposal_token,undefined);assert.equal(calls,0)
  chat.dispose()
})

test('pending recovery never replays a model request and turns into a completed answer on a read-only refresh',async()=>{
  let state,calls=0,finished=false
  const chat=createAssistantConversation({getContext:context,readHistory:async()=>({messages:finished?[{id:1,role:'user',content:'原问题',status:'completed'},{id:2,role:'assistant',content:'已完成答复',status:'completed'}]:[{id:1,role:'user',content:'原问题',status:'pending'}]}),request:async()=>{calls++},onChange:value=>state=value})
  chat.reset('task');await flush();assert.equal(state.serverPending,true);assert.equal(await chat.ask('重试'),false)
  finished=true;await chat.reload();assert.equal(state.serverPending,false);assert.equal(state.messages.length,2);assert.equal(calls,0);chat.dispose()
})

test('history read failure blocks sending; recovery sends bound revision and a request ID without trusting client history',async()=>{
  let state,fail=true,payload,calls=0
  const chat=createAssistantConversation({getContext:context,readHistory:async()=>{if(fail)throw new Error('offline');return {messages:[]}},request:async(_,body)=>{calls++;payload=body;return {message:'有据答复',request_id:body.request_id,user_message_id:31,assistant_message_id:32}},onChange:value=>state=value})
  chat.reset('task');await flush();assert.equal(await chat.ask('问题保留'),false);assert.match(state.historyError,/输入仍保留/)
  fail=false;await chat.reload();await chat.ask('问题保留');assert.equal(calls,1);assert.equal(payload.expected_revision,7);assert.equal(payload.source_version,'source-v1');assert.ok(payload.request_id);assert.equal(payload.history,undefined);assert.equal(state.messages[0].id,'31');chat.dispose()
})

test('unknown network outcome requires history recovery and never silently resends the uncertain request',async()=>{
  let state,calls=0
  const chat=createAssistantConversation({getContext:context,readHistory:async()=>({messages:[]}),request:async()=>{calls++;throw new Error('connection lost')},onChange:value=>state=value})
  chat.reset('task');await flush();assert.equal(await chat.ask('修改请求'),false);assert.equal(state.historyReady,false);assert.equal(state.messages[0].state,'unknown');assert.equal(await chat.ask('再次发送'),false);assert.equal(calls,1);chat.dispose()
})

test('late persisted history cannot cross task boundaries and failed history responses are not rendered as success',async()=>{
  let state,oldResolve
  const chat=createAssistantConversation({readHistory:async id=>id==='old'?new Promise(resolve=>oldResolve=resolve):{messages:[{id:'new-failed',role:'assistant',content:'请求未完成',status:'failed'}]},request:async()=>{},onChange:value=>state=value})
  chat.reset('old');chat.reset('new');await flush();oldResolve({messages:[{id:'old',role:'assistant',content:'旧案',status:'completed'}]});await flush()
  assert.equal(state.messages.length,1);assert.equal(state.messages[0].content,'请求未完成');assert.equal(state.messages[0].state,'failed');chat.dispose()
})

test('restored live proposal applies by server ID once, while applied and expired history cannot be adopted',async()=>{
  const make=state=>normalizeAssistantHistory({messages:[{id:2,role:'assistant',content:'建议',status:'completed',tool:'propose_field_change',proposal,proposal_state:state}]} )[0].proposal
  const calls=[];const app=createProposalApplication({beforeApply:async()=>'',request:async(_,body)=>{calls.push(body);return {applied:true,task:{id:'task',revision:8}}}})
  assert.equal(await app.apply('task',make('applied'),{revision:7,sourceVersion:'source-v1'}),false)
  assert.equal(await app.apply('task',make('expired'),{revision:7,sourceVersion:'source-v1'}),false)
  app.reset();assert.equal(await app.apply('task',make('pending'),{revision:7,sourceVersion:'source-v1'}),true)
  assert.deepEqual(calls,[{proposal_id:'stored-proposal',expected_revision:7}]);app.reset()
})

test('interrupted adoption has a distinct recover-only request even if another tab has already restored it',async()=>{
  const stored=normalizeAssistantHistory({messages:[{id:2,role:'assistant',content:'建议',status:'completed',tool:'propose_field_change',proposal,proposal_state:'applying',proposal_notice:'备份已保留'}]})[0].proposal
  const calls=[],applied=[];let refreshed=0
  const app=createProposalApplication({beforeApply:async()=>'',onApplied:value=>applied.push(value),onRecovered:()=>refreshed++,request:async(_,body)=>{calls.push(body);throw {response:{status:409,data:{detail:'状态已恢复，请重新核对后采用'}}}}})
  assert.equal(stored.state,'applying');assert.equal(stored.notice,'备份已保留')
  assert.equal(await app.apply('task',stored,{revision:7,sourceVersion:'source-v1'}),false)
  await app.recover('task',stored,{revision:8})
  assert.deepEqual(calls,[{proposal_id:'stored-proposal',expected_revision:8,recover_only:true}]);assert.deepEqual(applied,[]);assert.equal(refreshed,1);app.reset()
})

test('dirty inputs prevent recovery and a failed recovery keeps the reason without marking the proposal applied',async()=>{
  const stored={...proposal,persisted:true,state:'applying'},calls=[];let state,dirty=true
  const app=createProposalApplication({beforeApply:async()=>dirty?'当前有未保存输入':'',onChange:value=>state=value,request:async(_,body)=>{calls.push(body);throw {response:{status:503,data:{detail:'备份保留，请检查存储后重试恢复'}}}}})
  await app.recover('task',stored,{revision:7});assert.equal(calls.length,0);assert.match(state[proposal.id].error,/未保存/)
  dirty=false;await app.recover('task',stored,{revision:7});assert.equal(calls.length,1);assert.match(state[proposal.id].error,/备份保留/);assert.equal(state[proposal.id].applied,undefined);app.reset()
})
