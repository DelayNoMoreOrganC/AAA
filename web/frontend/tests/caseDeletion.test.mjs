import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'
import { caseDeletionBlocked,createCaseDeletion,createCaseCleanupQueue } from '../src/domain/caseDeletion.js'

const record={id:'synthetic-case',title:'虚构体验案件',last_task_status:'awaiting_review'}
function harness(remove){
  let state;const deleted=[]
  const control=createCaseDeletion({remove,onChange:value=>{state=value},onDeleted:result=>deleted.push(result)})
  return {control,deleted,get state(){return state}}
}

test('opening and cancelling do not delete; explicit confirmation deletes only the frozen selected case',async()=>{
  const calls=[],h=harness(async id=>{calls.push(id);return {status:204}})
  assert.equal(await h.control.confirm(record),false)
  assert.equal(h.control.open(record),true)
  assert.equal(h.state.selected.title,'虚构体验案件')
  assert.equal(h.control.cancel(),true)
  assert.deepEqual(calls,[]);assert.deepEqual(h.deleted,[])
  h.control.open(record)
  assert.equal(await h.control.confirm({...record,id:'another-case'}),false)
  assert.deepEqual(calls,[])
  assert.equal(await h.control.confirm(record),true)
  assert.deepEqual(calls,['synthetic-case'])
  assert.deepEqual(h.deleted,[{caseId:'synthetic-case',caseTitle:record.title,cleanupPending:false,message:'案件已删除'}])
  assert.equal(h.state.opened,false)
})

test('pending/running and a state change during confirmation never send DELETE',async()=>{
  const calls=[],h=harness(async id=>{calls.push(id);return {status:204}})
  for(const last_task_status of ['pending','running']){
    const active={...record,last_task_status}
    assert.match(caseDeletionBlocked(active),/完成后才能删除/)
    assert.equal(h.control.open(active),false)
  }
  h.control.open(record)
  assert.equal(await h.control.confirm({...record,last_task_status:'running'}),false)
  assert.match(h.state.error,/完成后才能删除/)
  assert.deepEqual(calls,[])
  assert.equal(await h.control.confirm(record,true),false)
  assert.equal(await h.control.confirm({...record,can_delete:false}),false)
  assert.deepEqual(calls,[])
})

test('double confirm and cancel during DELETE cannot send duplicates or discard the pending state',async()=>{
  let resolve,calls=0
  const h=harness(()=>{calls++;return new Promise(done=>{resolve=done})})
  h.control.open(record)
  const pending=h.control.confirm(record)
  assert.equal(h.state.pending,true)
  assert.equal(await h.control.confirm(record),false)
  assert.equal(h.control.cancel(),false)
  assert.equal(h.control.open({...record,id:'other'}),false)
  resolve({status:204});await pending
  assert.equal(calls,1);assert.equal(h.deleted.length,1)
})

test('authorization/conflict/network errors keep the case and show the actual failure without success refresh',async()=>{
  for(const error of [{response:{status:409,data:{detail:'案件正在处理中，请稍后删除'}}},{response:{status:403}},{response:{status:404}},new Error('offline')]){
    const h=harness(async()=>{throw error});h.control.open(record)
    assert.equal(await h.control.confirm(record),false)
    assert.equal(h.state.opened,true);assert.equal(h.state.pending,false)
    assert.ok(h.state.error);assert.equal(h.state.selected.id,record.id)
    assert.deepEqual(h.deleted,[])
    if(error.response?.data?.detail)assert.equal(h.state.error,error.response.data.detail)
  }
})

test('202 removes the database case but explicitly reports pending file cleanup instead of complete deletion',async()=>{
  const message='案件记录已删除；工作站隔离文件待清理'
  const h=harness(async()=>({status:202,data:{deleted:true,cleanup_pending:true,message}}))
  h.control.open(record);assert.equal(await h.control.confirm(record),true)
  assert.equal(h.state.opened,false)
  assert.deepEqual(h.deleted,[{caseId:record.id,caseTitle:record.title,cleanupPending:true,message}])
})

test('unexpected responses and disposal cannot publish a fabricated deletion success',async()=>{
  const unexpected=harness(async()=>({status:200}));unexpected.control.open(record)
  assert.equal(await unexpected.control.confirm(record),false);assert.deepEqual(unexpected.deleted,[])
  let resolve
  const h=harness(()=>new Promise(done=>{resolve=done}));h.control.open(record)
  const pending=h.control.confirm(record);h.control.dispose();resolve({status:204});await pending
  assert.deepEqual(h.deleted,[]);assert.equal(h.control.open(record),false)
})

test('cleanup remains recoverable after the row disappears; retries only known 202 cases and clears only on 204',async()=>{
  let items;const calls=[],cleaned=[],responses=[{status:202,data:{message:'暂被占用，请重试清理'}},{status:204}]
  const queue=createCaseCleanupQueue({remove:async id=>{calls.push(id);return responses.shift()},onChange:value=>{items=value},onCleaned:id=>cleaned.push(id)})
  assert.equal(await queue.retry('unrelated-case'),false)
  assert.equal(queue.add({caseId:record.id,cleanupPending:false}),false)
  queue.add({caseId:record.id,caseTitle:record.title,cleanupPending:true,message:'清理待完成'})
  assert.equal(items[0].title,record.title)
  assert.equal(await queue.retry(record.id),false)
  assert.equal(items.length,1);assert.equal(items[0].message,'暂被占用，请重试清理');assert.equal(items[0].pending,false)
  assert.equal(await queue.retry(record.id),true)
  assert.deepEqual(items,[]);assert.deepEqual(cleaned,[record.id]);assert.deepEqual(calls,[record.id,record.id])
})

test('cleanup failures remain visible; repeated clicks and account changes cannot leak or restore cleanup items',async()=>{
  let items,resolve,calls=0
  const queue=createCaseCleanupQueue({remove:()=>{calls++;return new Promise(done=>{resolve=done})},onChange:value=>{items=value}})
  queue.add({caseId:record.id,cleanupPending:true})
  const pending=queue.retry(record.id)
  assert.equal(items[0].pending,true);assert.equal(await queue.retry(record.id),false);assert.equal(calls,1)
  queue.reset();assert.deepEqual(items,[])
  resolve({status:202,data:{message:'旧账号清理状态'}});await pending;assert.deepEqual(items,[])
  const failed=createCaseCleanupQueue({remove:async()=>{throw {response:{status:409,data:{detail:'文件仍被占用'}}}},onChange:value=>{items=value}})
  failed.add({caseId:record.id,cleanupPending:true})
  assert.equal(await failed.retry(record.id),false)
  assert.equal(items.length,1);assert.equal(items[0].error,'文件仍被占用');assert.equal(items[0].pending,false)
})

// Execute the real Vue template against an in-memory renderer. UI-library shells
// are replaced only at their native element boundary; clicks exercise the actual
// template handlers and production deletion state machine, without a server.
const source=await readFile(new URL('../src/components/DeleteCaseButton.vue',import.meta.url),'utf8')
const {descriptor}=parse(source)
const {code}=compile(descriptor.template.content,{mode:'function',prefixIdentifiers:true})
const render=new Function('Vue',code)(Vue)
const node=(type,text='')=>({type,text,props:{},children:[],parent:null})
const renderer=Vue.createRenderer({
  createElement:type=>node(type),createText:text=>node('#text',text),createComment:text=>node('#comment',text),
  setText:(n,text)=>{n.text=text},setElementText:(n,text)=>{n.text=text;n.children=[]},
  patchProp:(n,key,old,value)=>{n.props[key]=value},parentNode:n=>n.parent,nextSibling:n=>n.parent?.children[n.parent.children.indexOf(n)+1]||null,
  insert(n,parent,anchor=null){if(n.parent)n.parent.children.splice(n.parent.children.indexOf(n),1);n.parent=parent;const index=anchor?parent.children.indexOf(anchor):-1;if(index<0)parent.children.push(n);else parent.children.splice(index,0,n)},
  remove(n){if(n.parent)n.parent.children.splice(n.parent.children.indexOf(n),1);n.parent=null},
})
const Button={props:['disabled','loading'],setup:(props,{attrs,slots})=>()=>Vue.h('button',{...attrs,disabled:props.disabled},slots.default?.())}
const Dialog={props:['modelValue'],setup:(props,{attrs,slots})=>()=>props.modelValue?Vue.h('dialog',attrs,[...(slots.default?.()||[]),...(slots.footer?.()||[])]):null}
const Shell={setup:(_,{slots})=>()=>Vue.h('span',null,slots.default?.())}
const find=(root,testId)=>root.props?.['data-testid']===testId?root:root.children.map(child=>find(child,testId)).find(Boolean)
const textContent=root=>root.text+root.children.map(textContent).join('')
function click(target){
  if(target.props.disabled)return
  let stopped=false
  const event={stopPropagation(){stopped=true},preventDefault(){}}
  for(let current=target;current&&!stopped;current=current.parent)current.props.onClick?.(event)
}
function mountDeletion(recordValue=record){
  const calls=[],deleted=[];let rowNavigation=0
  const Component={props:['caseRecord','disabled'],render,setup(props){
    const state=Vue.ref({opened:false,pending:false,error:'',selected:null})
    const deletion=createCaseDeletion({remove:async id=>{calls.push(id);return {status:204}},onChange:value=>{state.value=value},onDeleted:result=>deleted.push(result)})
    return {state,blockedReason:Vue.computed(()=>caseDeletionBlocked(props.caseRecord,props.disabled)),open:()=>deletion.open(props.caseRecord,props.disabled),cancel:()=>deletion.cancel(),confirm:()=>deletion.confirm(props.caseRecord,props.disabled)}
  }}
  const app=renderer.createApp(Component,{caseRecord:recordValue})
  for(const [name,component] of Object.entries({'el-button':Button,'el-dialog':Dialog,'el-tooltip':Shell,'el-alert':Shell}))app.component(name,component)
  const root=node('row');root.props.onClick=()=>rowNavigation++;app.mount(root)
  return {app,root,calls,deleted,get rowNavigation(){return rowNavigation}}
}

test('real delete button stops row navigation, shows exact case/scope, and cancel retains the record',async()=>{
  const h=mountDeletion({...record,title:'虚构案 <script>不可执行</script>'})
  click(find(h.root,'delete-case'));await Vue.nextTick()
  assert.equal(h.rowNavigation,0);assert.deepEqual(h.calls,[])
  const dialog=find(h.root,'delete-case-dialog')
  assert.ok(dialog);assert.match(textContent(dialog),/虚构案 <script>不可执行<\/script>/)
  assert.match(textContent(dialog),/导入副本、分析与核对记录、网页归档成果/)
  assert.match(textContent(dialog),/原始来源文件和指定保存目录中已保存的成果副本会保留/)
  click(find(h.root,'cancel-delete-case'));await Vue.nextTick()
  assert.equal(find(h.root,'delete-case-dialog'),undefined)
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.deleted,[])
  h.app.unmount()
})

test('real confirmation sends one DELETE and active-task trigger stays disabled',async()=>{
  const h=mountDeletion();click(find(h.root,'delete-case'));await Vue.nextTick()
  click(find(h.root,'confirm-delete-case'));await Promise.resolve();await Vue.nextTick()
  assert.deepEqual(h.calls,[record.id]);assert.equal(h.deleted.length,1);assert.equal(h.rowNavigation,0)
  h.app.unmount()
  const active=mountDeletion({...record,last_task_status:'running'})
  const trigger=find(active.root,'delete-case');assert.equal(trigger.props.disabled,true)
  click(trigger);await Vue.nextTick();assert.equal(find(active.root,'delete-case-dialog'),undefined);assert.deepEqual(active.calls,[])
  active.app.unmount()
})
