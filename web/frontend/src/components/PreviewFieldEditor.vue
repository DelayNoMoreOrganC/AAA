<template>
  <section class="original-template-review" data-testid="original-template-review">
    <header class="template-toolbar"><div><strong>{{ templateName }}</strong><span>{{ !loaded?'正在读取填写内容':readOnly?'只读预览':hasUnsavedChanges()?'有未保存修改':'已保存填写内容' }}</span></div><div class="template-actions"><el-button data-testid="toggle-template-fields" text @click="fieldsOpen=!fieldsOpen">{{ fieldsOpen?'收起填写内容':readOnly?'查看填写内容':'修改填写内容' }}</el-button><el-button data-testid="refresh-template-pdf" text :disabled="pdfLoading||saving||disabled" @click="refreshPdf">刷新原表</el-button></div></header>
    <p class="template-caption">预览由原始 Word 模板填写后生成，固定文字、表格和版式保留在原表中。</p>
    <p v-if="hasUnsavedChanges()" class="template-pending" role="status">预览显示已保存版本，尚未包含右侧未保存修改。</p>
    <p v-if="revisionChanged&&hasUnsavedChanges()" class="template-pending">其他填写内容已有更新。你的修改仍保留，保存时会核对是否冲突。</p>
    <div class="template-workspace" :class="{'with-fields':fieldsOpen}">
      <div class="template-paper" :aria-busy="pdfLoading">
        <p v-if="pdfLoading" class="template-state" role="status">正在用原表生成预览…</p>
        <div v-else-if="pdfError" class="template-state template-error" role="alert" data-testid="template-pdf-error"><p>{{ pdfError }}</p><el-button :disabled="disabled||saving" @click="refreshPdf">重试预览</el-button><p>未用网页重画表格替代原表。</p></div>
        <div v-else-if="pdfUrl" class="original-pages"><img :src="pdfUrl" class="original-pdf" data-testid="original-template-pdf" :alt="templateName+' · 第 '+pdfPage+' 页'" @error="pdfError='原表图像未能显示，请重试预览。'" /><nav v-if="pdfPages>1" class="page-controls" aria-label="原表翻页"><el-button :disabled="pdfPage<=1||pdfLoading" @click="refreshPdf(undefined,pdfPage-1)">上一页</el-button><span>{{pdfPage}} / {{pdfPages}}</span><el-button :disabled="pdfPage>=pdfPages||pdfLoading" @click="refreshPdf(undefined,pdfPage+1)">下一页</el-button></nav></div>
        <p v-else class="template-state">打开表格后加载原表预览。</p>
      </div>
      <aside v-show="fieldsOpen" class="template-fields" data-testid="template-fields">
        <p class="fields-note">仅修改原表允许填写的内容。清空输入会保存为空白。</p><p v-if="loading" class="template-state">正在读取填写内容…</p>
        <p v-if="fieldError" class="template-error" role="alert" data-testid="template-field-error">{{ fieldError }}</p>
        <div v-for="conflict in conflicts" :key="conflict.key" class="field-conflict" data-testid="template-field-conflict"><strong>{{ conflict.key }}</strong><p>当前已保存：{{ conflict.current || '空白' }}</p><p>本页输入：{{ fields.find(field=>field.key===conflict.key)?.value || '空白' }}</p><el-button text :disabled="disabled||saving||readOnly||!conflict.present" @click="resolveConflict(conflict.key,false)">采用已保存值</el-button><el-button text :disabled="disabled||saving||readOnly||!conflict.present" @click="resolveConflict(conflict.key,true)">保留我的输入，稍后保存</el-button></div>
        <div v-for="field in fields" :key="field.key" class="template-field" :data-focused="focusedField===field.key" :data-field="field.key"><label :for="fieldId(field.key)">{{ field.label }}</label><el-input :ref="element=>{if(element)fieldInputs[field.key]=element}" :id="fieldId(field.key)" :data-field="field.key" :model-value="field.value" :disabled="readOnly||disabled||saving||loading" :type="field.multiline?'textarea':'text'" :rows="field.multiline?3:undefined" :aria-label="field.label" @update:model-value="value=>updateValue(field.key,String(value))" /><p class="field-assurance" data-testid="template-field-assurance" :data-field="field.key" :data-status="field.value!==baseline[field.key]?'unsaved':field.assurance.status">{{ field.value!==baseline[field.key]?'未保存修改，尚未核验':field.assurance.label }}<span v-if="field.value===baseline[field.key]&&field.assurance.source_count"> · {{ field.assurance.source_count }} 处原文</span></p><el-button class="field-source" data-testid="template-field-source" :data-field="field.key" text @click="$emit('source',field.key)">查看来源</el-button><p v-if="field.display_value&&field.value===baseline[field.key]" class="field-assurance" data-testid="template-field-display">表内显示：{{ field.display_value }}<br />{{ field.display_note }}</p></div>
        <p v-if="loaded&&!fields.length" class="fields-note">此表没有可编辑字段，固定内容请查看左侧原表。</p>
        <div v-if="!readOnly" class="fields-save"><el-button data-testid="save-template-fields" type="primary" :loading="saving" :disabled="disabled||loading||!loaded||!hasUnsavedChanges()" @click="saveFromEditor">保存并刷新原表</el-button><p v-if="saveMessage" role="status">{{ saveMessage }}</p></div>
      </aside>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref,watch,nextTick,onUnmounted } from 'vue'
import client from '../api/client'
import { normalizeTemplateFields,templateValues,changedTemplateValues,conflictingTemplateFields,templateRequestError,templatePageMetadata } from '../domain/templateFields.js'
const props=defineProps<{taskId:string,templateName:string,active:boolean,revision?:number,sourceVersion?:string,readOnly?:boolean,disabled?:boolean,outputReady?:boolean,outputVersion?:string,caseType?:string,focusField?:string}>()
const emit=defineEmits<{saved:[task:any],busy:[value:boolean],source:[field:string]}>()
const conflicts=ref<any[]>([])
const fields=ref<any[]>([]),fieldsOpen=ref(false),loading=ref(false),loaded=ref(false),saving=ref(false),fieldError=ref(''),saveMessage=ref('')
const pdfPage=ref(1),pdfPages=ref(1)
const pdfUrl=ref(''),pdfLoading=ref(false),pdfError=ref(''),revisionChanged=ref(false)
const focusedField=ref(''),fieldInputs=ref<Record<string,any>>({})
let baseline:Record<string,string>={},styles:any={},customValues:any={},loadedRevision:number|null=null,generation=0,pdfRequest=0,disposed=false,lastScope='',controller:AbortController|null=null,pdfController:AbortController|null=null,saveController:AbortController|null=null
function hasUnsavedChanges(){return loaded.value&&Object.keys(changedTemplateValues(fields.value,baseline)).length>0}
function isLoaded(){return loaded.value}
function fieldId(key:string){return 'template-'+props.taskId+'-'+props.templateName+'-'+key}
function fieldKeys(){return fields.value.map(field=>field.key)}
async function revealField(key:string){if(!key)return false;if(!loaded.value)await loadPreview(true);if(!fields.value.some(item=>item.key===key))return false;fieldsOpen.value=true;focusedField.value=key;await nextTick();fieldInputs.value[key]?.focus?.();fieldInputs.value[key]?.$el?.scrollIntoView?.({block:'nearest'});return true}
function updateValue(key:string,value:string){if(props.readOnly||props.disabled||saving.value||loading.value)return;const field=fields.value.find(item=>item.key===key);if(field){field.value=value;saveMessage.value=''}}
function path(kind:string){return '/tasks/'+encodeURIComponent(props.taskId)+'/'+kind+'/'+encodeURIComponent(props.templateName)}
function clearPdf(){if(pdfUrl.value)URL.revokeObjectURL(pdfUrl.value);pdfUrl.value=''}
async function refreshPdf(revision?:number,page=1){
  if(!props.active||disposed)return
  const expected=typeof revision==='number'?revision:props.revision??loadedRevision
  const scope=generation,request=++pdfRequest;pdfController?.abort();pdfController=new AbortController();clearPdf();pdfLoading.value=true;pdfError.value=''
  try{
    const response=await client.get(path('preview')+'?page='+page,{responseType:'blob',signal:pdfController.signal})
    if(disposed||scope!==generation||request!==pdfRequest)return
    const meta=templatePageMetadata(response.headers)
    if(!meta.original)throw new Error('工作站尚未确认此预览来自原始模板，请更新原表组件后重试。')
    if(!meta.image||meta.page!==page||!meta.pages||!response.data?.size)throw new Error('没有取得有效的原表页面，请重试。')
    if(expected!=null&&meta.revision!==expected)throw new Error('填写内容版本已变化，请刷新原表后再核对。')
    pdfPage.value=page;pdfPages.value=meta.pages;pdfUrl.value=URL.createObjectURL(response.data)
  }catch(error:any){const message=await templateRequestError(error,'原表预览生成失败，请重试。');if(scope===generation&&request===pdfRequest&&!disposed)pdfError.value=message}
  finally{if(scope===generation&&request===pdfRequest&&!disposed)pdfLoading.value=false}
}
async function loadPreview(force=false){
  if((!props.active&&!force)||loading.value||disposed||hasUnsavedChanges())return
  const scope=generation;controller?.abort();controller=new AbortController();loading.value=true;fieldError.value=''
  try{
    const {data}=await client.get(path('preview-fields'),{signal:controller.signal})
    if(scope!==generation||disposed)return
    fields.value=normalizeTemplateFields(data.fields);baseline=templateValues(fields.value);styles=data.styles||{};customValues=data.custom_values||{};loadedRevision=Number.isInteger(data.revision)?data.revision:props.revision??null;loaded.value=true;revisionChanged.value=false
    await refreshPdf(loadedRevision??undefined)
  }catch(error:any){const message=await templateRequestError(error,'无法读取表格填写内容，请重试。');if(scope===generation&&!disposed)fieldError.value=message}
  finally{if(scope===generation&&!disposed)loading.value=false}
}
async function saveChanges():Promise<boolean>{
  if(!loaded.value||saving.value||props.readOnly||disposed)return false
  if(!hasUnsavedChanges())return true
  const scope=generation;const submitted=templateValues(fields.value),changes=changedTemplateValues(fields.value,baseline)
  saving.value=true;emit('busy',true);fieldError.value='';saveMessage.value='';conflicts.value=[];saveController=new AbortController()
  try{
    // A cached second form must not overwrite fields changed by the first form.
    const {data:current}=await client.get(path('preview-fields'),{signal:saveController.signal})
    if(scope!==generation||disposed)return false
    if(props.readOnly||current.source_changed===true)throw new Error('材料或任务状态已变化，当前表格不可修改。输入已保留。')
    const changedElsewhere=conflictingTemplateFields(changes,baseline,current.fields)
    if(changedElsewhere.length){const latest=templateValues(normalizeTemplateFields(current.fields));conflicts.value=changedElsewhere.map(key=>({key,current:latest[key]??'',present:key in latest}));throw new Error('部分字段已在其他位置修改。本页输入已保留，请核对下方差异。')}
    const revision=Number.isInteger(current.revision)?current.revision:null
    if(revision===null)throw new Error('工作站尚未提供表格版本校验，已保留修改，请更新服务后再保存。')
    const {data}=await client.put(path('preview-fields'),{values:changes,styles:current.styles??styles,custom_values:current.custom_values??customValues,expected_revision:revision},{signal:saveController.signal})
    if(scope!==generation||disposed)return false
    if(String(data?.id)!==props.taskId||!Number.isInteger(data.revision)||data.revision<=revision)throw new Error('未取得保存后的表格版本，输入仍保留，请刷新核对。')
    baseline=submitted;loadedRevision=data.revision;revisionChanged.value=false;saveMessage.value='填写内容已保存，档案草稿需更新后下载。';emit('saved',data)
    clearPdf();await loadPreview(true)
    return true
  }catch(error:any){const message=await templateRequestError(error,'保存失败，输入仍保留，请重试。');if(scope===generation&&!disposed)fieldError.value=message;return false}
  finally{if(scope===generation&&!disposed){saving.value=false;emit('busy',false)}}
}
async function saveFromEditor(){if(!props.disabled)await saveChanges()}
function resolveConflict(key:string,keepMine:boolean){if(saving.value||props.readOnly||props.disabled)return;const item=conflicts.value.find(item=>item.key===key);if(!item||!item.present)return;baseline[key]=item.current;if(!keepMine){const field=fields.value.find(field=>field.key===key);if(field)field.value=item.current}conflicts.value=conflicts.value.filter(item=>item.key!==key);if(!conflicts.value.length)fieldError.value=''} 
function reset(){conflicts.value=[];generation++;pdfRequest++;controller?.abort();pdfController?.abort();saveController?.abort();clearPdf();fields.value=[];baseline={};loaded.value=false;loading.value=false;saving.value=false;pdfLoading.value=false;fieldError.value='';pdfError.value='';saveMessage.value='';loadedRevision=null;revisionChanged.value=false;emit('busy',false)}
watch(()=>[props.taskId,props.templateName,props.active,props.revision,props.sourceVersion],()=>{
  const scope=props.taskId+':'+props.templateName
  if(scope!==lastScope){reset();lastScope=scope}
  if(!props.active)return
  if(saving.value)return
  if(loadedRevision!==null&&props.revision!==undefined&&props.revision!==loadedRevision){revisionChanged.value=true;if(hasUnsavedChanges())refreshPdf();else loadPreview()}
  else if(!loaded.value)loadPreview()
  else if(!pdfUrl.value&&!pdfLoading.value&&!pdfError.value)refreshPdf()
},{immediate:true})
onUnmounted(()=>{disposed=true;reset()})
watch(()=>[props.active,props.focusField,loaded.value],()=>{if(props.active&&props.focusField&&loaded.value)revealField(props.focusField)},{immediate:true})
defineExpose({saveChanges,loadPreview,isLoaded,hasUnsavedChanges,revealField,fieldKeys})
</script>
<style scoped>
.original-template-review{font-size:12px;color:#63745c}.template-toolbar{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:10px 0}.template-toolbar strong{font-size:14px;font-weight:500}.template-toolbar span{display:block;font-size:10px;color:#96a18b;margin-top:5px}.template-actions{display:flex;align-items:center;gap:4px}.template-caption,.template-pending{font-size:11px;line-height:1.8;color:#8c9980;margin:8px 0 14px}.template-pending{color:#a58a5d}.template-workspace{display:grid;grid-template-columns:1fr;gap:18px}.template-workspace.with-fields{grid-template-columns:minmax(0,1fr) 280px}.template-paper{background:#e8eae6;border:1px solid #dce2d4;min-height:65vh;border-radius:8px;overflow:hidden}.original-pages{max-height:72vh;overflow:auto}.original-pdf{display:block;width:100%;height:auto;border:0;background:white}.page-controls{display:flex;align-items:center;justify-content:center;gap:16px;position:sticky;bottom:0;background:#fff;padding:8px}.template-state{padding:38px 20px;text-align:center;font-size:12px;line-height:1.9;color:#8c9980}.template-error{color:#a57556;font-size:12px;line-height:1.9;overflow-wrap:anywhere}.template-fields{max-height:72vh;overflow:auto;padding:0 8px 16px 0}.fields-note{font-size:10px;line-height:1.8;color:#96a18b;margin:0 0 18px}.template-field{margin-bottom:14px}.template-field label{display:block;font-size:11px;margin-bottom:7px;color:#6c7f60}.field-source{font-size:10px;margin:3px 0;padding:3px 0;height:auto}.field-conflict{padding:12px;border:1px solid #e8d7bc;border-radius:6px;margin:12px 0;font-size:11px;line-height:1.8;overflow-wrap:anywhere}.field-conflict p{white-space:pre-wrap}.field-conflict .el-button{margin:4px 0;display:block;font-size:10px}.fields-save{position:sticky;bottom:0;background:#fff;padding:12px 0 3px;border-top:1px solid #e6ecdf}.fields-save>.el-button{width:100%}.fields-save p{font-size:10px;line-height:1.8;color:#819775;margin:8px 0 0}@media(max-width:850px){.template-workspace.with-fields{grid-template-columns:1fr}.template-fields{max-height:55vh}.original-pages{max-height:60vh}.template-toolbar{gap:10px}.template-actions{gap:0}}
</style>
<style scoped>
.field-assurance{font-size:10px;line-height:1.7;margin:6px 0 0;color:#8b9781}.field-assurance[data-status="conflict"],.field-assurance[data-status="unsaved"]{color:#a57556}
</style>




<style scoped>.template-field[data-focused="true"]{padding:10px;border-left:2px solid #7a9c83;background:#f3f7ef;border-radius:4px}</style>
