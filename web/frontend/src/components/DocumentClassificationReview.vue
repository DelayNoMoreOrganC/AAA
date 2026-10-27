<template>
  <details ref="detailsElement" class="document-review" @toggle="onToggle">
    <summary>按文书核对 <span>查看整卷中的文书归属</span></summary>
    <p class="muted">按已识别的一整份文书调整归属。来源页范围保持不变，原文可随时打开核对。</p>
    <div class="document-toolbar"><span v-if="state.revision" class="muted">修订 {{ state.revision }} · {{ state.documents.length }} 份文书</span><el-button text :loading="state.loading" :disabled="state.saving" @click="refresh">刷新文书清单</el-button></div>
    <el-alert v-if="state.stale" title="任务有新的修订，请刷新文书清单后继续核对。" type="warning" :closable="false" />
    <el-alert v-if="state.error" :title="state.error" type="warning" :closable="false" />
    <el-alert v-if="state.message" :title="state.message" type="success" :closable="false" />
    <p v-if="locateMessage" class="muted" role="status">{{ locateMessage }}</p>
    <p v-if="!state.editable && state.revision" class="muted">{{ state.blocked_reason || '当前任务仅可查看，待处理完成后再调整。' }}</p>
    <p v-if="unsaved" class="draft-notice">当前表格或待处理事项有未保存修改。<el-button text :disabled="disabled || state.saving" @click="$emit('save-review')">先保存核对草稿</el-button>保存后刷新此清单，再保存文书分类。</p>
    <div v-loading="state.loading">
      <p v-if="state.revision && !state.documents.length" class="muted">尚无可核对的文书，请先完成材料识别。</p>
      <section v-for="group in groups" :key="group.key" :class="{'evidence-bundle':group.bundle}">
        <button v-if="group.bundle" class="bundle-toggle" :aria-expanded="!!expandedGroups[group.key]" @click="expandedGroups[group.key]=!expandedGroups[group.key]">
          <strong>证据清单及附件</strong><span>第 {{ group.page_start }}—{{ group.page_end }} 页<span v-if="group.pending"> · {{ group.pending }} 处待定</span> · {{ expandedGroups[group.key]?'收起':'展开' }}</span>
        </button>
      <article v-for="document in group.documents" v-show="!group.bundle || expandedGroups[group.key]" :key="document.unit_key" :ref="el=>setRowRef(document.unit_key,el)" class="document-row" :class="{'located-document':locatedKey===document.unit_key}" tabindex="-1">
        <div class="document-title"><strong>{{ document.title || document.filename }}</strong><el-tag size="small" type="info" effect="plain">{{ document.classification_origin==='human'?'已确认':document.match_tier==='confirmed'?'已自动匹配':document.match_tier==='suggested'?'已建议归入':'待定' }}</el-tag></div>
        <p class="muted">第 {{ document.page_start }}<template v-if="document.page_end!==document.page_start">—{{ document.page_end }}</template> 页 · {{ document.catalog_name || document.doc_type }}<span v-if="document.catalog_seq">（目录 {{ document.catalog_seq }}）</span></p>
        <p v-if="document.classification_origin==='human' && document.reason" class="document-reason">核对原因：{{ document.reason }}</p>
        <div class="document-actions"><el-button text :disabled="!document.file_id || !document.page_start" @click="$emit('source',{file_id:document.file_id,filename:document.filename,page:document.page_start})">打开文书首页</el-button><el-button v-if="state.draft?.unit_key!==document.unit_key" text :disabled="cannotEdit || !!state.draft" @click="review.select(document.unit_key)">调整归属</el-button></div>
        <div v-if="state.draft?.unit_key===document.unit_key" class="classification-form">
          <div class="document-actions" aria-label="建议归档位置"><el-button v-for="option in document.suggestions||[]" :key="classificationTargetKey(option)" :disabled="cannotEdit" @click="review.updateDraft({target:classificationTargetKey(option),reason:option.reason})">{{ option.label }}</el-button></div>
          <label :for="'classification-target-'+document.unit_key">归入目录</label>
          <el-select :id="'classification-target-'+document.unit_key" :model-value="state.draft.target" :disabled="cannotEdit" style="width:100%" placeholder="选择本案允许的文书分类" @update:model-value="value=>review.updateDraft({target:value})"><el-option v-if="!state.options.some(option => classificationTargetKey(option) === state.draft.target)" :value="state.draft.target" :label="'待定（暂存目录 ' + document.catalog_seq + '）'" disabled /><el-option v-for="option in state.options" :key="classificationTargetKey(option)" :value="classificationTargetKey(option)" :label="option.label" /></el-select>
          <label :for="'classification-reason-'+document.unit_key">核对原因</label>
          <el-input :id="'classification-reason-'+document.unit_key" :model-value="state.draft.reason" :disabled="state.saving" type="textarea" :rows="2" maxlength="1000" show-word-limit placeholder="例如：对照原文第 4—6 页，确认是证据材料" @update:model-value="value=>review.updateDraft({reason:value})" />
          <div class="document-actions"><el-button type="primary" plain :loading="state.saving" :disabled="cannotEdit || unsaved || !state.draft.reason.trim()" @click="review.save()">保存分类草稿</el-button><el-button text :disabled="state.saving" @click="review.cancel()">取消调整</el-button></div>
          <p class="muted">保存后原最终确认失效；历史成果保留，核对后需要再次最终确认。</p>
        </div>
      </article>
      </section>
    </div>
  </details>
</template>
<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import client from '../api/client'
import { evidenceGroups } from '../domain/evidenceGroups.js'
import { classificationTargetKey, createDocumentClassification, documentClassificationDirty, locateDocumentUnit } from '../domain/documentClassification.js'
const props=defineProps<{taskId:string,revision:number,disabled:boolean,unsaved:boolean,beforeWrite:(revision:number)=>Promise<string>|string}>()
const emit=defineEmits(['source','saved','busy','dirty','save-review'])
const state=ref<any>({documents:[],options:[],draft:null,loading:false,saving:false,error:'',message:'',revision:null})
const detailsElement=ref<HTMLDetailsElement|null>(null),locatedKey=ref(''),locateMessage=ref('')
const rowElements=new Map<string,HTMLElement>()
const expandedGroups=ref<Record<string,boolean>>({})
const groups=computed(()=>evidenceGroups(state.value.documents))
let refreshRequest:Promise<void>|null=null
const review=createDocumentClassification({
  read:async(id:string,signal:AbortSignal)=>(await client.get('/tasks/'+id+'/documents',{signal})).data,
  write:async(id:string,key:string,body:any,signal:AbortSignal)=>(await client.patch('/tasks/'+id+'/documents/'+encodeURIComponent(key)+'/classification',body,{signal})).data,
  beforeWrite:props.beforeWrite,
  onSaved:(task:any)=>emit('saved',task),
  onChange:(value:any)=>{state.value=value;emit('busy',value.saving);emit('dirty',documentClassificationDirty(value))},
})
const cannotEdit=computed(()=>props.disabled||state.value.loading||state.value.saving||state.value.stale||!state.value.editable||state.value.source_changed)
async function refresh(){
  if(refreshRequest)return refreshRequest
  refreshRequest=(async()=>{await review.load();review.invalidate(props.revision)})()
  try{await refreshRequest}finally{refreshRequest=null}
}
function setRowRef(key:string,element:any){if(element)rowElements.set(key,element);else rowElements.delete(key)}
async function reveal(source:any){
  if(detailsElement.value)detailsElement.value.open=true
  await refresh()
  const document=locateDocumentUnit(state.value.documents,source)
  locatedKey.value=document?.unit_key||''
  const group=groups.value.find(group=>group.documents.some(row=>row.unit_key===locatedKey.value))
  if(group?.bundle)expandedGroups.value[group.key]=true
  locateMessage.value=document?'已定位对应文书，请结合原文核对。已有分类草稿会保留。':'未找到唯一对应的文书，请按来源文件和页范围核对下方清单。'
  await nextTick()
  const element=rowElements.get(locatedKey.value)
  if(element){element.scrollIntoView({block:'nearest'});element.focus({preventScroll:true})}
}
defineExpose({reveal})
function onToggle(event:Event){if((event.target as HTMLDetailsElement).open && state.value.revision===null)refresh()}
watch(()=>props.taskId,id=>{review.reset(id);expandedGroups.value={}},{immediate:true})
watch(()=>props.revision,revision=>review.invalidate(revision))
onUnmounted(()=>{review.dispose();emit('busy',false);emit('dirty',false)})
</script>
<style scoped>
.evidence-bundle{border:1px solid #e9ede2;border-radius:12px;margin:12px 0;padding:0 14px}.bundle-toggle{width:100%;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 0;border:0;background:transparent;text-align:left;color:inherit;cursor:pointer}.bundle-toggle strong{font-size:13px;font-weight:500}.bundle-toggle span{font-size:12px;color:#667a5e}.bundle-toggle:focus-visible{outline:2px solid #a1b391;outline-offset:3px}
.document-review{margin-top:24px;border-top:1px solid #e4e8dc;padding:18px 0;font-size:12px;color:#667a5e}.document-review>summary{cursor:pointer;font-size:13px}.document-review>summary>span{font-size:11px;color:#929e85;margin-left:10px}.document-toolbar,.document-title,.document-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.document-toolbar{justify-content:space-between}.document-review .el-alert{margin:10px 0}.document-row{border-bottom:1px solid #e9ede2;padding:18px 0}.document-title strong{font-size:13px;font-weight:500;overflow-wrap:anywhere}.document-reason{line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere}.document-actions>.el-button{margin-left:0}.classification-form{padding:14px;background:#f6f8f1;border-radius:5px;margin-top:10px}.classification-form>label{display:block;margin:8px 0;color:#62745a}.classification-form>.document-actions{margin-top:14px}.draft-notice{font-size:12px;line-height:1.8;color:#95805c}.muted{font-size:12px;color:#929e85;line-height:1.8}
.located-document{background:#f5f8ef;box-shadow:inset 3px 0 #a1b391;padding-left:12px;padding-right:12px;outline:none}.document-row:focus-visible{outline:2px solid #a1b391;outline-offset:2px}
.classification-form .document-actions>.el-button{max-width:100%;height:auto;min-height:32px;white-space:normal;text-align:left;padding:8px 12px}.classification-form .document-actions :deep(.el-button>span){white-space:normal;overflow-wrap:anywhere}
</style>
