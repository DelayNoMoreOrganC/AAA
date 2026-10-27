import test from 'node:test'
import assert from 'node:assert/strict'
import { createProposalApplication,normalizeProposal,proposalIsStale } from '../src/domain/assistantProposal.js'
import { createAssistantConversation } from '../src/domain/assistant.js'
const proposal={id:'synthetic-proposal',proposal_token:'memory-only-token',field:'委托人名称',before:'虚构甲',after:'虚构乙',reason:'采用后为人工修改',revision:7,source_version:'synthetic-sources',expires_at:'2099-01-01T00:00:00Z'}
const context={revision:7,sourceVersion:'synthetic-sources'}
const success={applied:true,proposal_id:proposal.id,task:{id:3,revision:8,has_archive:false,confirmed_revision:null}}
function harness({request=async()=>success,beforeApply=async()=>''}={}){let state;const applied=[];const control=createProposalApplication({request,beforeApply,onChange:value=>{state=value},onApplied:task=>applied.push(task)});return {control,applied,get state(){return state}}}

test('assistant answer offers an unpersisted proposal, and only explicit apply sends its token and frozen revision',async()=>{
  let conversationState;const calls=[]
  const conversation=createAssistantConversation({request:async()=>({message:'已准备修改建议',tool:'propose_field_change',proposal}),onChange:value=>{conversationState=value}})
  conversation.reset('3');await conversation.ask('委托人改为虚构乙')
  const received=conversationState.messages.find(item=>item.role==='assistant').proposal
  assert.deepEqual(received,proposal)
  const h=harness({request:async(id,body)=>{calls.push({id,body});return success}})
  assert.deepEqual(calls,[])
  assert.equal(await h.control.apply('3',received,context),true)
  assert.deepEqual(calls,[{id:'3',body:{proposal_token:proposal.proposal_token,expected_revision:7}}])
  assert.equal(h.applied[0].has_archive,false);assert.equal(h.applied[0].confirmed_revision,null)
  assert.equal(await h.control.apply('3',received,context),false)
  assert.equal(calls.length,1)
})
test('dirty edits block adoption after UI lock publication; input and proposal stay retryable',async()=>{
  let state,calls=0,guardCalls=0
  const control=createProposalApplication({request:async()=>{calls++;return success},onChange:value=>{state=value},beforeApply:async()=>{guardCalls++;assert.equal(state[proposal.id].pending,true);return '请先保存表格'}})
  assert.equal(await control.apply('3',proposal,context),false)
  assert.equal(calls,0);assert.equal(guardCalls,1);assert.equal(state[proposal.id].error,'请先保存表格');assert.equal(state[proposal.id].pending,false)
})
test('source/revision changes and disabled controls never issue a write',async()=>{
  let calls=0;const h=harness({request:async()=>{calls++;return success}})
  for(const changed of [{...context,revision:8},{...context,sourceVersion:'new-source'},{...context,disabled:true}])assert.equal(await h.control.apply('3',proposal,changed),false)
  assert.equal(calls,0);assert.equal(proposalIsStale(proposal,7,'new-source'),true)
  assert.equal(normalizeProposal({...proposal,revision:'7'}),null)
})
test('rapid double click sends once, stale server rejection preserves suggestion and asks to re-propose',async()=>{
  let reject,calls=0;const h=harness({request:()=>{calls++;return new Promise((_,no)=>{reject=no})}})
  const pending=h.control.apply('3',proposal,context);await Promise.resolve()
  assert.equal(await h.control.apply('3',proposal,context),false)
  reject({response:{status:409,data:{detail:'材料版本已变化'}}});assert.equal(await pending,false)
  assert.equal(calls,1);assert.equal(h.state[proposal.id].stale,true);assert.match(h.state[proposal.id].error,/重新告诉助理/)
  assert.equal(await h.control.apply('3',proposal,context),false);assert.deepEqual(h.applied,[])
})
test('failed network remains retryable, and leaving the task discards a late success',async()=>{
  let calls=0;const h=harness({request:async()=>{if(++calls===1)throw new Error('断网');return success}})
  assert.equal(await h.control.apply('3',proposal,context),false);assert.equal(h.state[proposal.id].stale,false)
  assert.equal(await h.control.apply('3',proposal,context),true)
  let resolve;const late=harness({request:()=>new Promise(done=>{resolve=done})})
  const pending=late.control.apply('3',proposal,context);await Promise.resolve();late.control.reset();resolve(success);assert.equal(await pending,false);assert.deepEqual(late.state,{});assert.deepEqual(late.applied,[])
})

