import test from 'node:test'
import * as positioning from '../src/domain/companionPosition.js'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,findType,content,click,input,settle} from './vueHarness.mjs'
import {companionPresentation} from '../src/domain/taskExperience.js'

test('mascot uses persisted task state without labelling drafts or historical output as complete',()=>{
  const draft={status:'awaiting_review',phase:'draft_ready',has_archive:true,delivery_kind:'draft'}
  assert.equal(companionPresentation().state,'idle')
  assert.equal(companionPresentation({status:'running'}).state,'working')
  assert.equal(companionPresentation({...draft,status:'failed'}).state,'error')
  assert.equal(companionPresentation({...draft,error:'layout failure'}).state,'error')
  assert.equal(companionPresentation(draft,{unresolved:2}).state,'question')
  assert.match(companionPresentation(draft,{unresolved:2}).label,/草稿.*补充与核对/)
  assert.doesNotMatch(companionPresentation(draft,{unresolved:2}).label,/\d+ 项待核对/)
  assert.equal(companionPresentation(draft).short,'草稿已生成')
  assert.match(companionPresentation(draft,{historical:true}).label,/历史/)
  assert.match(companionPresentation({...draft,source_changed:true}).label,/补件/)
  assert.equal(companionPresentation(draft,{consent:true}).short,'等待授权')
  assert.equal(companionPresentation({status:'awaiting_review'}).short,'待生成草稿')
})

test('assistant content mounts only on demand; close, hide and evidence navigation preserve unsent content',async()=>{
  const previous=globalThis.window;globalThis.window={matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}})}
  let starts=0,stops=0;const actions=[],suppressed=Vue.ref(false)
  const Dock=await loadSfc('../src/components/ArchiveCompanion.vue',{'../domain/companionPosition.js':positioning})
  const Chat={setup(){starts++;const value=Vue.ref('');Vue.onUnmounted(()=>stops++);return()=>Vue.h('input',{'data-testid':'draft',value:value.value,onInput:e=>value.value=e.target.value})}}
  const Parent={setup:()=>()=>Vue.h(Dock,{suppressed:suppressed.value,actions:[{kind:'sources',label:'查看原文'}],onAction:kind=>actions.push(kind)},{default:()=>Vue.h(Chat)})}
  const h=mount(Parent)
  try{
    await settle();assert.equal(starts,0)
    click(find(h.root,'companion-open'));await settle();assert.equal(starts,1)
    input(find(h.root,'draft'),'尚未发送');await settle()
    click(find(h.root,'companion-close'));await settle();assert.equal(find(h.root,'companion-panel').style.display,'none')
    click(find(h.root,'companion-open'));await settle();assert.equal(find(h.root,'draft').props.value,'尚未发送')
    click(find(h.root,'companion-action-sources'));await settle();assert.deepEqual(actions,['sources']);assert.equal(stops,0)
    click(find(h.root,'companion-open'));await settle();suppressed.value=true;await settle();assert.equal(find(h.root,'companion-panel').style.display,'none')
    suppressed.value=false;await settle();click(find(h.root,'companion-open'));await settle();click(find(h.root,'companion-hide'));await settle()
    assert.ok(find(h.root,'companion-restore'));click(find(h.root,'companion-restore'));await settle();click(find(h.root,'companion-open'));await settle()
    assert.equal(starts,1);assert.equal(find(h.root,'draft').props.value,'尚未发送');assert.equal(stops,0)
    click(find(h.root,'companion-motion'));await settle();assert.equal(findType(h.root,'img').props.src,'/pet/juanzhu-actions-v2.png')
    assert.match(content(h.root),/开启动效/)
  }finally{h.app.unmount();globalThis.window=previous}
  assert.equal(stops,1)
})

test('reduced motion uses local still asset and disabled actions do not dispatch',async()=>{
  const previous=globalThis.window;globalThis.window={matchMedia:()=>({matches:true,addEventListener(){},removeEventListener(){}})}
  const actions=[];const Dock=await loadSfc('../src/components/ArchiveCompanion.vue',{'../domain/companionPosition.js':positioning})
  const h=mount(Dock,{actions:[{kind:'fields',label:'填写表格',disabled:true}],onAction:v=>actions.push(v)})
  try{await settle();assert.equal(findType(h.root,'img').props.src,'/pet/juanzhu-actions-v2.png');click(find(h.root,'companion-open'));await settle();click(find(h.root,'companion-action-fields'));assert.deepEqual(actions,[]);assert.match(content(h.root),/素材说明/)}finally{h.app.unmount();globalThis.window=previous}
})

test('reading preview changes action only; remount returns to automatic task animation',async()=>{
  const previous=globalThis.window,stored=new Map()
  globalThis.window={localStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)}}
  const Dock=await loadSfc('../src/components/ArchiveCompanion.vue',{'../domain/companionPosition.js':positioning})
  let h=mount(Dock)
  try{
    await settle();click(find(h.root,'companion-open'));await settle()
    assert.doesNotMatch(content(h.root),/换装|墨镜|休闲/)
    click(find(h.root,'companion-motion-reading'));await settle()
    assert.equal(find(h.root,'companion-motion-reading').props['aria-pressed'],true)
    assert.ok(parseFloat(findType(h.root,'img').props.style.top)<0)
    assert.equal(find(h.root,'companion-open').props['aria-expanded'],true)
    h.app.unmount();h=mount(Dock,{presentation:{state:'working',label:'正在整理'}});await settle()
    assert.equal(find(h.root,'companion-motion-auto').props['aria-pressed'],true)
    assert.ok(parseFloat(findType(h.root,'img').props.style.top)<0)
  }finally{h.app.unmount();globalThis.window=previous}
})
