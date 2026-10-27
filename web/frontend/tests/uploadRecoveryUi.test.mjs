// Real production Vue SFCs, synthetic workstation API and in-memory renderer.
// No browser, server, model, customer document or browser storage is involved.
import test from 'node:test'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,content,click,esm} from './vueHarness.mjs'
import {withUploadIntentsApi,uploadImports} from './uploadRecoveryApi.mjs'
import * as workflow from '../src/domain/workflow.js'
import * as experience from '../src/domain/taskExperience.js'
import * as privacy from '../src/domain/processingPrivacy.js'
import * as types from '../src/domain/caseTypes.js'
import * as decisions from '../src/domain/decisionQueue.js'
import * as issueReview from '../src/domain/issueReview.js'
import * as fieldDecision from '../src/domain/fieldDecision.js'
import * as review from '../src/domain/review.js'
const settle=async()=>{for(let i=0;i<4;i++){await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick()}}
const file=(name,body=name)=>new File([body],name,{type:'application/pdf'})
function server(){
  const events=[],uploads=[],files=[];let fail=true
  const task={id:3,revision:7,status:'awaiting_review',phase:'draft_ready',has_archive:true,delivery_kind:'draft',source_version:'synthetic-v1',issues:[],catalog_status:[],fields:{},execution_profile:{processing_mode:'deepseek_cloud',authorized_source_version:'synthetic-v1',cloud_consent:true},can_resume:true}
  const client=withUploadIntentsApi({get:async path=>{
    if(path==='/cases/c')return {data:{id:'c',title:'虚构恢复卷',case_type:'civil',last_task_id:3,files,last_task_status:'awaiting_review'}}
    if(path==='/tasks/3')return {data:{...task,source_changed:files.length>0}}
    if(path.includes('readiness'))return {data:{ready:true,mode:'local'}}
    if(path.endsWith('/templates'))return {data:{templates:['立案审批表']}}
    if(path.includes('doc-types'))return {data:[]}
    return {data:{supported_extensions:['.pdf'],max_upload_mb:100}}
  },post:async(path,body,config)=>{events.push(['post',path]);if(path==='/cases')return {data:{id:'c'}};if(path.endsWith('/files')){const f=body.get('file');uploads.push({name:f.name,key:config.headers['Idempotency-Key']});if(f.name==='待补.pdf'&&fail)throw {response:{status:503,data:{detail:'全虚构上传故障'}}};files.push({id:'f'+files.length,filename:f.name});return {data:{id:'f'+files.length}}};return {data:{id:3}}}})
  const rawPut=client.put;client.put=async(path,...args)=>{events.push(['put',path]);return rawPut(path,...args)}
  return {client,events,uploads,files,setFail:value=>{fail=value}}
}
async function page(kind,api,{query={},account='u',caseAllowed=true}={}){
  const routes=[],replacements=[],listeners=new Map();let leave
  const route=Vue.reactive({params:{id:'c',taskId:'3'},query}),auth=Vue.reactive({token:'synthetic',isAdmin:false,user:{org_id:'o',id:account}})
  const baseGet=api.client.get
  const client={...api.client,get:(path,...args)=>{if(!caseAllowed&&path==='/cases/c')return Promise.reject({response:{status:404}});return baseGet(path,...args)}}
  const Component=await loadSfc('../src/views/'+kind+'.vue',{...uploadImports,'vue-router':{useRoute:()=>route,useRouter:()=>({push:path=>routes.push(path),replace:async path=>{replacements.push(path);api.events.push(['replace',path]);if(typeof path==='object')route.query=path.query}}),onBeforeRouteLeave:fn=>{leave=fn},onBeforeRouteUpdate(){}},'../api/client':esm(client),'../stores/auth':{useAuthStore:()=>auth},'../domain/workflow.js':workflow,'../domain/taskExperience.js':experience,'../domain/processingPrivacy.js':privacy,'../domain/caseTypes.js':types,'../domain/decisionQueue.js':decisions,'../domain/issueReview.js':issueReview,'../domain/fieldDecision.js':fieldDecision,'../domain/review.js':review,'../domain/useCloudConsent':{useCloudConsent:()=>({approved:Vue.ref(false),reset(){},payload:()=>({cloud_consent:false,expected_processing_mode:'local'})})}})
  const previous=globalThis.window;globalThis.window={addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),location:{protocol:'http:',host:'synthetic'}}
  const h=mount(Component);await settle()
  return {...h,routes,replacements,route,auth,listeners,leave:()=>leave(),dispose(){h.app.unmount();globalThis.window=previous}}
}
const choose=async(h,testId,files)=>{find(h.root,testId).props.onChange({target:{files,value:''}});await settle()}

test('case page remount recovers failed metadata and folder reselection uploads only the unfinished original request',async()=>{
  const api=server();let h=await page('CaseDetail',api)
  try{await choose(h,'case-import-files',[file('成功.pdf'),file('待补.pdf')]);assert.ok(find(h.root,'case-retry-uploads'));const originalKey=api.uploads[1].key
    h.dispose();h=await page('CaseDetail',api);assert.match(content(find(h.root,'upload-recovery')),/重新选择原文件/);assert.equal(find(h.root,'case-retry-uploads'),undefined)
    await choose(h,'upload-recovery-folder',[file('成功.pdf'),file('待补.pdf'),file('变更.pdf')]);assert.match(content(h.root),/已导入 1 份/);assert.match(content(h.root),/不匹配/);assert.equal(api.uploads.length,2)
    api.setFail(false);click(find(h.root,'case-retry-uploads'));await settle();assert.deepEqual(api.uploads.map(x=>x.name),['成功.pdf','待补.pdf','待补.pdf']);assert.equal(api.uploads[2].key,originalKey);assert.match(content(h.root),/不匹配/);assert.equal(find(h.root,'case-retry-uploads'),undefined)
  }finally{h.dispose()}
})

test('task supplement remount retains failed work and successful recovery waits for cloud authorization without a false failure',async()=>{
  const api=server();let h=await page('TaskProgress',api)
  try{await choose(h,'task-supplement-files',[file('成功.pdf'),file('待补.pdf')]);assert.ok(find(h.root,'task-retry-uploads'));assert.equal(api.events.filter(([m,p])=>m==='post'&&p.endsWith('/resume')).length,0)
    h.dispose();h=await page('TaskProgress',api);assert.match(content(h.root),/还有 1 份材料待导入/);await choose(h,'upload-recovery-files',[file('待补.pdf')]);api.setFail(false);click(find(h.root,'task-retry-uploads'));await settle()
    assert.equal(api.uploads.length,3);assert.equal(find(h.root,'task-retry-uploads'),undefined);assert.equal(find(h.root,'archive-operation-error'),undefined);assert.match(content(find(h.root,'supplement-consent')),/补件已保存在工作站/);assert.equal(api.events.filter(([m,p])=>m==='post'&&p.endsWith('/resume')).length,0)
  }finally{h.dispose()}
})

test('home stores only case ID before registration and refresh opens that authorized case without creating another',async()=>{
  const api=server();let h=await page('Dashboard',api)
  try{find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file('待补.pdf')]}});await settle();find(h.root,'case-type').props.onChange({target:{value:'civil'}});await settle();click(find(h.root,'start-archive'));await settle()
    assert.deepEqual(h.replacements[0],{path:'/cases',query:{import_case:'c'}});assert.ok(api.events.findIndex(([m])=>m==='replace')<api.events.findIndex(([m])=>m==='put'));assert.ok(find(h.root,'dashboard-retry-uploads'))
    const count=api.events.filter(([m,p])=>m==='post'&&p==='/cases').length;h.dispose();h=await page('Dashboard',api,{query:{import_case:'c'}});assert.deepEqual(h.replacements,['/cases/c']);assert.equal(api.events.filter(([m,p])=>m==='post'&&p==='/cases').length,count)
  }finally{h.dispose()}
})

test('home cannot turn an inaccessible recovery URL into a new case or upload queue',async()=>{
  const api=server(),h=await page('Dashboard',api,{query:{import_case:'c'},caseAllowed:false})
  try{const alert=node=>node.props.title?.includes('核对当前账号')?node:node.children.map(alert).find(Boolean);assert.ok(alert(h.root));find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file('另一份.pdf')]}});await settle();assert.equal(find(h.root,'archive-import-dialog'),undefined);assert.equal(api.events.filter(([m])=>m==='put'||m==='post').length,0);assert.deepEqual(h.replacements,[])}finally{h.dispose()}
})

test('home ignores a late case-creation receipt after account switch and cannot upload the previous account selection',async()=>{
  const api=server(),original=api.client.post;let resolveCreate
  api.client.post=async(path,...args)=>path==='/cases'?new Promise(resolve=>{resolveCreate=resolve}):original(path,...args)
  const h=await page('Dashboard',api)
  try{find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file('旧账号.pdf')]}});await settle();find(h.root,'case-type').props.onChange({target:{value:'civil'}});await settle();click(find(h.root,'start-archive'));await settle();assert.equal(typeof resolveCreate,'function');h.auth.user={org_id:'o',id:'other'};await settle();resolveCreate({data:{id:'c'}});await settle();assert.equal(find(h.root,'archive-import-dialog'),undefined);assert.deepEqual(h.replacements,[]);assert.deepEqual(api.uploads,[]);assert.equal(api.events.filter(([m])=>m==='put').length,0)}finally{h.dispose()}
})

test('home back and forward query navigation restores the existing authorized case without retaining the old selection',async()=>{
  const api=server(),h=await page('Dashboard',api)
  try{find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file('待补.pdf')]}});await settle();find(h.root,'case-type').props.onChange({target:{value:'civil'}});await settle();click(find(h.root,'start-archive'));await settle();assert.ok(find(h.root,'dashboard-retry-uploads'));const before=api.events.filter(([m,p])=>m==='post'&&p==='/cases').length
    h.route.query={};await settle();assert.equal(find(h.root,'archive-import-dialog'),undefined);h.route.query={import_case:'c'};await settle();assert.equal(h.replacements.at(-1),'/cases/c');assert.equal(api.events.filter(([m,p])=>m==='post'&&p==='/cases').length,before);assert.equal(api.uploads.length,1)
  }finally{h.dispose()}
})


test('home first active upload is processing, not a retry; a stopped failure still offers retry',async()=>{
  const api=server(),original=api.client.post;let release
  api.client.post=async(path,...args)=>{if(path.endsWith('/files'))await new Promise(resolve=>{release=resolve});return original(path,...args)}
  const h=await page('Dashboard',api)
  try {
    find(h.root,'material-drop').props.onDrop({preventDefault(){},dataTransfer:{files:[file('待补.pdf')]}})
    await settle();find(h.root,'case-type').props.onChange({target:{value:'civil'}});await settle()
    click(find(h.root,'start-archive'));await settle()
    assert.equal(typeof release,'function')
    assert.ok(!content(find(h.root,'start-archive')).includes('重试'))
    assert.ok(content(find(h.root,'start-archive')).includes('正在'))
    release();await settle()
    assert.ok(content(find(h.root,'start-archive')).includes('重试未导入材料'))
    assert.ok(find(h.root,'dashboard-retry-uploads'))
  }finally{release?.();h.dispose()}
})
