import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'
import { reconcileIssueExpansion,toggleIssueExpansion,issueCardSummary } from '../src/domain/issueReview.js'
import { unresolvedIssues } from '../src/domain/workflow.js'

const issues=[{id:'a',kind:'field_conflict',blocking:true},{id:'b',kind:'classification',blocking:true},{id:'hint',kind:'field_extraction_review',blocking:false}]

test('initial view opens only the first genuinely unresolved blocking card',()=>{
  assert.equal(reconcileIssueExpansion(issues,{}),'a')
  // Reading an explanation does not resolve a factual conflict on the server.
  assert.equal(reconcileIssueExpansion(issues,{a:{action:'acknowledged',reason:'已对照原文'}}),'a')
  assert.equal(reconcileIssueExpansion(issues,{a:{action:'acknowledged',reason:'  '}}),'a')
  const resolved=[{...issues[0],detail:{fact_resolved:true}},...issues.slice(1)]
  assert.equal(reconcileIssueExpansion(resolved,{}),'b')
  assert.equal(reconcileIssueExpansion(resolved,{b:{action:'acknowledged',reason:'核对'}}),null)
  assert.equal(reconcileIssueExpansion([issues[2]],{}),undefined)
})

test('polling, explanations and acknowledging a card preserve the reader selection without modifying decisions',()=>{
  const decisions={a:{action:'pending',reason:'正在编辑'},b:{action:'pending',reason:''}}
  const before=structuredClone(decisions)
  let selected=reconcileIssueExpansion(issues,decisions)
  selected=toggleIssueExpansion(selected,'b')
  assert.equal(selected,'b')
  assert.equal(reconcileIssueExpansion(issues,decisions,selected),'b')
  selected=toggleIssueExpansion(selected,'b')
  assert.equal(selected,null)
  assert.equal(reconcileIssueExpansion(issues,decisions,selected),null)
  assert.deepEqual(decisions,before)
  assert.equal(unresolvedIssues(issues,decisions).length,2)
  assert.equal(reconcileIssueExpansion(issues,{b:{action:'acknowledged',reason:'已核对'}},'b'),'b')
})

test('removed or refreshed issues pick a remaining unresolved card; no issue and a later analysis can initialize',()=>{
  assert.equal(reconcileIssueExpansion([issues[1]],{},'a'),'b')
  const unloaded=reconcileIssueExpansion([],{},'a')
  assert.equal(unloaded,undefined)
  assert.equal(reconcileIssueExpansion(issues,{},unloaded),'a')
})

test('collapsed summaries retain type, real page ranges and field without inventing coordinates',()=>{
  assert.deepEqual(issueCardSummary({kind:'field_conflict',message:'需要核对',detail:{field:'案号',filename:'虚构卷宗.pdf',page_start:3,page_end:5}}),{type:'字段冲突',message:'需要核对',location:'字段：案号 · 虚构卷宗.pdf · 第 3—5 页'})
  assert.equal(issueCardSummary({kind:'ocr',detail:{filename:'虚构扫描.pdf',page:8}}).location,'虚构扫描.pdf · 第 8 页')
  for(const page of [0,-1,'bad',null])assert.equal(issueCardSummary({kind:'ocr',detail:{page}}).location,'')
})

const cardSource=await readFile(new URL('../src/components/IssueReviewCard.vue',import.meta.url),'utf8')
const {descriptor:cardDescriptor}=parse(cardSource)
const {code}=compile(cardDescriptor.template.content,{mode:'function',prefixIdentifiers:true})
const render=new Function('Vue',code)(Vue)
const Card={props:['issueId','summary','expanded','complete'],emits:['toggle'],render}
const renderCard=(expanded,complete=false)=>renderToString(Vue.createSSRApp({render:()=>Vue.h(Card,{issueId:'synthetic-item',summary:issueCardSummary({kind:'classification',message:'核对文书类型',detail:{filename:'虚构.pdf',page:4}}),expanded,complete},{default:()=>[Vue.h('textarea',{value:'未保存的核对说明'}),Vue.h('button',{type:'button'},'打开原文页')]})}))

test('actual card template exposes accessible expansion state and retains hidden inputs/source controls without confirmation',async()=>{
  const closed=await renderCard(false)
  assert.match(closed,/aria-expanded="false"/)
  assert.match(closed,/aria-controls="issue-panel-synthetic-item"/)
  assert.match(closed,/display:none/)
  assert.match(closed,/未保存的核对说明/)
  assert.match(closed,/打开原文页/)
  assert.match(closed,/第 4 页/)
  assert.match(closed,/待核对/)
  const opened=await renderCard(true)
  assert.match(opened,/aria-expanded="true"/)
  assert.doesNotMatch(opened,/display:none/)
  assert.match(opened,/待核对/)
  assert.match(await renderCard(false,true),/已核对/)
})

test('task template keeps only one optional review card and one always-open conversation after results',async()=>{
  const source=await readFile(new URL('../src/views/TaskProgress.vue',import.meta.url),'utf8')
  const {descriptor,errors}=parse(source)
  assert.deepEqual(errors,[])
  const template=descriptor.template.content
  assert.equal((template.match(/<ArchiveAssistant\b/g)||[]).length,1)
  assert.equal((template.match(/<DecisionFocus\b/g)||[]).length,1)
  assert.ok(template.indexOf('<ArchiveActionBar')<template.indexOf('<ArchiveAssistant'))
  assert.ok(template.indexOf('<SupplementSummary')<template.indexOf('<ArchiveAssistant'))
  assert.doesNotMatch(template,/progress-strip|task-aside|<IssueReviewCard|<el-checkbox/)
  assert.match(template,/已核对，无需修改/)
  assert.match(template,/v-model="issueDecisions\[activeDecision.source.id\].reason"/)
  assert.match(template,/:inert="locked"/)
})

