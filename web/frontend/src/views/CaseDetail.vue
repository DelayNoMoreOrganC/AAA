<template>
  <div v-loading="loading" class="case-workspace">
    <router-link class="back-link" to="/cases"><el-icon><ArrowLeft /></el-icon> 新归档</router-link>
    <div class="page-toolbar"><div><div class="page-kicker">{{ typeLabel(detail?.case_type) }}<template v-if="detail?.stage"> · {{ caseStageLabel(detail.stage) }}</template></div><h1 class="page-heading">{{ detail?.title || '正在打开案件' }}</h1></div><div v-if="detail" class="case-heading-actions"><el-tag type="info" effect="plain">{{ detail.files?.length || 0 }} 份材料</el-tag><DeleteCaseButton :case-record="detail" :disabled="loading||uploading||generating" @deleted="router.replace('/cases')" /></div></div>
    <el-alert v-if="pageError" type="error" :closable="false" :title="pageError" style="margin-bottom:20px"><el-button text @click="load">重新加载</el-button></el-alert>
    <div class="case-columns">
      <section class="surface material-panel">
        <div class="page-toolbar" style="margin-bottom:18px"><h2 class="section-title" style="margin:0">案件材料</h2><el-dropdown trigger="click"><el-button :disabled="uploading||activeTask">添加材料 <el-icon><ArrowDown /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="fileInput?.click()">选择文件</el-dropdown-item><el-dropdown-item @click="folderInput?.click()">选择文件夹</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        <div class="import-zone" :class="{dragging}" @dragover.prevent="dragging=true" @dragleave.prevent="dragging=false" @drop.prevent="onDrop">
          <el-icon><Upload /></el-icon><p>把案件材料拖到这里</p><span>或 <button @click="fileInput?.click()" :disabled="uploading||activeTask">选择文件</button> / <button @click="folderInput?.click()" :disabled="uploading||activeTask">导入文件夹</button></span><small>{{ importHint }}</small>
        </div>
        <input ref="fileInput" data-testid="case-import-files" type="file" multiple :accept="accept" hidden @change="onFilesSelected" />
        <input ref="folderInput" type="file" webkitdirectory multiple hidden @change="onFilesSelected" />
        <div v-if="uploading" data-testid="upload-in-progress" class="upload-progress"><el-progress :percentage="Math.round(uploadIndex / uploadTotal * 100)" :stroke-width="4" /><p class="muted">正在导入 {{ uploadIndex }} / {{ uploadTotal }} · {{ uploadingName }}</p></div>
        <UploadRecoveryPanel :state="uploadState" :disabled="uploading||activeTask" dismiss-test-id="case-dismiss-upload" retry-test-id="case-retry-uploads" @reload="uploadQueue.reload()" @remove="dismissUpload" @recover="recoverUploads" @retry="retryUploads" />
        <div class="file-list">
          <div v-for="file in detail?.files || []" :key="file.id" class="file-row">
            <span class="file-icon"><el-icon><Document /></el-icon></span>
            <div class="file-body"><button class="filename" @click="openOriginal(file)">{{ file.filename }}</button><div class="file-metadata">{{ formatSize(file.file_size) }}</div><details class="material-classification"><summary>材料类型（高级）</summary><p class="muted">默认由助理识别。此设置作用于整份文件，综合扫描卷请保持“综合文档”。</p><el-select v-model="file.doc_type" size="small" filterable class="doc-type-select" :disabled="uploading||activeTask" @change="onTypeChange(file)"><el-option v-for="type in docTypes" :key="type.value" :label="type.label" :value="type.value" /></el-select></details></div>
            <el-button text :icon="Delete" :disabled="uploading||activeTask" :aria-label="'删除 '+file.filename" @click="onDeleteFile(file)" />
          </div>
          <div v-if="!detail?.files?.length && !uploading" class="muted empty-files">尚未导入材料</div>
        </div>
      </section>
      <aside class="case-action-panel">
        <section class="surface">
          <h2 class="section-title" data-testid="case-task-state">{{ presentation.title }}</h2>
          <details class="small-details"><summary>详情</summary><p class="muted">{{ presentation.description }}</p></details>
          <p class="muted">{{ processingLabel(processingMode) }}</p>
          <el-alert v-if="!lastTask && readiness && !readiness.ready" type="warning" :closable="false" title="工作站处理组件尚未就绪" style="margin-top:16px"><div v-for="issue in readiness.issues || []" :key="issue" class="muted">{{ issue }}</div><router-link v-if="auth.isAdmin" to="/settings" style="font-size:12px">检查工作站设置 →</router-link><p v-else class="muted">请联系工作站管理员，材料会保留在这里。</p></el-alert>
          <CloudProcessingConsent v-if="cloudConsentRequired && !openExistingTask" v-model="cloudApproved" :mode="processingMode" :disabled="generating||uploading" />
          <p v-else-if="lastTask && isCloudProcessing(processingMode) && !cloudConsentRequired" class="muted">当前材料已获云端授权</p>
          <details v-if="!detail?.last_task_id" class="material-classification"><summary>排列设置（高级）</summary><el-form label-position="top" style="margin-top:16px"><el-form-item label="正文排列"><el-radio-group v-model="orderMode"><el-radio value="catalog">按目录顺序（默认）</el-radio><el-radio value="original">按原始顺序</el-radio></el-radio-group></el-form-item></el-form></details>
          <el-button data-testid="case-primary-action" type="primary" :loading="generating" :disabled="uploading || (!openExistingTask && (uploadState.blocked || !detail?.files?.length || activeTask || !processingMode || (detail?.last_task_id&&!lastTask) || (cloudConsentRequired&&!cloudApproved) || (!lastTask && readiness && !readiness.ready)))" style="width:100%;margin-top:18px" @click="performCaseAction">{{ presentation.action }} <el-icon style="margin-left:8px"><ArrowRight /></el-icon></el-button>
          
        </section>
        <details class="material-tips"><summary>材料与历史说明</summary><p>一份完整扫描卷宗可保持「综合文档」。分开的文书可以由助理识别，也可在这里检查分类。</p><p>补件后继续归档会生成新修订；此前成果仍保留，但不包含新增材料。</p><router-link v-if="auth.isAdmin" to="/settings">工作站设置 <span>↗</span></router-link></details>
        <section v-if="detail?.done_tasks?.length" class="completed-tasks"><h2 class="section-title">已保存的成果</h2><div v-for="task in detail.done_tasks" :key="task.id" class="completed-task"><div class="muted">{{ task.id!==detail.last_task_id?'历史成果 · ':'' }}{{ task.delivery_kind==='draft'?'草稿':'已核对成果' }} · {{ fmtDate(task.finished_at) }} · 任务 {{ task.id }}</div><el-button text type="primary" @click="goTask(task.id)">查看与下载 <el-icon><ArrowRight /></el-icon></el-button></div></section>
      </aside>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { ArrowLeft, ArrowRight, ArrowDown, Upload, Document, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatShanghaiTime,createRequestId } from '../domain/workflow.js'
import { caseTaskSummary,caseTaskPresentation } from '../domain/taskExperience.js'
import { caseTypeLabel, caseStageLabel } from '../domain/caseTypes.js'
import { isCloudProcessing,processingLabel,materialConsentKey,resumeProcessingMode,taskNeedsCloudConsent,capturedFormPolicyToken,validateFormPolicyRefresh } from '../domain/processingPrivacy.js'
import { useCloudConsent } from '../domain/useCloudConsent'
import CloudProcessingConsent from '../components/CloudProcessingConsent.vue'
import DeleteCaseButton from '../components/DeleteCaseButton.vue'
import UploadRecoveryPanel from '../components/UploadRecoveryPanel.vue'
import {useUploadRecovery} from '../domain/useUploadRecovery.js'
const auth=useAuthStore()
const route=useRoute(), router=useRouter(), caseId=String(route.params.id)
const detail=ref<any>(null), loading=ref(false), pageError=ref(''), generating=ref(false), orderMode=ref('catalog')
const fileInput=ref<HTMLInputElement|null>(null), folderInput=ref<HTMLInputElement|null>(null), dragging=ref(false)
const uploadIndex=ref(0), uploadTotal=ref(0), uploadingName=ref('')
const docTypes=ref<any[]>([{value:'default',label:'综合文档 / 待识别'}])
const capabilities=ref<any>({supported_extensions:['.pdf'],docx_available:false,max_upload_mb:100})
const readiness=ref<any>(null)
const lastTask=ref<any>(null)
const currentSummary=computed(()=>lastTask.value||caseTaskSummary(detail.value))
const presentation=computed(()=>caseTaskPresentation(currentSummary.value))
const openExistingTask=computed(()=>!!detail.value?.last_task_id&&!currentSummary.value?.source_changed&&!currentSummary.value?.form_policy_update?.available)
const processingMode=computed(()=>lastTask.value?resumeProcessingMode(lastTask.value):readiness.value?.mode||'')
const cloudConsentRequired=computed(()=>isCloudProcessing(processingMode.value)&&(!lastTask.value||taskNeedsCloudConsent(lastTask.value)))
const {approved:cloudApproved,reset:resetCloudConsent,payload:cloudConsentPayload}=useCloudConsent(()=>processingMode.value,()=>caseId+materialConsentKey(detail.value?.files)+':'+(lastTask.value?.source_version||'')+':'+(lastTask.value?.form_policy_update?.token||''))
let generateKey=''
const {state:uploadState,queue:uploadQueue}=useUploadRecovery({client,getScope:()=>({caseId,accountScope:String(auth.user?.org_id||'')+':'+String(auth.user?.id||'')}),getCapabilities:()=>capabilities.value,onProgress:(done:number,total:number,name:string)=>{uploadIndex.value=done;uploadTotal.value=total;uploadingName.value=name}})
const uploading=computed(()=>uploadState.value.busy)
async function loadReadiness(){try{readiness.value=(await client.get('/settings/readiness')).data}catch{readiness.value=null}}
const accept=computed(()=>capabilities.value.supported_extensions.join(','))
const importHint=computed(()=>capabilities.value.supported_extensions.length>1 ? '支持 PDF、图片'+(capabilities.value.doc_available?'、Word（DOC / DOCX）':capabilities.value.docx_available?'、DOCX':'')+' · 单份不超过 '+capabilities.value.max_upload_mb+' MB':'PDF · 其他格式以工作站实际支持为准')
const activeTask=computed(()=>['pending','running'].includes(detail.value?.last_task_status))
const typeLabel=caseTypeLabel
const fmtDate=formatShanghaiTime
function formatSize(v:number){return v>1024*1024?(v/1024/1024).toFixed(1)+' MB':Math.max(1,Math.round(v/1024))+' KB'}
async function load(quiet=false){if(!quiet)loading.value=true;pageError.value='';try{detail.value=(await client.get('/cases/'+caseId)).data;lastTask.value=detail.value.last_task_id?(await client.get('/tasks/'+detail.value.last_task_id)).data:null;docTypes.value=(await client.get('/cases/meta/doc-types',{params:{case_type:detail.value.case_type}})).data}catch(e:any){lastTask.value=null;pageError.value=e.response?.data?.detail||'无法加载案件，请重试'}finally{loading.value=false}}
async function loadCapabilities(){try{capabilities.value=(await client.get('/cases/meta/import-capabilities')).data}catch{/* Old backends accept PDF only. */}}
function onFilesSelected(e:Event){const input=e.target as HTMLInputElement;const files=Array.from(input.files||[]);input.value='';uploadFiles(files)}
function onDrop(e:DragEvent){dragging.value=false;if(!uploading.value)uploadFiles(Array.from(e.dataTransfer?.files||[]))}
async function uploadFiles(files:File[]){
  if(uploading.value||activeTask.value||!files.length)return
  resetCloudConsent();const complete=await uploadQueue.add(files);await load(true)
  if(complete)ElMessage.success('材料已导入')
}
async function retryUploads(){if(uploading.value||activeTask.value)return;resetCloudConsent();await uploadQueue.retry();await load(true)}
async function recoverUploads(files:File[]){if(uploading.value||activeTask.value)return;await uploadQueue.recover(files)}
async function dismissUpload(id:string){if(uploading.value||activeTask.value)return;await uploadQueue.remove(id)}
async function onTypeChange(file:any){resetCloudConsent();try{await client.patch('/cases/'+caseId+'/files/'+file.id,{doc_type:file.doc_type});await load(true)}catch(e:any){ElMessage.error(e.response?.data?.detail||'分类保存失败');await load(true)}}
async function onDeleteFile(file:any){try{await ElMessageBox.confirm('从案件中移除「'+file.filename+'」？','移除材料',{confirmButtonText:'移除',cancelButtonText:'保留',type:'warning'})}catch{return}resetCloudConsent();try{await client.delete('/cases/'+caseId+'/files/'+file.id);await load(true)}catch(e:any){ElMessage.error(e.response?.data?.detail||'移除失败')}}
async function openOriginal(file:any){try{const {data}=await client.get('/cases/'+caseId+'/files/'+file.id+'/original',{responseType:'blob'});const url=URL.createObjectURL(data);const a=document.createElement('a');a.href=url;a.download=file.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}catch{ElMessage.error('无法读取原件，请稍后重试')}}
async function onGenerate(){if(generating.value||uploading.value||activeTask.value)return;if(uploadState.value.blocked){ElMessage.warning('请先完成或移除待导入项，并确认清单已读取');return};generating.value=true;const selectedPolicy=capturedFormPolicyToken(lastTask.value);try{if(!generateKey)generateKey=createRequestId();await load(true);if(pageError.value)throw new Error('未能核对最新材料，请重新加载后再开始。');validateFormPolicyRefresh(selectedPolicy,lastTask.value);if(!lastTask.value){await loadReadiness();if(!readiness.value?.ready)throw new Error('工作站处理组件尚未就绪，请联系管理员。')}const consent=lastTask.value&&!taskNeedsCloudConsent(lastTask.value)?{cloud_consent:false,expected_processing_mode:processingMode.value}:cloudConsentPayload();const {data}=lastTask.value?await client.post('/tasks/'+lastTask.value.id+'/resume',{...consent,form_policy_token:selectedPolicy}):await client.post('/cases/'+caseId+'/generate',{order_mode:orderMode.value,idempotency_key:generateKey,...consent});resetCloudConsent();goTask(data.id)}catch(e:any){ElMessage.error(e.response?.data?.detail||e.message||'归档任务未能启动，材料仍保留在案件中')}finally{generating.value=false}}
function goTask(id:number){router.push('/cases/'+caseId+'/tasks/'+id)}
function performCaseAction(){if(openExistingTask.value)goTask(detail.value.last_task_id);else onGenerate()}
function beforeUploadLeave(event:BeforeUnloadEvent){if(uploadState.value.navigationDirty){event.preventDefault();event.returnValue=''}}
onBeforeRouteLeave(async()=>{if(!uploadState.value.navigationDirty)return true;try{await ElMessageBox.confirm('材料正在上传或尚未登记。离开会中断，尚未登记项仅在本页。','离开案件？',{confirmButtonText:'离开',cancelButtonText:'继续导入'});return true}catch{return false}})
onMounted(()=>{load();loadCapabilities();loadReadiness();globalThis.window?.addEventListener('beforeunload',beforeUploadLeave)})
onUnmounted(()=>globalThis.window?.removeEventListener('beforeunload',beforeUploadLeave))
</script>
<style scoped>
.case-heading-actions{display:flex;align-items:center;gap:14px}
.case-workspace{max-width:1280px;margin:auto;}.case-columns{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:26px;align-items:start;}.material-panel{padding:24px;}.import-zone{border:1px dashed #d2d2d7;border-radius:8px;background:#fafafa;text-align:center;padding:30px 16px;color:#6e6e73;}.import-zone.dragging{background:#f5f5f7;border-color:#6e6e73;}.import-zone>.el-icon{font-size:25px;color:#6e6e73;}.import-zone p{color:#424245;font-size:14px;margin:12px 0 7px;}.import-zone span{font-size:12px;}.import-zone button{border:0;background:none;color:#424245;padding:0 3px;cursor:pointer;}.import-zone small{display:block;font-size:10px;margin-top:17px;color:#6e6e73;}
.file-row{display:flex;align-items:flex-start;gap:12px;padding:21px 0;border-bottom:1px solid #f5f5f7;}.file-row:last-child{border-bottom:0;}.file-icon{font-size:22px;color:#6e6e73;padding-top:2px;}.file-body{flex:1;min-width:0;}.filename{display:block;border:0;padding:0;text-align:left;background:none;font-size:13px;color:#424245;cursor:pointer;word-break:break-all;}.filename:hover{text-decoration:underline;}.file-metadata{font-size:10px;color:#6e6e73;margin-top:7px;}.doc-type-select{margin-top:10px;width:min(100%,320px);}.doc-type-select :deep(.el-select__wrapper){box-shadow:none;background:#f5f5f7;min-height:26px;}.empty-files{text-align:center;padding:25px 0 10px;}.material-tips{padding:22px 6px;color:#6e6e73;font-size:12px;line-height:1.9;}.material-tips h3{font-weight:500;font-size:12px;color:#6e6e73;}.material-tips a{color:#424245;}.resume-task{display:flex;align-items:center;justify-content:space-between;gap:15px;background:#f5f5f7;border:1px solid #e5e5ea;border-radius:8px;padding:18px 22px;margin-bottom:22px;}.resume-task strong{font-weight:500;font-size:13px;}.resume-task p{font-size:12px;color:#6e6e73;margin:7px 0 0;}.completed-tasks{padding:16px 6px;border-top:1px solid #e5e5ea;}.completed-task{margin-top:15px;}.upload-progress{margin-top:15px;}.import-error{font-size:12px;word-break:break-word;line-height:1.7;}
@media(max-width:1050px){.case-columns{grid-template-columns:1fr}.case-action-panel{display:grid;grid-template-columns:1fr 1fr;gap:22px;}}@media(max-width:650px){.case-action-panel{display:block;}.resume-task{align-items:flex-start;flex-direction:column;}}
</style>
<style scoped>.material-classification{margin-top:14px;font-size:11px;color:#6e6e73}.material-classification summary{cursor:pointer}.material-classification p{font-size:11px}</style>
