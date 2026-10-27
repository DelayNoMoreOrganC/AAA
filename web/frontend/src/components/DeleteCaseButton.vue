<template>
  <span class="delete-case-control" :data-case-id="caseRecord.id" @click.stop>
    <el-tooltip :content="blockedReason" :disabled="!blockedReason" placement="top">
      <span class="delete-case-trigger" :title="blockedReason" :tabindex="blockedReason?0:undefined" :aria-label="blockedReason||undefined">
        <el-button text class="delete-case-button" data-testid="delete-case" :disabled="!!blockedReason||state.pending" :aria-label="'删除案件：'+caseRecord.title" @click.stop="open">删除</el-button>
      </span>
    </el-tooltip>
    <el-dialog :model-value="state.opened" data-testid="delete-case-dialog" title="删除案件" width="min(480px, 92vw)" append-to-body :close-on-click-modal="!state.pending" :close-on-press-escape="!state.pending" :show-close="!state.pending" @update:model-value="value=>{if(!value)cancel()}">
      <p class="delete-case-name">确认删除「{{ state.selected?.title }}」？</p>
      <p class="delete-case-description">将删除本案在工作站中的导入副本、分析与核对记录、网页归档成果，删除后不能在这里恢复。</p>
      <p class="delete-case-description">外部原始来源文件和指定保存目录中已保存的成果副本会保留。</p>
      <el-alert v-if="state.error" :title="state.error" type="error" :closable="false" role="alert" />
      <template #footer><el-button data-testid="cancel-delete-case" :disabled="state.pending" @click="cancel">保留案件</el-button><el-button data-testid="confirm-delete-case" type="danger" :loading="state.pending" :disabled="!!blockedReason" @click="confirm">确认删除</el-button></template>
    </el-dialog>
  </span>
</template>
<script setup lang="ts">
import { computed, ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import client from '../api/client'
import { CASES_CHANGED_EVENT,caseDeletionBlocked,createCaseDeletion } from '../domain/caseDeletion.js'
const props=defineProps<{caseRecord:any,disabled?:boolean}>()
const emit=defineEmits<{deleted:[result:{caseId:string,caseTitle:string,cleanupPending:boolean,message:string}]}>()
const state=ref<any>({opened:false,pending:false,error:'',selected:null})
const blockedReason=computed(()=>caseDeletionBlocked(props.caseRecord,props.disabled))
const deletion=createCaseDeletion({
  remove:(id:string)=>client.delete('/cases/'+encodeURIComponent(id)),
  onChange:(value:any)=>{state.value=value},
  onDeleted:(result:any)=>{
    if(result.cleanupPending)ElMessage.warning({message:result.message,duration:8000,showClose:true})
    else ElMessage.success(result.message)
    window.dispatchEvent(new CustomEvent(CASES_CHANGED_EVENT,{detail:{action:'deleted',...result}}))
    emit('deleted',result)
  },
})
function open(){deletion.open(props.caseRecord,props.disabled)}
function cancel(){deletion.cancel()}
function confirm(){deletion.confirm(props.caseRecord,props.disabled)}
onBeforeUnmount(()=>deletion.dispose())
</script>
<style scoped>
.delete-case-control,.delete-case-trigger{display:inline-flex;align-items:center}.delete-case-button{--el-button-text-color:#8e8179;--el-button-hover-text-color:#a75d50;--el-button-hover-bg-color:#faf0eb;font-size:12px}.delete-case-name{font-size:15px;line-height:1.9;color:#4d5a50;overflow-wrap:anywhere}.delete-case-description{font-size:12px;line-height:1.9;color:#859080;margin:12px 0 18px}
</style>
