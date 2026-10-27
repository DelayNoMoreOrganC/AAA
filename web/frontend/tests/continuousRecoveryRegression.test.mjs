import {withUploadIntentsApi,uploadImports,settleUploads} from './uploadRecoveryApi.mjs'
// Audit regressions: actual SFCs mounted in the in-memory Vue renderer.
// Every transport is a synthetic stub; no browser, backend or model is used.
import test from 'node:test'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,content,click,input,settle,esm} from './vueHarness.mjs'
import * as workflow from '../src/domain/workflow.js'
import * as experience from '../src/domain/taskExperience.js'
import * as privacy from '../src/domain/processingPrivacy.js'
import * as types from '../src/domain/caseTypes.js'
import * as assistant from '../src/domain/assistant.js'
import * as draftDomain from '../src/domain/assistantDraft.js'
import {withAssistantDraftApi} from './assistantDraftApi.mjs'
import * as proposals from '../src/domain/assistantProposal.js'

const task={id:3,status:'awaiting_review',revision:7,source_version:'synthetic-v1',source_changed:false,has_archive:true,execution_profile:{processing_mode:'local'}}
const record={id:'synthetic-case',title:'全虚构恢复检查',case_type:'civil',last_task_id:3,last_task_status:'awaiting_review',last_task_summary:task,files:[]}
const proposal={id:'synthetic-proposal',field:'委托人名称',before:'虚构甲',after:'虚构乙',reason:'明确人工修改建议',revision:7,source_version:'synthetic-v1',expires_at:'2099-01-01T00:00:00Z'}
async function assistantComponent(client){return loadSfc('../src/components/ArchiveAssistant.vue',{'../api/client':esm(withAssistantDraftApi(client)),'../domain/assistant.js':assistant,'../domain/assistantDraft.js':draftDomain,'../domain/workflow.js':workflow,'../domain/assistantProposal.js':proposals})}
const assistantProps={taskId:'3',revision:7,sourceVersion:'synthetic-v1',beforeApply:async()=>'',beforeRecover:async()=>''}

test('a new selected batch must retain the earlier unresolved failed-file retry entry',async()=>{
  const imported=[]
  const client={get:async path=>({data:path==='/cases/synthetic-case'?record:path==='/tasks/3'?task:path.includes('doc-types')?[]:path.includes('readiness')?{mode:'local',ready:true}:{supported_extensions:['.pdf'],max_upload_mb:100}}),post:async(path,body)=>{
    const name=body.get('file').name;imported.push(name)
    if(name==='先前失败.pdf')throw {response:{status:503,data:{detail:'全虚构临时故障'}}}
    return {data:{}}
  }}
  const Component=await loadSfc('../src/views/CaseDetail.vue',{...uploadImports,'vue-router':{useRoute:()=>({params:{id:'synthetic-case'}}),useRouter:()=>({push(){},replace:async()=>{}}),onBeforeRouteLeave(){}},'../api/client':esm(withUploadIntentsApi(client)),'../stores/auth':{useAuthStore:()=>({isAdmin:false})},'../domain/workflow.js':workflow,'../domain/taskExperience.js':experience,'../domain/caseTypes.js':types,'../domain/processingPrivacy.js':privacy,'../domain/useCloudConsent':{useCloudConsent:()=>({approved:Vue.ref(false),reset(){},payload:()=>({cloud_consent:false,expected_processing_mode:'local'})})}})
  const h=mount(Component)
  try{
    await settleUploads(h.root)
    find(h.root,'case-import-files').props.onChange({target:{files:[new File(['a'],'先前失败.pdf')],value:''}});await settleUploads(h.root)
    assert.ok(find(h.root,'case-retry-uploads'))
    find(h.root,'case-import-files').props.onChange({target:{files:[new File(['b'],'后来成功.pdf')],value:''}});await settleUploads(h.root)
    assert.deepEqual(imported,['先前失败.pdf','后来成功.pdf'])
    assert.ok(find(h.root,'case-retry-uploads'),'adding an unrelated successful batch must not silently dismiss the failed file')
    assert.match(content(h.root),/先前失败.pdf/)
    click(find(h.root,'case-dismiss-upload'));await settleUploads(h.root)
    assert.equal(find(h.root,'case-retry-uploads'),undefined)
    assert.deepEqual(imported,['先前失败.pdf','后来成功.pdf'])
  }finally{h.app.unmount()}
})

test('an unsent assistant input must survive remount independently from persisted sent history',async()=>{
  let requests=0
  const Component=await assistantComponent({get:async()=>({data:{messages:[]}}),post:async()=>{requests++;throw new Error('No submit expected')}})
  let h=mount(Component,assistantProps)
  try{
    await settle();input(find(h.root,'assistant-question'),'全虚构尚未发送的核对要求');await settle()
    assert.equal(find(h.root,'assistant-question').props.value,'全虚构尚未发送的核对要求')
    await new Promise(resolve=>setTimeout(resolve,550));await settle()
    assert.match(content(find(h.root,'assistant-draft-status')),/已同步到工作站/)
    h.app.unmount();h=mount(Component,assistantProps);await settle()
    assert.equal(requests,0)
    assert.equal(find(h.root,'assistant-question').props.value,'全虚构尚未发送的核对要求')
  }finally{h.app.unmount()}
})

test('an interrupted adoption must reload persistent state and expose recover-only instead of another adoption',async()=>{
  let status='pending',reads=0,posts=0
  const Component=await assistantComponent({get:async()=>{reads++;return {data:{messages:[{id:2,role:'assistant',content:'全虚构修改建议',status:'completed',tool:'propose_field_change',proposal,proposal_state:status}]}}},post:async()=>{posts++;status='applying';throw {response:{status:503,data:{detail:'备份保留，请检查存储后重试恢复'}}}}})
  const h=mount(Component,assistantProps)
  try{
    await settle();assert.ok(find(h.root,'apply-assistant-proposal'))
    click(find(h.root,'apply-assistant-proposal'));await settle()
    assert.equal(posts,1);assert.match(content(h.root),/备份保留/)
    assert.ok(reads>=2,'failed adoption needs a read-only history reconciliation')
    assert.ok(find(h.root,'recover-assistant-proposal'))
    assert.equal(find(h.root,'apply-assistant-proposal'),undefined)
  }finally{h.app.unmount()}
})

test('unavailable adoption readback disables repeat adoption until explicit read-only history recovery',async()=>{
  let failHistory=false,posts=0
  const Component=await assistantComponent({get:async()=>{
    if(failHistory)throw new Error('synthetic disconnected history')
    return {data:{messages:[{id:2,role:'assistant',content:'全虚构修改建议',status:'completed',tool:'propose_field_change',proposal,proposal_state:posts?'applying':'pending'}]}}
  },post:async()=>{posts++;failHistory=true;throw new Error('synthetic lost response')}})
  const h=mount(Component,assistantProps)
  try{
    await settle();click(find(h.root,'apply-assistant-proposal'));await settle()
    assert.equal(posts,1);assert.ok(find(h.root,'assistant-history-error'))
    assert.equal(find(h.root,'apply-assistant-proposal').props.disabled,true)
    click(find(h.root,'apply-assistant-proposal'));await settle();assert.equal(posts,1)
    failHistory=false;click(find(h.root,'assistant-reload-history'));await settle()
    assert.ok(find(h.root,'recover-assistant-proposal'));assert.equal(posts,1)
  }finally{h.app.unmount()}
})
