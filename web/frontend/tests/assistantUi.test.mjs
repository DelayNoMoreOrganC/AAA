import {withUploadIntentsApi,uploadImports,settleUploads} from './uploadRecoveryApi.mjs'
import test from 'node:test'
import assert from 'node:assert/strict'
import { Vue,loadSfc,mount,find,findType,content,click,input,settle,esm,Shell } from './vueHarness.mjs'
import * as assistant from '../src/domain/assistant.js'
import * as draftDomain from '../src/domain/assistantDraft.js'
import {withAssistantDraftApi} from './assistantDraftApi.mjs'
import * as proposalDomain from '../src/domain/assistantProposal.js'
import * as workflow from '../src/domain/workflow.js'
import * as experience from '../src/domain/taskExperience.js'
import * as review from '../src/domain/review.js'
import * as privacy from '../src/domain/processingPrivacy.js'
import * as decisions from '../src/domain/decisionQueue.js'
import * as issueReview from '../src/domain/issueReview.js'
import * as fieldDecision from '../src/domain/fieldDecision.js'
const proposal={id:'proposal-ui',proposal_token:'only-in-memory',field:'委托人名称',before:'虚构甲',after:'虚构乙',reason:'采用后为人工修改',revision:7,source_version:'synthetic-v1',expires_at:'2099-01-01T00:00:00Z'}
const answer={message:'已准备修改建议，请核对前后内容后采用。',tool:'propose_field_change',proposal}
async function assistantComponent(client){return loadSfc('../src/components/ArchiveAssistant.vue',{'../api/client':esm(withAssistantDraftApi({get:async()=>({data:{messages:[]}}),...client})),'../domain/assistant.js':assistant,'../domain/assistantDraft.js':draftDomain,'../domain/workflow.js':workflow,'../domain/assistantProposal.js':proposalDomain})}
async function ask(h){await settle();input(find(h.root,'assistant-question'),'委托人改为虚构乙');await settle();findType(h.root,'form').props.onSubmit({preventDefault(){}});await settle()}

test('production assistant SFC keeps conversation open and requires an explicit adoption click after before/after review',async()=>{
  const calls=[],applied=[]
  const Component=await assistantComponent({post:async(path,body)=>{calls.push({path,body});return {data:path.endsWith('/apply')?{applied:true,task:{id:'3',revision:8,has_archive:false}}:answer}}})
  const h=mount(Component,{taskId:'3',mode:'deepseek_cloud',revision:7,sourceVersion:'synthetic-v1',beforeApply:async()=>'',onApplied:task=>applied.push(task)})
  assert.ok(find(h.root,'assistant-question'));assert.equal(findType(h.root,'details'),undefined)
  await ask(h);assert.equal(calls.length,1);assert.equal(applied.length,0)
  const suggestion=find(h.root,'assistant-proposal');assert.match(content(suggestion),/虚构甲/);assert.match(content(suggestion),/虚构乙/);assert.match(content(suggestion),/尚未采用/)
  click(find(h.root,'apply-assistant-proposal'));await settle()
  assert.equal(calls.length,2);assert.deepEqual(calls[1].body,{proposal_token:'only-in-memory',expected_revision:7});assert.equal(applied.length,1)
  assert.match(content(find(h.root,'assistant-proposal')),/已采用/);assert.equal(find(h.root,'apply-assistant-proposal'),undefined)
  h.app.unmount()
})
test('production assistant preserves proposal and error when unsaved editor guard blocks its write',async()=>{
  let calls=0;const Component=await assistantComponent({post:async()=>{calls++;return {data:answer}}})
  const h=mount(Component,{taskId:'3',revision:7,sourceVersion:'synthetic-v1',beforeApply:async()=>'表格尚未保存'})
  await ask(h);click(find(h.root,'apply-assistant-proposal'));await settle()
  assert.equal(calls,1);assert.match(content(h.root),/表格尚未保存/);assert.ok(find(h.root,'apply-assistant-proposal'));assert.match(content(h.root),/虚构乙/)
  h.app.unmount()
})
test('production assistant shows failed response without fake answer and permits typing while task is running',async()=>{
  const Component=await assistantComponent({post:async()=>{throw {response:{status:409,data:{detail:'任务正在生成草稿'}}}}})
  const h=mount(Component,{taskId:'3',revision:7,sourceVersion:'synthetic-v1'});await ask(h);assert.match(content(h.root),/任务正在生成草稿/);assert.equal(find(h.root,'assistant-proposal'),undefined);assert.equal(find(h.root,'assistant-question').props.value,'委托人改为虚构乙');h.app.unmount()
  const active=mount(Component,{taskId:'3',busy:true});await settle();input(find(active.root,'assistant-question'),'稍后修改');await settle();assert.equal(find(active.root,'assistant-question').props.disabled,false);assert.equal(find(active.root,'assistant-question').props.value,'稍后修改');assert.equal(find(active.root,'assistant-send').props.disabled,true);active.app.unmount()
})
const Brief=await loadSfc('../src/components/ArchiveBrief.vue')
const Action=await loadSfc('../src/components/ArchiveActionBar.vue')
const Supplements=await loadSfc('../src/components/SupplementSummary.vue',{'../domain/materialCompleteness.js':await import('../src/domain/materialCompleteness.js')})
const Focus=await loadSfc('../src/components/DecisionFocus.vue')
const baseline={id:'3',revision:7,status:'awaiting_review',phase:'draft_ready',delivery_kind:'draft',source_version:'synthetic-v1',has_archive:true,has_docx:true,can_assemble:true,formal_ready:false,fields:{},issues:[{id:'a',kind:'field_conflict',message:'案号需核对',blocking:true,detail:{field:'案号'}}],catalog_status:[{seq:1,name:'虚构缺项',found:false,requirement:'unknown'}],artifacts:[]}
async function taskHarness(value=baseline,options={}){
  let current=structuredClone(value);const calls=[],listeners=new Map();let leaveGuard=null
  const client={get:async path=>{calls.push(['get',path]);if(options.get){const data=await options.get(path);if(data!==undefined)return {data}};if(path==='/tasks/3')return {data:structuredClone(current)};if(path==='/cases/c')return {data:{id:'c',title:'虚构体验卷',last_task_id:'3',files:[{id:'synthetic-file',filename:'虚构.pdf'}]}};if(path.endsWith('/templates'))return {data:{templates:['立案审批表']}};if(path.includes('import-capabilities'))return {data:{supported_extensions:['.pdf'],max_upload_mb:100}};return {data:{}}},post:async(path,body,config)=>{calls.push(['post',path,body]);if(options.post){const data=await options.post(path,body,current,config);if(data!==undefined){if(data?.id===current.id)current=data;return {data}}};current={...current,status:'running',phase:'rendering',has_archive:false};return {data:structuredClone(current)}},patch:async(path,body)=>{calls.push(['patch',path,body]);if(options.failPatch)throw Error('测试保存失败');current={...current,revision:current.revision+1,fields:{...current.fields,...JSON.parse(JSON.stringify(body.fields))}};return {data:current}}}
  const Component=await loadSfc('../src/views/TaskProgress.vue',{...uploadImports,'vue-router':{useRoute:()=>({params:{id:'c',taskId:'3'},query:{}}),useRouter:()=>({push(){}}),onBeforeRouteLeave(callback){leaveGuard=callback}},'../api/client':esm(withUploadIntentsApi(client)),'../stores/auth':{useAuthStore:()=>({token:'',isAdmin:false,user:{org_id:'synthetic-org',id:'synthetic-user'}})},...(options.elementPlus?{'element-plus':options.elementPlus}:{}),'../domain/issueReview.js':issueReview,'../domain/fieldDecision.js':fieldDecision,'../domain/decisionQueue.js':decisions,'../domain/taskExperience.js':experience,'../domain/processingPrivacy.js':privacy,'../domain/review.js':review,'../domain/workflow.js':workflow,'../domain/useCloudConsent':{useCloudConsent:()=>({approved:Vue.ref(false),reset(){},payload:()=>({cloud_consent:false,expected_processing_mode:'local'})})},'../components/ArchiveBrief.vue':esm(Brief),'../components/ArchiveActionBar.vue':esm(Action),'../components/SupplementSummary.vue':esm(Supplements),'../components/DecisionFocus.vue':esm(Focus),...(options.components||{})})
  const previous=globalThis.window;globalThis.window={addEventListener(name,callback){listeners.set(name,callback)},removeEventListener(name){listeners.delete(name)},location:{protocol:'http:',host:'test'}}
  const h=mount(Component,{},options.globalComponents||{});await settle()
  return {...h,calls,listeners,leave:()=>leaveGuard(),setTask(value){current=structuredClone(value)},dispose(){h.app.unmount();globalThis.window=previous}}
}
test('production task SFC lands on draft download with consolidated unknown-rule materials and no default decision form',async()=>{
  const h=await taskHarness()
  try{assert.match(content(find(h.root,'archive-primary-action')),/下载档案草稿/);assert.ok(find(h.root,'archive-result'));assert.match(content(find(h.root,'supplement-summary')),/适用性待核验/);assert.equal(find(h.root,'decision-focus'),undefined);assert.equal(find(h.root,'issue-review-reason'),undefined);assert.ok(!h.calls.some(([method])=>method==='post'||method==='patch'))}finally{h.dispose()}
})

test('policy repair task action posts the exact plan and keeps existing result access',async()=>{
  const token='a'.repeat(64)
  const h=await taskHarness({...baseline,can_resume:true,issues:[],execution_profile:{processing_mode:'ollama_local'},
    form_policy_update:{available:true,token,fields:['结案小结']}})
  try{
    assert.match(content(find(h.root,'archive-primary-action')),/更新表单草稿/)
    assert.ok(find(h.root,'archive-result'))
    click(find(h.root,'archive-primary-action'));await settle()
    const calls=h.calls.filter(([method])=>method==='post')
    assert.deepEqual(calls,[['post','/tasks/3/resume',{cloud_consent:false,expected_processing_mode:'ollama_local',form_policy_token:token}]])
  }finally{h.dispose()}
})

test('policy repair refresh keeps the captured token when the old task no longer offers a plan',async()=>{
  const token='a'.repeat(64)
  const value={...baseline,can_resume:true,issues:[],execution_profile:{processing_mode:'ollama_local'},
    form_policy_update:{available:true,token,fields:['结案小结']}}
  const h=await taskHarness(value)
  try{
    h.setTask({...value,form_policy_update:null})
    click(find(h.root,'archive-primary-action'));await settle()
    const calls=h.calls.filter(([method])=>method==='post')
    assert.deepEqual(calls,[['post','/tasks/3/resume',{cloud_consent:false,expected_processing_mode:'ollama_local',form_policy_token:token}]])
  }finally{h.dispose()}
})

test('policy repair refresh cannot silently adopt a new rule token',async()=>{
  const value={...baseline,can_resume:true,issues:[],execution_profile:{processing_mode:'ollama_local'},
    form_policy_update:{available:true,token:'a'.repeat(64),fields:['结案小结']}}
  const h=await taskHarness(value)
  try{
    h.setTask({...value,form_policy_update:{...value.form_policy_update,token:'b'.repeat(64)}})
    click(find(h.root,'archive-primary-action'));await settle()
    assert.equal(h.calls.filter(([method])=>method==='post').length,0)
    assert.match(content(h.root),/填写规则已变化/)
    assert.ok(find(h.root,'archive-result'))
  }finally{h.dispose()}
})

test('policy repair cloud task asks consent despite historical cloud approval',async()=>{
  const h=await taskHarness({...baseline,can_resume:true,issues:[],
    execution_profile:{processing_mode:'deepseek_cloud',cloud_consent:true,authorized_source_version:baseline.source_version},
    form_policy_update:{available:true,token:'a'.repeat(64),fields:['结案小结']}})
  try{
    assert.match(content(find(h.root,'archive-primary-action')),/确认本次栏目更新/)
    assert.ok(find(h.root,'supplement-consent'))
    assert.ok(find(h.root,'archive-result'))
    assert.equal(h.calls.filter(([method])=>method==='post').length,0)
  }finally{h.dispose()}
})
test('production task shows original-cell limits as brief-entry work without blocking draft download or inventing missing materials',async()=>{
  const h=await taskHarness({...baseline,fields:{_form_drafts:{fields:{
    '案情简介':{status:'generated',source_count:2},
    '法院文件清单':{status:'insufficient',reason_codes:['no_document_sources'],source_count:0},
    '委托人联系地址及电话':{status:'insufficient',reason_codes:['draft_too_long_for_original_cell'],source_count:3},
    '案件或项目名称':{status:'insufficient',reason_codes:['draft_too_long_for_original_cell'],source_count:2},
  }}}})
  try{
    const byClass=(node,css)=>node.props.class===css?node:node.children.map(child=>byClass(child,css)).find(Boolean)
    assert.equal(byClass(h.root,'draft-summary'),undefined)
    click(find(h.root,'archive-tools'));await settle()
    const summary=byClass(h.root,'draft-summary')
    assert.match(content(summary),/案情简介 · 有依据草稿/)
    assert.match(content(summary),/法院文件清单 · 待补全依据/)
    assert.match(content(summary),/委托人联系地址及电话 · 待简要填写/)
    assert.match(content(summary),/案件或项目名称 · 待简要填写/)
    assert.doesNotMatch(content(summary),/委托人联系地址及电话 · 材料不足|案件或项目名称 · 材料不足/)
    assert.match(content(find(h.root,'archive-primary-action')),/下载档案草稿/)
    assert.equal(find(h.root,'archive-primary-action').props.disabled,false)
    click(findType(summary,'button'));await settle()
    assert.match(content(h.root),/系统表核对/)
    assert.equal(h.calls.filter(([method])=>method==='post'||method==='patch').length,0)
  }finally{h.dispose()}
})

test('production task generates a complete draft with unresolved issues without sending artificial acknowledgements',async()=>{
  const h=await taskHarness({...baseline,has_archive:false,delivery_kind:null,phase:'needs_input'})
  try{assert.match(content(find(h.root,'archive-primary-action')),/生成档案草稿/);click(find(h.root,'archive-primary-action'));await settle();assert.deepEqual(h.calls.filter(([method])=>method==='post'),[['post','/tasks/3/draft',{expected_revision:7}]]);assert.equal(h.calls.filter(([method])=>method==='patch').length,0);assert.equal(find(h.root,'archive-primary-action').props.disabled,true)}finally{h.dispose()}
})

test('missing date is reachable directly from the draft and focuses only its intake field without writing',async()=>{
  const seen=[]
  const Editor={props:['templateName','focusField'],setup:props=>()=>{seen.push([props.templateName,props.focusField]);return Vue.h('div',{'data-testid':'focused-fixture-editor'},props.templateName+':'+props.focusField)}}
  const fields={_form_drafts:{fields:{'立案审批日期':{status:'insufficient'},'案情简介':{status:'generated'}}}}
  const h=await taskHarness({...baseline,fields},{components:{'../components/PreviewFieldEditor.vue':esm(Editor)}})
  try{
    assert.match(content(find(h.root,'pending-form-fields')),/立案日期/)
    assert.doesNotMatch(content(find(h.root,'pending-form-fields')),/案情简介/)
    click(find(h.root,'fill-立案审批日期'));await settle()
    assert.ok(seen.some(([name,field])=>name==='立案审批表'&&field==='立案审批日期'))
    assert.equal(h.calls.filter(([method])=>['post','patch'].includes(method)).length,0)
    assert.equal(find(h.root,'archive-primary-action').props.disabled,false)
  }finally{h.dispose()}
  const retained=await taskHarness({...baseline,fields:{...fields,_original_forms:{'立案审批表':[{file_id:'original',page:1}]}}})
  try{assert.equal(find(retained.root,'pending-form-fields'),undefined)}finally{retained.dispose()}
})
test('production task opens optional single decision without saving or changing its unresolved count',async()=>{
  const h=await taskHarness()
  try{const more=find(h.root,'supplement-summary').children;const findButton=n=>n.type==='button'&&content(n).includes('识别疑问')?n:n.children.map(findButton).find(Boolean);click(findButton(find(h.root,'supplement-summary')));await settle();assert.ok(find(h.root,'decision-focus'));assert.match(content(find(h.root,'decision-focus')),/1 项尚未处理/);assert.match(content(find(h.root,'decision-focus')),/保存核对说明不会解决事实冲突/);assert.equal(find(h.root,'acknowledge-decision'),undefined);assert.equal(h.calls.filter(([method])=>method==='patch'||method==='post').length,0)}finally{h.dispose()}
})

const caseTypes=await import('../src/domain/caseTypes.js')
async function dashboardHarness(){
  const calls=[],routes=[]
  const Component=await loadSfc('../src/views/Dashboard.vue',{...uploadImports,'vue-router':{useRoute:()=>({query:{}}),useRouter:()=>({push:path=>routes.push(path),replace:async()=>{}}),onBeforeRouteLeave(){},onBeforeRouteUpdate(){}},'../api/client':esm(withUploadIntentsApi({get:async path=>({data:path.includes('readiness')?{mode:'local',ready:true}:{supported_extensions:['.pdf'],max_upload_mb:100}}),post:async(path,body,config)=>{calls.push({path,body,config});return {data:path==='/cases'?{id:'synthetic-created'}:path.endsWith('/generate')?{id:10}:{}}}})),'../stores/auth':{useAuthStore:()=>({isAdmin:false})},'../domain/workflow.js':workflow,'../domain/caseTypes.js':caseTypes,'../domain/decisionQueue.js':decisions,'../domain/processingPrivacy.js':privacy,'../domain/useCloudConsent':{useCloudConsent:()=>({approved:Vue.ref(false),reset(){},payload:()=>({cloud_consent:false,expected_processing_mode:'local'})})}})
  const h=mount(Component);await settle();return {...h,calls,routes}
}
test('production home has one dropzone and requires an explicit case type before importing synthetic files',async()=>{
  const h=await dashboardHarness()
  try{assert.ok(find(h.root,'material-drop'));assert.equal(find(h.root,'archive-import-dialog'),undefined);assert.match(content(find(h.root,'dashboard-heading')),/整理一份档案/)
    const file=new File(['%PDF synthetic test'], '虚构卷.pdf',{type:'application/pdf'})
    find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file]}});await settleUploads(h.root)
    assert.equal(find(h.root,'case-type').props.value,'');assert.equal(find(h.root,'start-archive').props.disabled,true);assert.deepEqual(h.calls,[])
    find(h.root,'case-type').props.onChange({target:{value:'civil'}});await settleUploads(h.root);assert.equal(find(h.root,'start-archive').props.disabled,false)
    click(find(h.root,'start-archive'));await settleUploads(h.root)
    assert.deepEqual(h.calls.find(call=>call.path==='/cases').body,{title:'虚构卷',case_type:'civil',stage:''})
    const generation=h.calls.find(call=>call.path.endsWith('/generate'));assert.equal(generation.body.expected_processing_mode,'local');assert.equal(generation.body.cloud_consent,false)
    assert.match(h.calls.find(call=>call.path.endsWith('/files')).config.headers['Idempotency-Key'],/^[0-9a-f-]{36}$/i)
    assert.deepEqual(h.routes,['/cases/synthetic-created/tasks/10'])
  }finally{h.app.unmount()}
})

test('home explicitly removing an unsupported item keeps imported material and waits for another start click',async()=>{
  const h=await dashboardHarness()
  try{
    find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[new File(['pdf'],'保留.pdf'),new File(['unsupported'],'不支持.txt')]}});await settleUploads(h.root)
    find(h.root,'case-type').props.onChange({target:{value:'civil'}});await settleUploads(h.root)
    click(find(h.root,'start-archive'));await settleUploads(h.root)
    assert.ok(find(h.root,'dashboard-dismiss-upload'))
    assert.equal(h.calls.filter(call=>call.path.endsWith('/generate')).length,0)
    click(find(h.root,'dashboard-dismiss-upload'));await settleUploads(h.root)
    assert.equal(find(h.root,'dashboard-dismiss-upload'),undefined)
    assert.equal(h.calls.filter(call=>call.path.endsWith('/generate')).length,0)
    click(find(h.root,'start-archive'));await settleUploads(h.root)
    assert.equal(h.calls.filter(call=>call.path.endsWith('/files')).length,1)
    assert.equal(h.calls.filter(call=>call.path.endsWith('/generate')).length,1)
  }finally{h.app.unmount()}
})
test('production home cancellation keeps no phantom case or generated task',async()=>{
  const h=await dashboardHarness()
  try{const file=new File(['synthetic'], '虚构卷.pdf');find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file]}});await settle()
    const findCancel=n=>n.type==='button'&&content(n)==='取消选择'?n:n.children.map(findCancel).find(Boolean)
    click(findCancel(h.root));await settle();assert.equal(find(h.root,'archive-import-dialog'),undefined);assert.deepEqual(h.calls,[]);assert.deepEqual(h.routes,[])
  }finally{h.app.unmount()}
})

test('production home disables unavailable original-template types and refuses synthetic selection without making a case',async()=>{
  const h=await dashboardHarness()
  try{
    const file=new File(['synthetic'], '虚构卷.pdf');find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file]}});await settle()
    const options=n=>[...(n.props.value==='arbitration'||n.props.value==='consultation'?[n]:[]),...n.children.flatMap(options)]
    for(const option of options(find(h.root,'case-type'))){assert.equal(option.props.disabled,true);assert.match(option.props.label,/暂未接入原目录/)}
    find(h.root,'case-type').props.onChange({target:{value:'arbitration'}});await settle()
    assert.equal(find(h.root,'start-archive').props.disabled,true);click(find(h.root,'start-archive'));await settle()
    assert.deepEqual(h.calls,[]);assert.deepEqual(h.routes,[])
  }finally{h.app.unmount()}
})
test('production optional decision navigation retains unsaved text without acknowledging or saving it',async()=>{
  const h=await taskHarness({...baseline,issues:[...baseline.issues,{id:'b',kind:'ocr',message:'扫描待核对',blocking:true,detail:{filename:'虚构.pdf',page:3}}]})
  try{const findButton=(n,label)=>n.type==='button'&&content(n).includes(label)?n:n.children.map(child=>findButton(child,label)).find(Boolean)
    click(findButton(h.root,'识别疑问'));await settle();click(findButton(h.root,'填写说明或修改'));await settle()
    input(find(h.root,'issue-review-reason'),'正在对照，尚未确认');await settle();click(findButton(h.root,'下一项'));await settle();click(findButton(h.root,'上一项'));await settle()
    assert.equal(find(h.root,'issue-review-reason').props.value,'正在对照，尚未确认');assert.match(content(find(h.root,'decision-focus')),/2 项尚未处理/);assert.equal(h.calls.filter(([method])=>method==='patch'||method==='post').length,0)
  }finally{h.dispose()}
})

test('production artifact list displays relative names from the actual manifest and never leaks artifact absolute paths',async()=>{
  const h=await taskHarness({...baseline,artifacts:[{key:'archive',relative_path:'完整卷宗.pdf',path:'C:/synthetic-private-root/archive.pdf'},{key:'quality_check',path:'C:/synthetic-private-root/quality.txt'}]})
  try{click(find(h.root,'archive-tools'));await settle();assert.match(content(h.root),/完整卷宗.pdf/);assert.match(content(h.root),/quality_check/);assert.doesNotMatch(content(h.root),/synthetic-private-root/)}finally{h.dispose()}
})

test('production assistant restores a persisted applied proposal without a token or another model request',async()=>{
  let posts=0
  const {proposal_token,...stored}=proposal
  const Component=await assistantComponent({get:async()=>({data:{messages:[{id:100,role:'user',content:'此前明确修改',status:'completed',revision:7},{id:101,role:'assistant',content:'已保存的建议',status:'completed',tool:'propose_field_change',proposal:stored,proposal_state:'applied',revision:7}]}}),post:async()=>{posts++;throw new Error('unexpected')}})
  const h=mount(Component,{taskId:'3',revision:8,sourceVersion:'synthetic-v1'})
  try{await settle();assert.match(content(h.root),/此前明确修改/);assert.match(content(find(h.root,'assistant-proposal')),/已采用/);assert.equal(find(h.root,'apply-assistant-proposal'),undefined);assert.match(content(h.root),/较早草稿的记录/);assert.equal(posts,0)}finally{h.app.unmount()}
})

test('production assistant preserves typed input through history failure/retry and suppresses a recovered pending request',async()=>{
  let fails=true,posts=0
  const Component=await assistantComponent({get:async()=>{if(fails)throw new Error('offline');return {data:{messages:[{id:100,role:'user',content:'之前的问题',status:'pending'}]}}},post:async()=>{posts++;return {data:{message:'不应请求'}}}})
  const h=mount(Component,{taskId:'3',revision:7,sourceVersion:'synthetic-v1'})
  try{await settle();input(find(h.root,'assistant-question'),'输入仍保留');await settle();assert.ok(find(h.root,'assistant-history-error'));assert.equal(find(h.root,'assistant-send').props.disabled,true)
    fails=false;click(find(h.root,'assistant-reload-history'));await settle();assert.equal(find(h.root,'assistant-question').props.value,'输入仍保留');assert.ok(find(h.root,'assistant-restored-pending'));assert.equal(find(h.root,'assistant-send').props.disabled,true);assert.equal(posts,0)
  }finally{h.app.unmount()}
})

test('production assistant exposes an interrupted adoption only as explicit recovery and reloads history without applying',async()=>{
  const calls=[];let reads=0,refreshes=0
  const {proposal_token,...stored}=proposal
  const Component=await assistantComponent({get:async()=>{reads++;return {data:{messages:[{id:101,role:'assistant',content:'此前建议',status:'completed',tool:'propose_field_change',proposal:stored,proposal_state:reads>1?'pending':'applying',proposal_notice:'备份已保留'}]}}},post:async(path,body)=>{calls.push(body);throw {response:{status:409,data:{detail:'已恢复，请核对后再采用'}}}}})
  const h=mount(Component,{taskId:'3',revision:7,sourceVersion:'synthetic-v1',beforeApply:async()=>'',beforeRecover:async()=>'',onRefresh:()=>refreshes++})
  try{await settle();assert.match(content(find(h.root,'assistant-proposal')),/采用待恢复/);assert.equal(find(h.root,'apply-assistant-proposal'),undefined);click(find(h.root,'recover-assistant-proposal'));await settle();assert.deepEqual(calls,[{proposal_id:proposal.id,expected_revision:7,recover_only:true}]);assert.equal(refreshes,1);assert.ok(find(h.root,'apply-assistant-proposal'));assert.doesNotMatch(content(find(h.root,'assistant-proposal')),/修改建议 · 已采用/)}finally{h.app.unmount()}
})

test('production historical or supplemented task permits recovery while keeping ordinary proposal adoption disabled',async()=>{
  for(const changedSource of [false,true]){
    const requests=[];let historyReads=0
    const {proposal_token,...stored}=proposal
    const Assistant=await assistantComponent({get:async()=>({data:{messages:[{id:101,role:'assistant',content:'此前建议',status:'completed',tool:'propose_field_change',proposal:stored,proposal_state:++historyReads===1?'applying':'pending'}]}}),post:async(path,body)=>{requests.push(body);throw {response:{status:409,data:{detail:'恢复完成，请重新核对'}}}}})
    const h=await taskHarness({...baseline,source_changed:changedSource},{get:async path=>path==='/cases/c'?{id:'c',title:'虚构卷',last_task_id:changedSource?'3':'4',files:[]}:undefined,components:{'../components/ArchiveAssistant.vue':esm(Assistant)}})
    try{await settle();assert.equal(find(h.root,'recover-assistant-proposal').props.disabled,false);click(find(h.root,'recover-assistant-proposal'));await settle();assert.deepEqual(requests,[{proposal_id:proposal.id,expected_revision:7,recover_only:true}]);assert.equal(find(h.root,'apply-assistant-proposal').props.disabled,true);assert.doesNotMatch(content(find(h.root,'assistant-proposal')),/修改建议 · 已采用/)}finally{h.dispose()}
  }
})

test('recovery retains its independent local-operation lock even when ordinary writes are disabled for history',async()=>{
  let requests=0
  const {proposal_token,...stored}=proposal
  const Assistant=await assistantComponent({get:async()=>({data:{messages:[{id:101,role:'assistant',content:'待恢复',status:'completed',tool:'propose_field_change',proposal:stored,proposal_state:'applying'}]}}),post:async()=>{requests++;return {data:{}}}})
  const h=mount(Assistant,{taskId:'3',revision:7,sourceVersion:'synthetic-v1',writeDisabled:true,recoverDisabled:true,beforeRecover:async()=>''})
  try{await settle();assert.equal(find(h.root,'recover-assistant-proposal').props.disabled,true);assert.equal(requests,0)}finally{h.app.unmount()}
})

test('production grouped conflict preserves all reasons and saving an explanation never resolves the factual conflict',async()=>{
  const second={id:'b',kind:'fact_review',message:'案号的来源仍有疑问',blocking:true,detail:{field:'案号'}}
  const h=await taskHarness({...baseline,catalog_status:[],issues:[...baseline.issues,second],review_queue:[{key:'field-case',kind:'issue',title:'案号核对',field:'案号',issue_ids:['a','b'],sources:[],field_targets:[]}]})
  const button=(n,label)=>n.type==='button'&&content(n).includes(label)?n:n.children.map(c=>button(c,label)).find(Boolean)
  try{click(button(h.root,'识别疑问'));await settle();assert.match(content(find(h.root,'decision-related-reasons')),/案号需核对/);assert.match(content(find(h.root,'decision-related-reasons')),/来源仍有疑问/);assert.equal(find(h.root,'acknowledge-decision'),undefined);assert.equal(h.calls.filter(([m])=>m==='patch').length,0)
    click(button(h.root,'填写说明或修改'));await settle();input(find(h.root,'issue-review-reason'),'已看来源，仍需确定案号');await settle();click(button(h.root,'保存说明（不解决字段冲突）'));await settle();const saved=h.calls.find(([m])=>m==='patch')[2].fields._issue_decisions;assert.equal(saved.a.action,'acknowledged');assert.equal(saved.b.action,'acknowledged');assert.match(content(find(h.root,'decision-focus')),/案号核对/);assert.match(content(find(h.root,'decision-focus')),/1 项尚未处理/)
  }finally{h.dispose()}
})

test('production grouped field action opens the server mapped original field and returns to the same undecided group after saving',async()=>{
  const Editor={props:['active','focusField','templateName'],emits:['saved'],setup:(props,{emit})=>()=>props.active?Vue.h('div',{'data-testid':'focused-editor'},[Vue.h('p',null,props.templateName+' / '+props.focusField),Vue.h('button',{'data-testid':'synthetic-field-save',onClick:()=>emit('saved',{...baseline,catalog_status:[],revision:8,has_archive:false,review_queue:queue})},'保存')]):null}
  const queue=[{key:'field-case',kind:'issue',title:'案号核对',field:'案号',issue_ids:['a'],field_targets:[{template_name:'送达材料清单',field:'法院收案号'}]}]
  const h=await taskHarness({...baseline,catalog_status:[],review_queue:queue},{get:async path=>path.endsWith('/templates')?{templates:['立案审批表','送达材料清单']}:undefined,components:{'../components/PreviewFieldEditor.vue':esm(Editor)}})
  const button=(n,label)=>n.type==='button'&&content(n).includes(label)?n:n.children.map(c=>button(c,label)).find(Boolean)
  try{click(button(h.root,'识别疑问'));await settle();click(find(h.root,'decision-edit-field'));await settle();assert.match(content(find(h.root,'focused-editor')),/送达材料清单 \/ 法院收案号/);click(find(h.root,'synthetic-field-save'));await settle();assert.equal(find(h.root,'focused-editor'),undefined);assert.match(content(find(h.root,'decision-focus')),/案号核对/);assert.match(content(find(h.root,'decision-focus')),/1 项尚未处理/);assert.equal(h.calls.filter(([m])=>m==='patch').length,0)}finally{h.dispose()}
})

test('production successful cloud supplement is an authorization status, not an error; retries send only failed files',async()=>{
  const cloudTask={...baseline,can_resume:true,execution_profile:{processing_mode:'deepseek_cloud',cloud_consent:true,authorized_source_version:'synthetic-v1'}}
  const uploads=[];let fail=true,h
  h=await taskHarness(cloudTask,{post:async(path,body)=>{if(path.endsWith('/files')){const file=body.get('file');uploads.push(file.name);if(file.name==='失败.pdf'&&fail)throw {response:{status:503,data:{detail:'临时不可用'}}};h.setTask({...cloudTask,source_changed:true});return {id:'uploaded'}}}})
  try{
    find(h.root,'task-supplement-files').props.onChange({target:{files:[new File(['a'],'成功.pdf'),new File(['b'],'失败.pdf')],value:''}});await settleUploads(h.root);assert.ok(find(h.root,'upload-recovery'));assert.match(content(find(h.root,'archive-primary-action')),/重试未导入材料/)
    fail=false;click(find(h.root,'archive-primary-action'));await settleUploads(h.root);assert.deepEqual(uploads,['成功.pdf','失败.pdf','失败.pdf']);assert.equal(find(h.root,'archive-operation-error'),undefined);assert.ok(find(h.root,'supplement-consent'));assert.match(content(find(h.root,'supplement-consent')),/补件已保存在工作站/);assert.equal(h.calls.filter(([m,path])=>m==='post'&&path.endsWith('/resume')).length,0)
  }finally{h.dispose()}
})

test('production supplement retains failures across new batches and resumes only after the remaining files succeed',async()=>{
  const uploads=[],keys=[];let fail=true,h
  const localTask={...baseline,can_resume:true,execution_profile:{processing_mode:'local'}}
  h=await taskHarness(localTask,{post:async(path,body,_task,config)=>{
    if(path.endsWith('/files')){
      const file=body.get('file');uploads.push(file.name);keys.push(config.headers['Idempotency-Key'])
      if(file.name==='早先失败.pdf'&&fail)throw {response:{status:503,data:{detail:'全虚构临时故障'}}}
      h.setTask({...localTask,source_changed:true});return {id:'uploaded'}
    }
    if(path.endsWith('/resume'))return {...localTask,status:'running',phase:'queued',source_changed:false}
  }})
  try{
    find(h.root,'task-supplement-files').props.onChange({target:{files:[new File(['a'],'早先失败.pdf')],value:''}});await settleUploads(h.root)
    find(h.root,'task-supplement-files').props.onChange({target:{files:[new File(['b'],'第二批成功.pdf')],value:''}});await settleUploads(h.root)
    assert.match(content(find(h.root,'upload-recovery')),/早先失败.pdf/)
    assert.match(content(find(h.root,'archive-primary-action')),/重试未导入材料/)
    assert.equal(h.calls.filter(([m,path])=>m==='post'&&path.endsWith('/resume')).length,0)
    fail=false;click(find(h.root,'archive-primary-action'));await settleUploads(h.root)
    assert.deepEqual(uploads,['早先失败.pdf','第二批成功.pdf','早先失败.pdf']);assert.ok(keys[0]);assert.equal(keys[0],keys[2]);assert.notEqual(keys[0],keys[1])
    assert.equal(h.calls.filter(([m,path])=>m==='post'&&path.endsWith('/resume')).length,1)
    assert.equal(find(h.root,'archive-operation-error'),undefined)
  }finally{h.dispose()}
})

test('removing the last unsupported supplement waits for an explicit resume and never deletes imported material',async()=>{
  let h
  const localTask={...baseline,can_resume:true,execution_profile:{processing_mode:'local'}}
  h=await taskHarness(localTask,{post:async(path)=>{
    if(path.endsWith('/files')){h.setTask({...localTask,source_changed:true});return {id:'uploaded'}}
    if(path.endsWith('/resume'))return {...localTask,status:'running',phase:'queued',source_changed:false}
  }})
  try{
    find(h.root,'task-supplement-files').props.onChange({target:{files:[new File(['bad'],'不支持.txt'),new File(['pdf'],'保留.pdf')],value:''}});await settleUploads(h.root)
    assert.ok(find(h.root,'task-dismiss-upload'))
    click(find(h.root,'task-dismiss-upload'));await settleUploads(h.root)
    assert.equal(find(h.root,'task-dismiss-upload'),undefined)
    assert.equal(h.calls.filter(([m,path])=>m==='post'&&path.endsWith('/resume')).length,0)
    assert.match(content(find(h.root,'archive-primary-action')),/继续整理/)
    click(find(h.root,'archive-primary-action'));await settleUploads(h.root)
    assert.equal(h.calls.filter(([m,path])=>m==='post'&&path.endsWith('/resume')).length,1)
    assert.equal(h.calls.filter(([m,path])=>m==='post'&&path.endsWith('/files')).length,1)
    assert.equal(h.calls.filter(([m])=>m==='delete').length,0)
  }finally{h.dispose()}
})

test('grouping OCR and classification at one span preserves the classification action even when OCR is the first reason',async()=>{
  const seen=[]
  const Classification={setup:(_,{expose})=>{expose({reveal:async source=>seen.push(source)});return ()=>Vue.h('p',null,'完整文书核对')}}
  const detail={file_id:'source',filename:'虚构扫描.pdf',page:2,page_start:2,page_end:3}
  const issues=[{id:'ocr',kind:'ocr',blocking:true,message:'字迹待核对',detail},{id:'class',kind:'classification',blocking:true,message:'文书归属待核对',detail}]
  const h=await taskHarness({...baseline,catalog_status:[],issues,review_queue:[{key:'span',kind:'issue',title:'同段材料',issue_ids:['ocr','class'],sources:[{...detail}]}]},{components:{'../components/DocumentClassificationReview.vue':esm(Classification)},globalComponents:{'el-table-column':{setup:()=>()=>Vue.h('span')}}})
  const button=(n,label)=>n.type==='button'&&content(n).includes(label)?n:n.children.map(c=>button(c,label)).find(Boolean)
  try{click(button(h.root,'识别疑问'));await settle();assert.ok(find(h.root,'decision-classification'));click(find(h.root,'decision-classification'));await settle();assert.deepEqual(seen,[detail]);assert.equal(h.calls.filter(([m])=>m==='patch'||m==='post').length,0)}finally{h.dispose()}
})

test('task navigation protects unsynced assistant input without making it a field edit or blocking draft generation',async()=>{
  let emitDraft,assistantProps,confirmed=false;const confirmations=[]
  const DraftEmitter={props:['accountScope','draftReadOnly'],emits:['draftDirty'],setup:(props,{emit})=>{assistantProps=props;emitDraft=value=>emit('draftDirty',value);return ()=>Vue.h('p',null,'全虚构草稿状态入口')}}
  const h=await taskHarness({...baseline,has_archive:false,delivery_kind:null,phase:'needs_input'},{components:{'../components/ArchiveAssistant.vue':esm(DraftEmitter)},elementPlus:{ElMessage:{success(){},warning(){},error(){},info(){}},ElMessageBox:{confirm:async message=>{confirmations.push(message);if(!confirmed)throw Error('synthetic cancel')}}}})
  try{
    assert.equal(assistantProps.accountScope,'synthetic-org:synthetic-user');assert.equal(assistantProps.draftReadOnly,false)
    emitDraft(true);await settle()
    let prevented=false;const event={preventDefault(){prevented=true}}
    h.listeners.get('beforeunload')(event);assert.equal(prevented,true);assert.equal(event.returnValue,'')
    assert.equal(await h.leave(),false);assert.match(confirmations[0],/未同步的对话文字/)
    assert.equal(find(h.root,'archive-primary-action').props.disabled,false)
    click(find(h.root,'archive-primary-action'));await settle()
    assert.deepEqual(h.calls.filter(([method])=>method==='post'),[['post','/tasks/3/draft',{expected_revision:7}]],'a conversation draft must not become an archive field-save prerequisite')
    confirmed=true;assert.equal(await h.leave(),true,'explicit abandonment is the only allowed unsynced exit')
    emitDraft(false);await settle();prevented=false
    h.listeners.get('beforeunload')({preventDefault(){prevented=true}});assert.equal(prevented,false)
    const before=confirmations.length;assert.equal(await h.leave(),true);assert.equal(confirmations.length,before)
  }finally{h.dispose()}
})

const reviewButton=(n,label)=>n.type==='button'&&content(n).includes(label)?n:n.children.map(c=>reviewButton(c,label)).find(Boolean)

test('supplied source forms show original-page entry and never mount the replacement editor',async()=>{
  for(const name of ['立案审批表','结案报告表','送达材料清单']){
    let editors=0
    const Editor={setup:()=>{editors++;return ()=>Vue.h('p','unexpected replacement')}}
    const value={...baseline,fields:{_original_forms:{[name]:[{file_id:'synthetic-file',filename:'虚构原表.pdf',page:2,page_end:3}]}},issues:[],catalog_status:[]}
    const h=await taskHarness(value,{get:async path=>path.endsWith('/templates')?{templates:[name]}:undefined,components:{'../components/PreviewFieldEditor.vue':esm(Editor)}})
    try{
      click(reviewButton(h.root,'管理档案'));await settle()
      click(reviewButton(h.root,'表格'));await settle()
      const view=find(h.root,'original-source-form')
      assert.ok(view);assert.match(content(view),/已保留原始/);assert.ok(content(view).includes(name))
      assert.match(content(view),/第 2—3 页/);assert.equal(editors,0)
      assert.equal(h.calls.filter(([method,path])=>path.includes('/preview-fields/')).length,0)
    }finally{h.dispose()}
  }
})

test('field correction selects an editable generated form instead of altering a supplied original',async()=>{
  const value={...baseline,fields:{_original_forms:{'立案审批表':[{file_id:'synthetic-file',page:1,page_end:1}]}},catalog_status:[],
    issues:[{...baseline.issues[0],detail:{field:'委托人'}}],review_queue:[{key:'client',kind:'issue',title:'委托人核对',field:'委托人',issue_ids:['a'],field_targets:[{template_name:'立案审批表',field:'委托人'},{template_name:'档案卷宗',field:'委托人'}]}]}
  const Editor={props:['active','templateName'],setup:props=>()=>props.active?Vue.h('p',{'data-testid':'active-form'},props.templateName):null}
  const h=await taskHarness(value,{get:async path=>path.endsWith('/templates')?{templates:['立案审批表','档案卷宗']}:undefined,components:{'../components/PreviewFieldEditor.vue':esm(Editor)}})
  try{
    click(reviewButton(h.root,'识别疑问'));await settle();click(find(h.root,'decision-edit-field'));await settle()
    assert.equal(content(find(h.root,'active-form')),'档案卷宗')
    assert.equal(h.calls.filter(([method,path])=>path.includes('/preview-fields/')).length,0)
  }finally{h.dispose()}
})

test('quality components show retained sources and mount only the missing card editor',async()=>{
  for(const kinds of [[],['quality_card'],['client_notice'],['quality_card','client_notice']]){
    let editors=0
    const refs=kinds.map((component,index)=>({component,file_id:'synthetic-file',page:index+1,page_end:index+1}))
    const fields={_original_form_components:{'质量监督卡':refs},_original_forms:kinds.length===2?{'质量监督卡':refs}:{},
      _form_drafts:{fields:{'委托人联系地址及电话':{status:'insufficient'}}}}
    const Editor={setup:()=>{editors++;return ()=>Vue.h('p','missing card editor')}}
    const h=await taskHarness({...baseline,fields,issues:[],catalog_status:[]},{
      get:async path=>path.endsWith('/templates')?{templates:['质量监督卡']}:undefined,
      components:{'../components/PreviewFieldEditor.vue':esm(Editor)}})
    try{
      click(reviewButton(h.root,'管理档案'));await settle()
      assert.equal(content(h.root).includes('委托人联系地址及电话 · 待补全依据'),!kinds.includes('quality_card'))
      click(reviewButton(h.root,'表格'));await settle()
      assert.equal(editors,kinds.includes('quality_card')?0:1)
      if(kinds.length===2)assert.match(content(h.root),/已保留质量监督卡和委托人须知原件/)
      else if(kinds[0]==='quality_card')assert.match(content(h.root),/委托人须知随成果补齐/)
      else if(kinds[0]==='client_notice')assert.match(content(find(h.root,'original-quality-part')),/仅补填质量监督卡/)
    }finally{h.dispose()}
  }
})
const navigationTask={...baseline,catalog_status:[],issues:[
  {id:'first',kind:'ocr',message:'第一处原页',blocking:true},
  {id:'done',kind:'ocr',message:'此前已核对',blocking:true},
  {id:'last',kind:'ocr',message:'最后一处原页',blocking:true},
],fields:{_issue_decisions:{done:{action:'acknowledged',reason:'已有人工核对'}}}}

test('saved acknowledgement advances past completed items and last save shows completion',async()=>{
  const h=await taskHarness(navigationTask)
  try{
    click(reviewButton(h.root,'识别疑问'));await settle()
    assert.match(content(find(h.root,'decision-focus')),/第一处原页/)
    click(find(h.root,'acknowledge-decision'));await settle();await settle();await settle()
    assert.match(content(find(h.root,'decision-focus')),/最后一处原页/)
    assert.doesNotMatch(content(find(h.root,'decision-focus')),/此前已核对/)
    click(find(h.root,'acknowledge-decision'));await settle();await settle();await settle()
    assert.equal(find(h.root,'decision-focus'),undefined)
    assert.match(content(h.root),/当前没有待处理的识别疑问或必要补件/)
    assert.equal(h.calls.filter(([method])=>method==='patch').length,2)
  }finally{h.dispose()}
})

test('failed save leaves the selected item and typed explanation in place',async()=>{
  const h=await taskHarness(navigationTask,{failPatch:true})
  try{
    click(reviewButton(h.root,'识别疑问'));await settle()
    input(find(h.root,'issue-review-reason'),'原页内容已检查');await settle()
    click(find(h.root,'acknowledge-decision'));await settle();await settle();await settle()
    assert.match(content(find(h.root,'decision-focus')),/第一处原页/)
    assert.equal(find(h.root,'issue-review-reason').props.value,'原页内容已检查')
    assert.match(content(h.root),/测试保存失败/)
  }finally{h.dispose()}
})

test('confirmed field value advances only when the server resolves the conflict',async()=>{
  for(const resolved of [true,false]){
    const value={...navigationTask,source_version:'a'.repeat(64),fields:{案号:'虚构案号'},issues:[...baseline.issues,navigationTask.issues[2]]}
    const h=await taskHarness(value,{post:async(path,body,current)=>{
      assert.ok(path.endsWith('/field-decisions'))
      return {...current,revision:8,issues:current.issues.map(i=>i.id==='a'?{...i,detail:{...i.detail,fact_resolved:resolved}}:i)}
    }})
    try{
      click(reviewButton(h.root,'识别疑问'));await settle()
      click(find(h.root,'accept-current-field'));await settle();await settle()
      assert.match(content(find(h.root,'decision-focus')),resolved?/最后一处原页/:/案号需核对/)
      assert.equal(h.calls.filter(([m])=>m==='post').length,1)
    }finally{h.dispose()}
  }
})

test('saving a resolved original-form field returns directly to the next pending decision',async()=>{
  const value={...navigationTask,issues:[{...baseline.issues[0],detail:{field:'案号'}},navigationTask.issues[2]],review_queue:[{key:'field-case',kind:'issue',title:'案号核对',field:'案号',issue_ids:['a'],field_targets:[{template_name:'立案审批表',field:'案号'}]}]}
  const Editor={props:['active'],emits:['saved'],setup:(props,{emit})=>()=>props.active?Vue.h('button',{'data-testid':'synthetic-field-save',onClick:()=>emit('saved',{...value,revision:8,issues:[{...value.issues[0],detail:{field:'案号',fact_resolved:true}},value.issues[1]]})},'保存'):null}
  const h=await taskHarness(value,{components:{'../components/PreviewFieldEditor.vue':esm(Editor)}})
  try{
    click(reviewButton(h.root,'识别疑问'));await settle();click(find(h.root,'decision-edit-field'));await settle()
    click(find(h.root,'synthetic-field-save'));await settle()
    assert.equal(find(h.root,'synthetic-field-save'),undefined)
    assert.match(content(find(h.root,'decision-focus')),/最后一处原页/)
  }finally{h.dispose()}
})

test('classification save returns to the next item when the old issue disappears',async()=>{
  const value={...navigationTask,issues:[{id:'classify',kind:'classification',message:'文书待定',blocking:true,detail:{page:3,file_id:'synthetic-file'}},navigationTask.issues[2]]}
  const Classification={emits:['saved'],setup:(_,{emit,expose})=>{expose({reveal(){}});return ()=>Vue.h('button',{'data-testid':'synthetic-classification-save',onClick:()=>emit('saved',{...value,revision:8,issues:[value.issues[1]]})},'保存分类')}}
  const h=await taskHarness(value,{components:{'../components/DocumentClassificationReview.vue':esm(Classification)},globalComponents:{'el-table-column':{render:()=>null}}})
  try{
    click(reviewButton(h.root,'识别疑问'));await settle();click(find(h.root,'decision-classification'));await settle()
    click(find(h.root,'synthetic-classification-save'));await settle()
    assert.equal(find(h.root,'synthetic-classification-save'),undefined)
    assert.match(content(find(h.root,'decision-focus')),/最后一处原页/)
  }finally{h.dispose()}
})


test('whole-form save waits for all editor saves before advancing; failure keeps the editor open',async()=>{
  for(const success of [false,true]){
    const value={...navigationTask,issues:[baseline.issues[0],navigationTask.issues[2]],review_queue:[{key:'field-case',kind:'issue',title:'案号核对',field:'案号',issue_ids:['a'],field_targets:[{template_name:'立案审批表',field:'案号'}]}]}
    let h
    const Editor={props:['active'],emits:['saved'],setup:(props,{emit,expose})=>{
      let dirty=true
      expose({isLoaded:()=>true,hasUnsavedChanges:()=>dirty,saveChanges:async()=>{
        const updated={...value,revision:8,issues:[{...value.issues[0],detail:{field:'案号',fact_resolved:true}},value.issues[1]]}
        h.setTask(updated);emit('saved',updated);if(success)dirty=false;return success
      }})
      return ()=>props.active?Vue.h('p',{'data-testid':'batch-editor'},'虚构编辑内容'):null
    }}
    h=await taskHarness(value,{components:{'../components/PreviewFieldEditor.vue':esm(Editor)}})
    try{
      click(reviewButton(h.root,'识别疑问'));await settle();click(find(h.root,'decision-edit-field'));await settle()
      click(find(h.root,'save-template-fields'));await settle();await settle()
      if(success){assert.equal(find(h.root,'batch-editor'),undefined);assert.match(content(find(h.root,'decision-focus')),/最后一处原页/)}
      else{assert.ok(find(h.root,'batch-editor'));assert.match(content(find(h.root,'decision-focus')),/案号核对/)}
    }finally{h.dispose()}
  }
})


test('priority review groups genuine doubts while catalog gaps remain accessible and final confirmation stays guarded',async()=>{
  const h=await taskHarness({...baseline,catalog_status:[{seq:2,name:'未知适用材料',found:false,requirement:'unknown'},{seq:3,name:'可选材料',found:false,requirement:'optional',legal_requirement_verified:true}],issues:[{id:'one',kind:'ocr',blocking:true,message:'同文书清晰度',detail:{}},{id:'two',kind:'classification',blocking:true,message:'同文书位置',detail:{}}],review_queue:[{key:'same-document',kind:'issue',issue_ids:['one','two'],title:'同文书疑点'}]})
  try{
    click(find(h.root,'archive-tools'));await settle()
    assert.match(content(find(h.root,'attention-review-entry')),/1 项/)
    assert.match(content(find(h.root,'material-review-entry')),/2 项待记录/)
    assert.equal(reviewButton(h.root,'最终确认并生成').props.disabled,true)
    click(find(h.root,'attention-review-entry'));await settle()
    assert.match(content(find(h.root,'decision-focus')),/1 项尚未处理/)
    assert.match(content(find(h.root,'decision-related-reasons')),/2 项关联依据/)
    click(reviewButton(h.root,'填写说明或修改'));await settle()
    input(find(h.root,'issue-review-reason'),'本组未保存说明');await settle()
    click(find(h.root,'toggle-review-section'));await settle()
    assert.match(content(find(h.root,'decision-focus')),/未知适用材料/)
    assert.match(content(find(h.root,'decision-focus')),/2 项材料待核/)
    click(find(h.root,'toggle-review-section'));await settle()
    assert.match(content(find(h.root,'decision-related-reasons')),/同文书清晰度/)
    assert.equal(find(h.root,'issue-review-reason').props.value,'本组未保存说明')
    assert.equal(h.calls.filter(([method])=>['patch','post'].includes(method)).length,0)
  }finally{h.dispose()}
})

test('absence of recognition doubts is not a claim that missing catalog material is verified',async()=>{
  const h=await taskHarness({...baseline,issues:[]})
  try{
    click(find(h.root,'archive-tools'));await settle()
    assert.match(content(find(h.root,'attention-review-entry')),/0 项/)
    assert.match(content(find(h.root,'material-review-entry')),/1 项待记录/)
    click(find(h.root,'attention-review-entry'));await settle()
    assert.match(content(h.root),/当前没有待处理的识别疑问或必要补件/)
    click(find(h.root,'toggle-review-section'));await settle()
    assert.ok(find(h.root,'decision-focus'))
    assert.equal(reviewButton(h.root,'最终确认并生成').props.disabled,true)
  }finally{h.dispose()}
})


test('management material count opens the same checklist, including checks outside empty catalog slots',async()=>{
  const check=(id,seq)=>({id,seq,name:id,check_kind:'source_material',status:'missing',requirement:'unknown',legal_requirement_verified:false,message:'虚构待核材料'})
  const value={...baseline,issues:[],catalog_status:[{seq:4,name:'授权委托书',found:false,material_status_version:'v1',material_checks:[check('material:poa',4)],additional_material_checks:[check('material:execution',15)]}]}
  const h=await taskHarness(value)
  try{
    assert.match(content(find(h.root,'applicability-materials')),/2 项适用性待核验/)
    click(find(h.root,'archive-tools'));await settle()
    assert.match(content(find(h.root,'material-checklist-entry')),/材料清单2 项待核验/)
    assert.match(content(find(h.root,'material-review-entry')),/目录空位说明 · 1 项待记录/)
    click(find(h.root,'material-checklist-entry'));await settle()
    assert.equal(find(h.root,'material-checklist-disclosure').open,true)
    assert.equal(find(h.root,'decision-focus'),undefined)
    assert.equal(h.calls.filter(([m])=>m==='post'||m==='patch').length,0)
  }finally{h.dispose()}
})

test('production field-source drawer groups one page navigation without losing current, historical or distinct quotes',async()=>{
  const page={file_id:'synthetic-file',filename:'虚构.pdf',page:8,method:'local_agent'}
  const Drawer={props:['modelValue'],emits:['open'],setup:(props,{emit,slots})=>{Vue.watch(()=>props.modelValue,value=>{if(value)emit('open')});return ()=>props.modelValue?Vue.h('aside',null,slots.default?.()):null}}
  const h=await taskHarness(baseline,{globalComponents:{'el-drawer':Drawer},get:async path=>path.includes('/page/')?new Blob(['fictional page']):path.endsWith('/evidence')?{fields:{'案号':[
    {...page,quote:'本金1000元。'},{...page,quote:'判决：本金1000元。'},
    {...page,quote:'驳回其余请求。'},{...page,historical:true,quote:'历史错误摘录'},
    {...page,file_id:'different-file',quote:'另一文件同页'}]}}:undefined})
  const nodes=(n,id)=>[...(n.props?.['data-testid']===id?[n]:[]),...n.children.flatMap(child=>nodes(child,id))]
  try{
    click(reviewButton(h.root,'识别疑问'));await settle()
    click(reviewButton(h.root,'查看字段依据'));await settle()
    const cards=nodes(h.root,'evidence-page-card');assert.equal(cards.length,3)
    assert.match(content(cards[0]),/判决：本金1000元/);assert.match(content(cards[0]),/驳回其余请求/)
    assert.equal(cards[0].children.filter(n=>n.type==='button').length,1)
    assert.match(content(cards[1]),/历史识别依据/);assert.match(content(cards[2]),/另一文件同页/)
    let scrolled=0;find(h.root,'source-preview').scrollIntoView=()=>scrolled++
    click(reviewButton(cards[0],'打开原文页'));await settle()
    assert.ok(h.calls.some(([method,path])=>method==='get'&&path==='/cases/c/files/synthetic-file/page/8'))
    const images=n=>[...(n.type==='img'&&n.props.alt==='案件原文'?[n]:[]),...n.children.flatMap(images)]
    images(h.root)[0].props.onLoad();assert.equal(scrolled,1)
    assert.equal(h.calls.filter(([m])=>m==='post'||m==='patch').length,0)
  }finally{h.dispose()}
})


test('source-backed candidate is one explicit decision, advances and is never sent on render',async()=>{
  const value={...navigationTask,source_version:'a'.repeat(64),fields:{立案审批日期:''},issues:[{id:'date',kind:'field_conflict',message:'核对日期',blocking:true,detail:{field:'立案审批日期'}},navigationTask.issues[2]],review_queue:[{key:'date',kind:'issue',field:'立案审批日期',issue_ids:['date'],field_candidates:[{value:'2026年1月5日',sources:[{file_id:'synthetic-file',filename:'旧合同.pdf',page:2}]},{value:'2026年2月5日',sources:[{file_id:'new-file',filename:'新合同.pdf',page:1}]}]}]}
  const h=await taskHarness(value,{post:async(path,body,current)=>{
    assert.equal(body.action,'accept_candidate');assert.equal(body.current_value,'');assert.equal(body.selected_value,'2026年2月5日');assert.equal(body.expected_revision,7)
    assert.equal(body.sources,undefined)
    return {...current,revision:8,fields:{立案审批日期:body.selected_value},issues:current.issues.map(i=>i.id==='date'?{...i,detail:{...i.detail,fact_resolved:true}}:i)}
  }})
  try{
    click(reviewButton(h.root,'识别疑问'));await settle()
    assert.match(content(find(h.root,'field-candidates')),/2026年1月5日/)
    assert.match(content(find(h.root,'field-candidates')),/新合同.pdf/)
    assert.equal(h.calls.filter(([m])=>m==='post').length,0)
    click(find(h.root,'choose-field-2026年2月5日'));await settle();await settle()
    assert.equal(h.calls.filter(([m])=>m==='post').length,1)
    assert.match(content(find(h.root,'decision-focus')),/最后一处原页/)
  }finally{h.dispose()}
})
