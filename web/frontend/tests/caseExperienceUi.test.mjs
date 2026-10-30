import {withUploadIntentsApi,uploadImports,settleUploads} from './uploadRecoveryApi.mjs'
import test from 'node:test'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,content,click,settle,esm} from './vueHarness.mjs'
import * as workflow from '../src/domain/workflow.js'
import * as experience from '../src/domain/taskExperience.js'
import * as privacy from '../src/domain/processingPrivacy.js'
import * as types from '../src/domain/caseTypes.js'
import * as deletion from '../src/domain/caseDeletion.js'
const task={id:3,status:'awaiting_review',phase:'draft_ready',revision:1,delivery_kind:'draft',has_archive:true,can_resume:true,source_changed:false,execution_profile:{processing_mode:'local'}}
const record={id:'synthetic-case',title:'虚构案件',case_type:'civil',stage:'',last_task_id:3,last_task_status:'awaiting_review',last_task_summary:task,files:[{id:'f',filename:'虚构.pdf',file_size:100,doc_type:'default'}]}
async function caseHarness({currentTask=task,post}={}){
  const calls=[],routes=[]
  const client={get:async path=>({data:path==='/cases/synthetic-case'?record:path==='/tasks/3'?currentTask:path.includes('doc-types')?[]:path.includes('readiness')?{ready:true,mode:'local'}:{supported_extensions:['.pdf'],max_upload_mb:100}}),post:async(path,body,config)=>{calls.push({path,body});return post?post(path,body,config):{data:{id:3}}}}
  const Component=await loadSfc('../src/views/CaseDetail.vue',{...uploadImports,'vue-router':{useRoute:()=>({params:{id:'synthetic-case'}}),useRouter:()=>({push:path=>routes.push(path),replace:async()=>{}}),onBeforeRouteLeave(){}},'../api/client':esm(withUploadIntentsApi(client)),'../stores/auth':{useAuthStore:()=>({isAdmin:false})},'../domain/workflow.js':workflow,'../domain/taskExperience.js':experience,'../domain/caseTypes.js':types,'../domain/processingPrivacy.js':privacy,'../domain/useCloudConsent':{useCloudConsent:()=>({approved:Vue.ref(false),reset(){},payload:()=>({cloud_consent:false,expected_processing_mode:'local'})})}})
  const h=mount(Component);await settle();return {...h,calls,routes,setTask(value){currentTask=value}}
}

test('real material page treats an existing draft as a result, opens it with one action and makes no new generate/resume request',async()=>{
  const h=await caseHarness()
  try{assert.match(content(find(h.root,'case-task-state')),/草稿已生成/);assert.match(content(find(h.root,'case-primary-action')),/查看与下载草稿/);assert.doesNotMatch(content(h.root),/表格与缺项确认后|等待你核对/);click(find(h.root,'case-primary-action'));assert.deepEqual(h.routes,['/cases/synthetic-case/tasks/3']);assert.deepEqual(h.calls,[])}finally{h.app.unmount()}
})

test('existing case action updates only the server-projected rule plan with the frozen local mode',async()=>{
  const token='a'.repeat(64)
  const h=await caseHarness({currentTask:{...task,execution_profile:{processing_mode:'ollama_local'},
    form_policy_update:{available:true,token,fields:['结案小结']}},post:async()=>({data:{id:4}})})
  try{
    assert.match(content(find(h.root,'case-primary-action')),/更新表单草稿/)
    click(find(h.root,'case-primary-action'));await settle()
    assert.deepEqual(h.calls,[{path:'/tasks/3/resume',body:{cloud_consent:false,expected_processing_mode:'ollama_local',form_policy_token:token}}])
    assert.deepEqual(h.routes,['/cases/synthetic-case/tasks/4'])
  }finally{h.app.unmount()}
})

test('case refresh retains an already selected plan for lost-response recovery',async()=>{
  const token='a'.repeat(64)
  const value={...task,execution_profile:{processing_mode:'ollama_local'},
    form_policy_update:{available:true,token,fields:['结案小结']}}
  const h=await caseHarness({currentTask:value,post:async()=>({data:{id:4}})})
  try{
    h.setTask({...value,form_policy_update:null})
    click(find(h.root,'case-primary-action'));await settle()
    assert.deepEqual(h.calls,[{path:'/tasks/3/resume',body:{cloud_consent:false,expected_processing_mode:'ollama_local',form_policy_token:token}}])
    assert.deepEqual(h.routes,['/cases/synthetic-case/tasks/4'])
  }finally{h.app.unmount()}
})

test('case refresh does not submit a changed rule scope',async()=>{
  const value={...task,execution_profile:{processing_mode:'ollama_local'},
    form_policy_update:{available:true,token:'a'.repeat(64),fields:['结案小结']}}
  const h=await caseHarness({currentTask:value})
  try{
    h.setTask({...value,form_policy_update:{...value.form_policy_update,token:'b'.repeat(64)}})
    click(find(h.root,'case-primary-action'));await settle()
    assert.deepEqual(h.calls,[]);assert.deepEqual(h.routes,[])
  }finally{h.app.unmount()}
})

test('cloud rule update is disabled until the existing consent control is approved',async()=>{
  const h=await caseHarness({currentTask:{...task,source_version:'v1',
    execution_profile:{processing_mode:'deepseek_cloud',cloud_consent:true,authorized_source_version:'v1'},
    form_policy_update:{available:true,token:'a'.repeat(64),fields:['结案小结']}}})
  try{
    assert.match(content(find(h.root,'case-primary-action')),/更新表单草稿/)
    assert.equal(find(h.root,'case-primary-action').props.disabled,true)
    assert.deepEqual(h.calls,[])
  }finally{h.app.unmount()}
})

test('real material page opens ongoing processing instead of inviting a duplicate start',async()=>{
  const h=await caseHarness({currentTask:{...task,status:'running',has_archive:false}})
  try{assert.match(content(find(h.root,'case-primary-action')),/查看整理进度/);assert.equal(find(h.root,'case-primary-action').props.disabled,false);click(find(h.root,'case-primary-action'));assert.equal(h.routes.length,1);assert.deepEqual(h.calls,[])}finally{h.app.unmount()}
})

test('real material page retries only failed imports and retains the successfully imported file',async()=>{
  let fail=true;const names=[],keys=[]
  const h=await caseHarness({post:async(path,body,config)=>{const name=body.get('file').name;names.push(name);keys.push(config.headers['Idempotency-Key']);if(name==='失败.pdf'&&fail)throw {response:{status:503,data:{detail:'暂时不可用'}}};return {data:{}}}})
  try{find(h.root,'case-import-files').props.onChange({target:{files:[new File(['a'],'成功.pdf'),new File(['b'],'失败.pdf')],value:''}});await settleUploads(h.root);assert.ok(find(h.root,'case-retry-uploads'));fail=false;click(find(h.root,'case-retry-uploads'));await settleUploads(h.root);assert.deepEqual(names,['成功.pdf','失败.pdf','失败.pdf']);assert.ok(keys[1]);assert.equal(keys[1],keys[2]);assert.notEqual(keys[0],keys[1]);assert.equal(find(h.root,'case-retry-uploads'),undefined)}finally{h.app.unmount()}
})

test('real history drawer uses the same persisted draft/download status and opens the result task directly',async()=>{
  const routes=[],previous=globalThis.window;globalThis.window={addEventListener(){},removeEventListener(){}}
  const Component=await loadSfc('../src/App.vue',{'vue-router':{useRoute:()=>({name:'cases',fullPath:'/cases',path:'/cases'}),useRouter:()=>({push:path=>routes.push(path)})},'./stores/auth':{useAuthStore:()=>({token:'synthetic',isAdmin:false,fetchMe:async()=>{},user:{id:1,org_id:1}})},'./api/client':esm({get:async()=>({data:[record]})}),'./domain/caseDeletion.js':deletion,'./domain/taskExperience.js':experience})
  const h=mount(Component)
  try{await settle();click(find(h.root,'open-case-history'));await settle();assert.match(content(find(h.root,'case-history')),/草稿可下载/);const button=n=>n.type==='button'&&content(n).includes('虚构案件')?n:n.children.map(button).find(Boolean);click(button(h.root));assert.deepEqual(routes,['/cases/synthetic-case/tasks/3'])}finally{h.app.unmount();globalThis.window=previous}
})
