import test from 'node:test'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,content,click,input,settle,esm} from './vueHarness.mjs'
import {withUploadIntentsApi,uploadImports} from './uploadRecoveryApi.mjs'
import * as experience from '../src/domain/taskExperience.js'
import * as privacy from '../src/domain/processingPrivacy.js'
import * as workflow from '../src/domain/workflow.js'
import * as review from '../src/domain/review.js'
import * as decisions from '../src/domain/decisionQueue.js'
import * as issueReview from '../src/domain/issueReview.js'
import * as fieldDecision from '../src/domain/fieldDecision.js'

const safeError='表格内容超出原表固定位置，请在表格核对中简要填写相关内容后重新生成。 [GD_ORIGINAL_TEMPLATE_OVERFLOW] 请核对字段：结案小结。'
const overflow={id:3,revision:7,status:'awaiting_review',phase:'needs_input',error:safeError,source_version:'synthetic-v1',source_changed:false,has_archive:false,can_assemble:true,can_resume:false,fields:{},catalog_status:[{seq:1,name:'虚构待核材料',found:false,requirement:'unknown'}],issues:[{id:'a',kind:'field_conflict',message:'虚构待核字段',blocking:true,detail:{field:'案号'}}],recovery_target:{template_name:'结案报告表',field:'结案小结'},execution_profile:{processing_mode:'local'}}
const Brief=await loadSfc('../src/components/ArchiveBrief.vue')
const Action=await loadSfc('../src/components/ArchiveActionBar.vue')
const Supplements=await loadSfc('../src/components/SupplementSummary.vue',{'../domain/materialCompleteness.js':await import('../src/domain/materialCompleteness.js')})

async function taskHarness(value=overflow,{failSave=false}={}){
  let current=structuredClone(value);const calls=[],revealed=[]
  // The production task/summary/action SFCs run in memory. Only the PDF editor
  // and HTTP transport are substitutes; this is not browser or native PDF QA.
  const Editor={props:['templateName','active','focusField'],emits:['saved'],setup(props,{emit,expose}){
    const text=Vue.ref(''),saved=Vue.ref('')
    expose({isLoaded:()=>true,hasUnsavedChanges:()=>text.value!==saved.value,revealField:field=>revealed.push([props.templateName,field]),saveChanges:async()=>{
      calls.push(['save',props.templateName,text.value]);if(failSave)return false
      saved.value=text.value;current={...current,revision:current.revision+1,error:'',recovery_target:null,phase:'needs_input'};emit('saved',structuredClone(current));return true
    }})
    return ()=>props.active?Vue.h('input',{'data-testid':'overflow-field','data-template':props.templateName,'data-field':props.focusField,value:text.value,onInput:event=>{text.value=event.target.value}}):null
  }}
  const client=withUploadIntentsApi({get:async path=>({data:path==='/tasks/3'?structuredClone(current):path==='/cases/c'?{id:'c',title:'虚构溢出测试',last_task_id:3,files:[]}:path.endsWith('/templates')?{templates:['立案审批表','结案报告表']}:path.includes('import-capabilities')?{supported_extensions:['.pdf'],max_upload_mb:100}:{}}),post:async(path,body)=>{calls.push(['post',path,body]);current={...current,status:'running',phase:'rendering',error:''};return {data:structuredClone(current)}},patch:async()=>{throw Error('No artificial acknowledgement is allowed')}})
  const Component=await loadSfc('../src/views/TaskProgress.vue',{...uploadImports,'vue-router':{useRoute:()=>({params:{id:'c',taskId:'3'},query:{}}),useRouter:()=>({push(){}}),onBeforeRouteLeave(){}},'../api/client':esm(client),'../stores/auth':{useAuthStore:()=>({token:'',isAdmin:false,user:{org_id:'synthetic',id:'synthetic'}})},'../domain/taskExperience.js':experience,'../domain/processingPrivacy.js':privacy,'../domain/workflow.js':workflow,'../domain/review.js':review,'../domain/decisionQueue.js':decisions,'../domain/issueReview.js':issueReview,'../domain/fieldDecision.js':fieldDecision,'../domain/useCloudConsent':{useCloudConsent:()=>({approved:Vue.ref(false),reset(){},payload:()=>({cloud_consent:false,expected_processing_mode:'local'})})},'../components/ArchiveBrief.vue':esm(Brief),'../components/ArchiveActionBar.vue':esm(Action),'../components/SupplementSummary.vue':esm(Supplements),'../components/PreviewFieldEditor.vue':esm(Editor)})
  const previous=globalThis.window;globalThis.window={addEventListener(){},removeEventListener(){},location:{protocol:'http:',host:'synthetic'}}
  const h=mount(Component);await settle();await settle()
  return {...h,calls,revealed,dispose(){h.app.unmount();globalThis.window=previous}}
}

test('overflow summary and primary action disclose a recoverable form failure rather than claiming a ready draft',()=>{
  assert.match(experience.archiveSummary(overflow).title,/原表|表格/)
  assert.doesNotMatch(experience.archiveSummary(overflow).title,/可以生成/)
  assert.equal(experience.nextArchiveAction(overflow).kind,'repair_form')
  assert.match(experience.caseTaskPresentation(overflow).label,/表格|原表/)
  assert.match(experience.caseTaskPresentation(overflow).action,/修改|处理/)
})

test('production task displays the safe overflow reason and opens the server supplied original-form field without acknowledgement',async()=>{
  const h=await taskHarness()
  try{
    assert.match(content(find(h.root,'archive-operation-error')),/GD_ORIGINAL_TEMPLATE_OVERFLOW/)
    assert.match(content(h.root),/请核对字段：结案小结/)
    assert.doesNotMatch(content(find(h.root,'supplement-summary')),/草稿可以先下载/)
    assert.equal(find(h.root,'archive-result'),undefined)
    assert.match(content(find(h.root,'archive-primary-action')),/修改原表/)
    click(find(h.root,'archive-primary-action'));await settle()
    assert.equal(find(h.root,'overflow-field').props['data-template'],'结案报告表')
    assert.equal(find(h.root,'overflow-field').props['data-field'],'结案小结')
    assert.deepEqual(h.revealed,[['结案报告表','结案小结']])
    assert.deepEqual(h.calls,[])
  }finally{h.dispose()}
})

test('saving corrected original-form content re-enables draft generation while unrelated issues remain unresolved',async()=>{
  const h=await taskHarness()
  try{
    click(find(h.root,'archive-primary-action'));await settle()
    input(find(h.root,'overflow-field'),'虚构且简要的人工填写');await settle()
    click(find(h.root,'save-template-fields'));await settle();await settle()
    assert.equal(find(h.root,'archive-operation-error'),undefined)
    assert.match(content(find(h.root,'archive-primary-action')),/生成档案草稿/)
    click(find(h.root,'archive-primary-action'));await settle();await settle()
    assert.deepEqual(h.calls,[['save','结案报告表','虚构且简要的人工填写'],['post','/tasks/3/draft',{expected_revision:8}]])
    assert.equal(find(h.root,'archive-primary-action').props.disabled,true)
  }finally{h.dispose()}
})

test('failed correction save preserves input and never generates an archive',async()=>{
  const h=await taskHarness(overflow,{failSave:true})
  try{
    click(find(h.root,'archive-primary-action'));await settle()
    input(find(h.root,'overflow-field'),'仍待保存的虚构内容');await settle()
    click(find(h.root,'save-template-fields'));await settle()
    assert.equal(find(h.root,'overflow-field').props.value,'仍待保存的虚构内容')
    assert.match(content(find(h.root,'archive-operation-error')),/保存失败/)
    assert.equal(h.calls.filter(([method])=>method==='post').length,0)
    assert.match(content(find(h.root,'archive-primary-action')),/修改原表/)
  }finally{h.dispose()}
})

test('legacy overflow without structured targets still opens editable forms and never parses field names from free text',async()=>{
  const h=await taskHarness({...overflow,recovery_target:null})
  try{click(find(h.root,'archive-primary-action'));await settle();assert.ok(find(h.root,'overflow-field'));assert.equal(find(h.root,'overflow-field').props['data-field'],'');assert.deepEqual(h.calls,[])}finally{h.dispose()}
})

test('a form-only recovery target opens that original template without inventing a field',async()=>{
  const h=await taskHarness({...overflow,recovery_target:{template_name:'结案报告表',field:null}})
  try{click(find(h.root,'archive-primary-action'));await settle();assert.equal(find(h.root,'overflow-field').props['data-template'],'结案报告表');assert.equal(find(h.root,'overflow-field').props['data-field'],'');assert.deepEqual(h.revealed,[])}finally{h.dispose()}
})

test('saving without changing the overflowing form does not claim the error is repaired or repeat generation',async()=>{
  const h=await taskHarness()
  try{click(find(h.root,'archive-primary-action'));await settle();click(find(h.root,'save-template-fields'));await settle();assert.match(content(find(h.root,'archive-operation-error')),/GD_ORIGINAL_TEMPLATE_OVERFLOW/);assert.match(content(find(h.root,'archive-primary-action')),/修改原表/);assert.deepEqual(h.calls,[])}finally{h.dispose()}
})

test('ordinary unreviewed drafts and cloud authorization waits retain their existing primary actions',async()=>{
  assert.equal(experience.nextArchiveAction({...overflow,error:'',recovery_target:null}).kind,'draft')
  assert.equal(experience.nextArchiveAction({...overflow,status:'running'}).disabled,true)
  assert.equal(experience.nextArchiveAction({...overflow,has_archive:true}).kind,'download')
  assert.equal(experience.nextArchiveAction({...overflow,source_changed:true},{cloudConsentRequired:true,cloudApproved:false}).kind,'consent')
  const h=await taskHarness({...overflow,error:'',recovery_target:null,has_archive:true,delivery_kind:'draft',phase:'draft_ready'})
  try{assert.equal(find(h.root,'archive-operation-error'),undefined);assert.match(content(find(h.root,'archive-primary-action')),/下载档案草稿/);assert.match(content(find(h.root,'supplement-summary')),/草稿可以先下载/)}finally{h.dispose()}
})
