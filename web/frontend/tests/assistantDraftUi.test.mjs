// Production SFCs compiled and mounted in the in-memory Vue renderer.
// All records below are synthetic; these are not browser or live API tests.
import test from 'node:test'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,findType,content,click,input,settle,esm} from './vueHarness.mjs'
import * as conversation from '../src/domain/assistant.js'
import * as drafts from '../src/domain/assistantDraft.js'
import * as proposals from '../src/domain/assistantProposal.js'
import * as workflow from '../src/domain/workflow.js'

const record=(overrides={})=>({content:'',version:0,revision:7,source_version:'synthetic-v1',task_revision:7,task_source_version:'synthetic-v1',writable:true,notice:'',updated_at:null,consumed_request_id:null,...overrides})
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
async function harness(options={}){
  let remote=record(options.record),failRead=options.failRead||false,history=options.history||[]
  const writes=[],posts=[],dirty=[]
  const client={
    get:async path=>{
      if(path.endsWith('/draft')){if(failRead)throw Error('synthetic unavailable');return {data:{...remote}}}
      return {data:{messages:history}}
    },
    put:async(_path,body)=>{
      writes.push({...body})
      if(body.expected_version!==remote.version||body.expected_revision!==remote.task_revision||body.source_version!==remote.task_source_version)throw {response:{status:409}}
      remote={...remote,content:body.content,version:remote.version+1,revision:body.expected_revision,source_version:body.source_version,consumed_request_id:null}
      return {data:{...remote}}
    },
    post:async(_path,body)=>{
      posts.push({...body})
      assert.equal(body.draft_version,remote.version);assert.equal(body.message,remote.content.trim())
      remote={...remote,content:'',version:remote.version+1,consumed_request_id:body.request_id}
      history=[{id:1,role:'user',content:body.message,status:'pending'}]
      if(options.response)return {data:await options.response.promise}
      return {data:{message:'全虚构只读回复',tool:'review_archive'}}
    },
  }
  const Component=await loadSfc('../src/components/ArchiveAssistant.vue',{'../api/client':esm(client),'../domain/assistant.js':conversation,'../domain/assistantDraft.js':drafts,'../domain/assistantProposal.js':proposals,'../domain/workflow.js':workflow})
  const props=Vue.reactive({taskId:'3',accountScope:'org:synthetic-user',revision:7,sourceVersion:'synthetic-v1',onDraftDirty:value=>dirty.push(value),...options.props})
  const Host={setup:()=>()=>Vue.h(Component,props)},h=mount(Host)
  await settle()
  return {...h,props,writes,posts,dirty,get remote(){return remote},setRemote(value){remote={...remote,...value}},setFailRead(value){failRead=value}}
}
const type=async(h,value)=>{input(find(h.root,'assistant-question'),value);await settle()}
const sync=async h=>{click(find(h.root,'draft-sync'));await settle()}
const send=async h=>{findType(h.root,'form').props.onSubmit({preventDefault(){}});await settle()}
const byClass=(node,cls)=>node.props.class===cls?node:node.children.map(child=>byClass(child,cls)).find(Boolean)

test('restored text suppresses examples and failed-message retry cannot replace a different local draft',async()=>{
  const h=await harness({record:{content:'全虚构已经保存的新要求',version:2}})
  try{assert.equal(byClass(h.root,'examples'),undefined);assert.equal(find(h.root,'assistant-question').props.value,'全虚构已经保存的新要求');assert.deepEqual(h.posts,[])}finally{h.app.unmount()}
  const retry=await harness({record:{content:'全虚构已经保存的新要求',version:2},history:[{id:1,role:'user',content:'全虚构旧问题',status:'failed'}]})
  try{click(find(retry.root,'assistant-retry-question'));await settle();assert.equal(find(retry.root,'assistant-question').props.value,'全虚构已经保存的新要求');assert.match(content(find(retry.root,'assistant-shortcut-notice')),/先处理当前草稿/);assert.deepEqual(retry.posts,[]);assert.deepEqual(retry.writes,[])}finally{retry.app.unmount()}
})

test('normal empty input has no permanent synced status and new unsynced text emits navigation dirtiness',async()=>{
  const h=await harness()
  try{assert.equal(find(h.root,'assistant-draft-status'),undefined);await type(h,'全虚构待保存文字');assert.equal(h.dirty.at(-1),true);assert.match(content(find(h.root,'assistant-draft-status')),/未同步/);await sync(h);assert.equal(h.dirty.at(-1),false);assert.match(content(find(h.root,'assistant-draft-status')),/已同步到工作站/);assert.equal(h.remote.content,'全虚构待保存文字');assert.deepEqual(h.posts,[])}finally{h.app.unmount()}
})

test('missing draft endpoint leaves locally typed text visibly unsynced and never sends it as saved',async()=>{
  const h=await harness({failRead:true})
  try{await type(h,'全虚构离线文字');assert.equal(find(h.root,'assistant-question').props.value,'全虚构离线文字');assert.equal(find(h.root,'assistant-send').props.disabled,true);assert.equal(h.dirty.at(-1),true);assert.match(content(h.root),/未能读取工作站草稿/);assert.equal(h.writes.length,0);assert.equal(h.posts.length,0)}finally{h.app.unmount()}
})

test('a cross-tab CAS conflict displays both texts and only explicit local selection permits saving over that version',async()=>{
  const h=await harness()
  try{await type(h,'全虚构本机文字');h.setRemote({content:'全虚构另一标签文字',version:1});await sync(h);assert.match(content(find(h.root,'assistant-draft-conflict')),/本机文字/);assert.match(content(find(h.root,'assistant-draft-conflict')),/另一标签文字/);assert.equal(h.remote.content,'全虚构另一标签文字');assert.equal(find(h.root,'assistant-send').props.disabled,true);click(find(h.root,'draft-keep-local'));await settle();await sync(h);assert.equal(h.remote.content,'全虚构本机文字');assert.equal(h.writes.at(-1).expected_version,1);assert.equal(h.dirty.at(-1),false)}finally{h.app.unmount()}
})

test('same-task revision updates retain typed text until explicit current-version continuation',async()=>{
  const h=await harness({record:{content:'全虚构旧版本要求',version:2}})
  try{await type(h,'全虚构正在输入的要求');h.props.revision=8;h.setRemote({task_revision:8});await settle();assert.equal(find(h.root,'assistant-question').props.value,'全虚构正在输入的要求');assert.ok(find(h.root,'assistant-draft-old-context'));assert.equal(find(h.root,'assistant-send').props.disabled,true);assert.equal(h.writes.length,0);click(find(h.root,'draft-continue-context'));await settle();await sync(h);assert.equal(h.writes.at(-1).expected_revision,8);assert.equal(h.remote.content,'全虚构正在输入的要求')}finally{h.app.unmount()}
})

test('atomic consumption preserves edits made during a model wait and saves from the consumed version',async()=>{
  const response=deferred(),h=await harness({response})
  try{await type(h,'全虚构发送A');await send(h);assert.equal(h.posts.length,1);assert.equal(h.posts[0].draft_version,1);assert.match(h.posts[0].request_id,/^[a-f0-9-]{36}$/i);await type(h,'全虚构发送期间输入B');await new Promise(resolve=>setTimeout(resolve,550));assert.equal(h.writes.length,1,'autosave pauses while request consumption is unresolved');response.resolve({message:'全虚构已完成回复',tool:'review_archive'});await settle();assert.equal(find(h.root,'assistant-question').props.value,'全虚构发送期间输入B');await sync(h);assert.equal(h.writes.at(-1).expected_version,2);assert.equal(h.remote.content,'全虚构发送期间输入B');assert.equal(h.writes.some(body=>body.content===''),false)}finally{h.app.unmount()}
})

test('lost POST reply after atomic consumption clears only the matching sent text and reads its pending history without resending',async()=>{
  const response=deferred(),h=await harness({response})
  try{await type(h,'全虚构已登记的问题');await send(h);response.reject(Error('synthetic response lost'));await settle();assert.equal(find(h.root,'assistant-question').props.value,'');assert.equal(h.remote.consumed_request_id,h.posts[0].request_id);assert.equal(h.writes.length,1);assert.ok(find(h.root,'assistant-history-error'));assert.equal(find(h.root,'assistant-send').props.disabled,true);click(find(h.root,'assistant-reload-history'));await settle();assert.ok(find(h.root,'assistant-restored-pending'));assert.match(content(h.root),/全虚构已登记的问题/);assert.equal(h.posts.length,1)}finally{h.app.unmount()}
})

test('historical draft remains readable but cannot be edited or sent, and an account switch loads only its own draft',async()=>{
  const h=await harness({record:{content:'全虚构历史草稿',version:3,writable:false},props:{draftReadOnly:true}})
  try{assert.equal(find(h.root,'assistant-question').props.value,'全虚构历史草稿');assert.equal(find(h.root,'assistant-question').props.disabled,true);await type(h,'不应覆盖');assert.equal(find(h.root,'assistant-question').props.value,'全虚构历史草稿');assert.equal(find(h.root,'assistant-send').props.disabled,true);h.setRemote({content:'全虚构另一账号草稿',version:1,writable:true});h.props.accountScope='org:other-synthetic-user';h.props.draftReadOnly=false;await settle();assert.equal(find(h.root,'assistant-question').props.value,'全虚构另一账号草稿');assert.equal(h.writes.length,0);assert.equal(h.posts.length,0)}finally{h.app.unmount()}
})
