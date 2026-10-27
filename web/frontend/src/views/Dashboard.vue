<template>
  <div class="assistant-home">
    <header class="home-intro"><h1 data-testid="dashboard-heading">AI Archiving Assistant</h1><p>卷小助智能归档</p></header>
    <section class="material-drop" :class="{dragging,selected:showImport}" data-testid="material-drop" @dragover.prevent="dragging=true" @dragleave.prevent="dragging=false" @drop.prevent="onDrop">
      <template v-if="!showImport"><span class="drop-symbol"><el-icon><DocumentAdd /></el-icon></span><h2>拖入案件材料</h2><p>PDF、Word、图片或文件夹</p></template>
      <template v-else><div class="selection-heading"><span class="drop-symbol small"><el-icon><DocumentAdd /></el-icon></span><div><h2>已选 {{ selectedFiles.length }} 份材料</h2></div><el-button text :disabled="busy" @click="closeImport">{{ createdCaseId?'查看已导入材料':'取消选择' }}</el-button></div><details class="selected-files"><summary>查看材料</summary><div v-for="(file,index) in selectedFiles" :key="index">{{ file.webkitRelativePath||file.name }}</div></details></template>
      <div v-if="!createdCaseId" class="drop-buttons"><el-button data-testid="import-files" :disabled="busy" @click="fileInput?.click()">{{ showImport?'重新选择文件':'选择文件' }}</el-button><el-button data-testid="import-folder" :disabled="busy" @click="folderInput?.click()">选择文件夹</el-button></div>
      <div v-if="showImport" class="launch-card" data-testid="archive-import-dialog">
        <el-form label-position="top" :disabled="busy||!!createdCaseId" @submit.prevent="startImport"><div class="launch-fields"><el-form-item label="业务类型"><el-select v-model="form.case_type" data-testid="case-type" placeholder="请选择本案业务类型"><el-option v-for="item in types" :key="item.value" :label="item.label+(item.templateReady===false?'（暂未接入原目录）':'')" :value="item.value" :disabled="item.templateReady===false" /></el-select></el-form-item><el-form-item label="案件名称（可选）"><el-input v-model="form.title" :placeholder="suggestedTitle" maxlength="150" /></el-form-item></div><details v-if="form.case_type" class="launch-stage"><summary>办理阶段（可选）</summary><el-select v-model="form.stage" clearable placeholder="待核对，可留空"><el-option v-for="stage in stages" :key="stage.value" :label="stage.label" :value="stage.value" /></el-select></details></el-form>
        <CloudProcessingConsent v-model="cloudApproved" :mode="readiness?.mode||''" :disabled="busy" />
        <p v-if="busy" data-testid="upload-in-progress" class="live-import" role="status">{{ busyMessage }}</p>
        <UploadRecoveryPanel v-if="!busy" :state="uploadState" :disabled="busy" dismiss-test-id="dashboard-dismiss-upload" retry-test-id="dashboard-retry-uploads" @reload="uploadQueue.reload()" @remove="dismissUpload" @recover="recoverUploads" @retry="startImport" />
        <el-alert v-if="launchError" :title="launchError" type="warning" :closable="false" />
        <div class="launch-footer"><el-button data-testid="start-archive" type="primary" size="large" :loading="busy" :disabled="uploadState.busy||!selectedFiles.length||!canCreateArchive(form.case_type)||!readiness||(isCloudProcessing(readiness.mode)&&!cloudApproved)" @click="startImport">{{ busy?'正在处理':uploadState.rows.length?'重试未导入材料':'开始整理' }} <el-icon><ArrowRight /></el-icon></el-button></div>
      </div>
    </section>
    <input ref="fileInput" type="file" multiple :accept="capabilities.supported_extensions.join(',')" hidden @change="selectFiles" /><input ref="folderInput" type="file" multiple webkitdirectory hidden @change="selectFiles" />
    <div class="home-secondary"><button data-testid="sample-case" :disabled="busy || !!createdCaseId" @click="startDemo">{{ demoBusy?'正在准备虚构案例…':'体验示例' }}</button><button @click="openHistory">已有案件</button></div>
    <ArchiveCompanion :key="homeAccount()" :suppressed="showDemoConsent" :presentation="busy?{state:'working',label:'正在导入材料。',short:'导入中'}:launchError?{state:'error',label:'导入遇到问题，请查看页面提示。',short:'需要处理'}:{state:'idle',label:'上传一套材料，我来整理成卷。',short:'问助理'}" :actions="[{kind:'files',label:'选择文件',disabled:busy||!!createdCaseId},{kind:'folder',label:'选择文件夹',disabled:busy||!!createdCaseId},{kind:'history',label:'已有案件'}]" @action="kind=>kind==='files'?fileInput?.click():kind==='folder'?folderInput?.click():openHistory()"><p class="muted">进入案件后，可以在这里提问、查看原文或调整表格。</p></ArchiveCompanion>
    <details class="processing-note"><summary>{{ readiness?.mode==='deepseek_cloud'?'视觉归档':processingLabel(readiness?.mode) }}</summary><p>{{ importHint }}</p></details>
    <el-alert v-if="launchError&&!showImport" :title="launchError" type="warning" :closable="false"><el-button v-if="createdCaseId" text @click="router.push('/cases/'+createdCaseId)">打开已保存材料</el-button></el-alert>
    <p v-if="readiness&&!readiness.ready" class="readiness-note">处理组件暂未就绪。<router-link v-if="auth.isAdmin" to="/settings">检查工作站设置</router-link><span v-else>请联系工作站管理员。</span></p>
    <el-dialog v-model="showDemoConsent" title="用虚构材料体验" width="min(480px,92vw)" :close-on-click-modal="!busy" :show-close="!busy"><p class="muted">示例实际调用{{ cloudProviderName(readiness?.mode) }}模型，会使用标准 API 额度。</p><CloudProcessingConsent v-model="cloudApproved" :mode="readiness?.mode||''" :disabled="busy" /><el-alert v-if="launchError" :title="launchError" type="warning" :closable="false" /><template #footer><el-button :disabled="busy" @click="showDemoConsent=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!cloudApproved" @click="runDemo">开始体验</el-button></template></el-dialog>
  </div>
</template>
<script setup lang="ts">
import { ref,reactive,computed,onMounted,onUnmounted,watch } from 'vue'
import { useRoute,useRouter,onBeforeRouteLeave,onBeforeRouteUpdate } from 'vue-router'
import {ElMessageBox} from 'element-plus'
import { DocumentAdd,ArrowRight } from '@element-plus/icons-vue'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'
import { createRequestId } from '../domain/workflow.js'
import {useUploadRecovery} from '../domain/useUploadRecovery.js'
import UploadRecoveryPanel from '../components/UploadRecoveryPanel.vue'
import ArchiveCompanion from '../components/ArchiveCompanion.vue'
import { CASE_TYPES,stageOptions,canCreateArchive } from '../domain/caseTypes.js'
import { defaultCaseTitle } from '../domain/decisionQueue.js'
import { isCloudProcessing,processingLabel,materialConsentKey,cloudProviderName } from '../domain/processingPrivacy.js'
import { useCloudConsent } from '../domain/useCloudConsent'
import CloudProcessingConsent from '../components/CloudProcessingConsent.vue'
const router=useRouter(),route=useRoute(),auth=useAuthStore()
const showImport=ref(false),busy=ref(false),demoBusy=ref(false),dragging=ref(false),showDemoConsent=ref(false)
const fileInput=ref<HTMLInputElement|null>(null),folderInput=ref<HTMLInputElement|null>(null),selectedFiles=ref<File[]>([])
const createdCaseId=ref(''),launchError=ref(''),busyMessage=ref(''),uploadProgress=ref(0)
const capabilities=ref<any>({supported_extensions:['.pdf'],docx_available:false,max_upload_mb:100}),readiness=ref<any>(null)
const form=reactive({title:'',case_type:'',stage:''}),startKey=ref('')
let leavingAfterStart=false,homeEpoch=0,homeDisposed=false
const homeAccount=()=>String(auth.user?.org_id||'')+':'+String(auth.user?.id||'')
const sameHome=(epoch:number)=>!homeDisposed&&epoch===homeEpoch
const {state:uploadState,queue:uploadQueue}=useUploadRecovery({client,getScope:()=>({caseId:createdCaseId.value,accountScope:String(auth.user?.org_id||'')+':'+String(auth.user?.id||'')}),getCapabilities:()=>capabilities.value,onProgress:(done:number,total:number,name:string)=>{uploadProgress.value=total?Math.round(done/total*100):0;busyMessage.value=done?'正在导入 '+done+' / '+total+' · '+name:name}})
const {approved:cloudApproved,reset:resetCloudConsent,payload:cloudConsentPayload}=useCloudConsent(()=>readiness.value?.mode||'',()=>showImport.value?'import:'+startKey.value+materialConsentKey(selectedFiles.value):'demo:'+startKey.value)
const types=CASE_TYPES,stages=computed(()=>stageOptions(form.case_type)),suggestedTitle=computed(()=>defaultCaseTitle(selectedFiles.value))
watch(()=>form.case_type,()=>{form.stage=''})
const importHint=computed(()=>'PDF'+(capabilities.value.supported_extensions.length>1?'、图片':'')+(capabilities.value.doc_available?'、Word':capabilities.value.docx_available?'、DOCX':''))
function openHistory(){window.dispatchEvent(new Event('gd:open-case-history'))}
function chooseFiles(files:File[]){if(busy.value||createdCaseId.value||!files.length)return;resetCloudConsent();selectedFiles.value=files;try{startKey.value=createRequestId()}catch(e:any){launchError.value=e.message;return};uploadProgress.value=0;launchError.value='';form.title='';form.case_type='';form.stage='';showImport.value=true;loadReadiness()}
function selectFiles(event:Event){const input=event.target as HTMLInputElement;const files=Array.from(input.files||[]);input.value='';chooseFiles(files)}
function onDrop(event:DragEvent){dragging.value=false;chooseFiles(Array.from(event.dataTransfer?.files||[]))}
async function loadReadiness(){try{readiness.value=(await client.get('/settings/readiness')).data;return true}catch{readiness.value=null;return false}}
async function requireProcessing(){if(!(await loadReadiness()))throw new Error('无法确认当前处理方式，请恢复连接后重试。');if(!readiness.value.ready)throw new Error('处理组件尚未就绪，请检查工作站设置。');return cloudConsentPayload()}
async function generate(id:string,epoch=homeEpoch){busyMessage.value='材料已保存，正在启动归档';const consent=await requireProcessing();if(!sameHome(epoch))return;const {data}=await client.post('/cases/'+id+'/generate',{order_mode:'catalog',idempotency_key:startKey.value,...consent});if(!sameHome(epoch))return;showImport.value=false;showDemoConsent.value=false;resetCloudConsent();leavingAfterStart=true;router.push('/cases/'+id+'/tasks/'+data.id)}
async function startImport(){
  if(busy.value||uploadState.value.busy||!canCreateArchive(form.case_type)||!selectedFiles.value.length)return
  const epoch=homeEpoch;busy.value=true;launchError.value=''
  try{
    await requireProcessing();if(!sameHome(epoch))return
    let firstSelection=false
    if(!createdCaseId.value){busyMessage.value='正在建立案件';const created=(await client.post('/cases',{title:form.title.trim()||suggestedTitle.value,case_type:form.case_type,stage:form.stage})).data;if(!sameHome(epoch))return;createdCaseId.value=created.id;await router.replace({path:'/cases',query:{import_case:createdCaseId.value}});firstSelection=true}
    if(!sameHome(epoch))return
    const complete=firstSelection?await uploadQueue.add(selectedFiles.value):await uploadQueue.retry()
    if(!sameHome(epoch)||!complete||uploadState.value.blocked)return
    await generate(createdCaseId.value,epoch)
  }catch(e:any){if(sameHome(epoch))launchError.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:e.message||'暂未启动，已导入材料仍保留，可重试。'}finally{if(sameHome(epoch))busy.value=false}
}
async function startDemo(){if(busy.value||createdCaseId.value)return;showImport.value=false;launchError.value='';createdCaseId.value='';try{startKey.value=createRequestId()}catch(e:any){launchError.value=e.message;return};resetCloudConsent();if(!(await loadReadiness())){launchError.value='无法确认处理方式，请恢复连接后重试。';return}if(isCloudProcessing(readiness.value.mode)){showDemoConsent.value=true;return}await runDemo()}
async function runDemo(){if(busy.value)return;busy.value=true;demoBusy.value=true;launchError.value='';try{await requireProcessing();if(!createdCaseId.value){createdCaseId.value=(await client.post('/demo/cases')).data.case_id}await generate(createdCaseId.value)}catch(e:any){launchError.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:e.message||'示例暂未启动，请检查工作站连接。'}finally{busy.value=false;demoBusy.value=false}}
async function dismissUpload(id:string){if(busy.value)return;await uploadQueue.remove(id)}
async function recoverUploads(files:File[]){if(busy.value)return;await uploadQueue.recover(files)}
function closeImport(){showImport.value=false;resetCloudConsent();if(createdCaseId.value)router.push('/cases/'+createdCaseId.value);else selectedFiles.value=[]}
async function restoreImport(id:any){if(!id||busy.value)return;const epoch=homeEpoch;createdCaseId.value=String(id);launchError.value='';try{await client.get('/cases/'+encodeURIComponent(String(id)));if(!sameHome(epoch))return;await router.replace('/cases/'+encodeURIComponent(String(id)))}catch{if(sameHome(epoch))launchError.value='未能打开此前的案件。请恢复连接或核对当前账号，暂不创建新案件。'}}
function clearHome(){homeEpoch++;busy.value=false;createdCaseId.value='';showImport.value=false;selectedFiles.value=[];startKey.value='';resetCloudConsent()}
watch(()=>route.query.import_case,(id,old)=>{if(!id&&old)clearHome();else if(id&&String(id)!==createdCaseId.value)restoreImport(id)})
watch(homeAccount,()=>{clearHome();if(route.query.import_case)restoreImport(route.query.import_case)})
function beforeImportLeave(event:BeforeUnloadEvent){if(busy.value||uploadState.value.navigationDirty||showImport.value&&!createdCaseId.value){event.preventDefault();event.returnValue=''}}
async function confirmHomeLeave(){if(leavingAfterStart)return true;if(!busy.value&&!uploadState.value.navigationDirty&&(!showImport.value||createdCaseId.value))return true;try{await ElMessageBox.confirm('尚有材料正在处理或未登记，离开会中断。已登记的待上传项可在案件中恢复。','离开导入？',{confirmButtonText:'离开',cancelButtonText:'继续导入'});return true}catch{return false}}
onBeforeRouteLeave(confirmHomeLeave)
onBeforeRouteUpdate((to:any)=>to.query.import_case===createdCaseId.value?true:confirmHomeLeave())
onUnmounted(()=>{homeDisposed=true;homeEpoch++;globalThis.window?.removeEventListener('beforeunload',beforeImportLeave)})
onMounted(async()=>{globalThis.window?.addEventListener('beforeunload',beforeImportLeave);if(route.query.import_case){await restoreImport(route.query.import_case);return}try{capabilities.value=(await client.get('/cases/meta/import-capabilities')).data}catch{}await loadReadiness();if(route.query.history==='1')openHistory()})
</script>
<style scoped>
.assistant-home{max-width:780px;margin:7vh auto 0}.home-intro{text-align:center;margin-bottom:38px}.home-eyebrow{font-size:11px;letter-spacing:.12em;color:#6e6e73}.home-intro h1{font-size:35px;line-height:1.65;font-weight:450;letter-spacing:.02em;margin:14px 0}.home-intro p{font-size:13px;color:#6e6e73;line-height:1.9;margin:10px 0}.material-drop{border:1px dashed #d2d2d7;background:#fff;border-radius:18px;padding:42px 36px;text-align:center;transition:background .15s,border-color .15s}.material-drop.dragging{background:#f5f5f7;border-color:#424245}.drop-symbol{width:48px;height:48px;display:grid;place-items:center;background:#f5f5f7;color:#6e6e73;border-radius:15px;font-size:25px;margin:0 auto 19px}.drop-symbol.small{margin:0;width:40px;height:40px;flex:none;font-size:20px}.material-drop h2{font-size:18px;line-height:1.7;font-weight:500;margin:0 0 8px;color:#424245}.material-drop p{font-size:12px;color:#6e6e73;line-height:1.9}.drop-buttons{display:flex;justify-content:center;gap:10px;margin-top:23px}.drop-buttons .el-button{margin-left:0}.material-drop.selected{text-align:left;padding:26px}.selection-heading{display:flex;align-items:center;gap:14px}.selection-heading>div{flex:1}.selection-heading h2{font-size:16px;margin:0}.selection-heading p{margin:3px 0}.selected-files{font-size:11px;color:#6e6e73;margin:18px 0;max-height:160px;overflow:auto;line-height:1.9}.selected-files summary{cursor:pointer}.selected-files>div{padding:4px 0;overflow-wrap:anywhere}.selected .drop-buttons{justify-content:flex-start;margin:10px 0}.launch-card{margin-top:25px;padding-top:24px;border-top:1px solid #f5f5f7}.launch-fields{display:grid;grid-template-columns:1fr 1.3fr;gap:20px}.launch-fields .el-select{width:100%}.launch-stage{font-size:11px;color:#6e6e73;margin-bottom:18px}.launch-stage>summary{cursor:pointer;margin-bottom:10px}.launch-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:24px}.launch-footer>span{font-size:11px;line-height:1.8;color:#6e6e73}.launch-footer .el-icon{margin-left:10px}.home-secondary{display:flex;justify-content:center;gap:28px;margin:24px 0}.home-secondary button{border:0;background:none;color:#6e6e73;font-size:12px;cursor:pointer}.home-secondary button:disabled{opacity:.5;cursor:wait}.processing-note{text-align:center;font-size:11px;line-height:1.8;color:#6e6e73;margin:32px 0 12px}.processing-note>span{color:#6e6e73}.readiness-note{font-size:12px;text-align:center;color:#a38d67;margin-top:20px}.readiness-note a{text-decoration:underline}.live-import{color:#6e6e73!important}.launch-card .el-alert{margin-top:12px}@media(max-width:650px){.assistant-home{margin-top:24px}.home-intro h1{font-size:27px}.home-intro{margin-bottom:26px}.material-drop{padding:28px 18px}.material-drop.selected{padding:20px}.launch-fields{grid-template-columns:1fr;gap:0}.launch-footer{align-items:stretch;flex-direction:column}.selection-heading{gap:9px}.selection-heading>.el-button{padding:5px}}
</style>



