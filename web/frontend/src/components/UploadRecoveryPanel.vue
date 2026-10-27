<template>
  <section v-if="!state.busy&&(state.rows.length||state.error||state.matchMessages.length||state.items.some(item=>item.status==='unavailable'))" class="upload-recovery" data-testid="upload-recovery" aria-live="polite">
    <strong v-if="state.rows.length">还有 {{ state.rows.length }} 份材料待导入</strong>
    <p v-if="state.rows.some(item=>!item.file)">重新选择原文件或原文件夹，我会核对内容，只补传未完成项。</p>
    <p v-if="state.error" role="alert">{{ state.error }} <el-button text data-testid="upload-reload" :disabled="disabled||state.busy||state.loading" @click="$emit('reload')">重新读取清单</el-button></p>
    <p v-for="item in state.rows" :key="item.request_id">{{ item.filename }}：{{ item.message||(item.local?'尚未登记，仅保留在本页':item.file?'可继续导入':'待重新选择原文件') }} <el-button text :data-testid="dismissTestId" :disabled="disabled||state.busy" @click="$emit('remove',item.request_id)">移除待导入项</el-button></p>
    <p v-for="(message,index) in state.matchMessages" :key="index">{{ message }}</p>
    <p v-for="item in state.items.filter(item=>item.status==='unavailable')" :key="'unavailable-'+item.request_id" data-testid="upload-unavailable">{{ item.filename }}：此前导入项现已移除、变更或无法核验，请检查案件材料列表。不会按原编号重新导入。</p>
    <div class="upload-actions" v-if="state.rows.length"><el-button data-testid="upload-reselect-files" :disabled="disabled||state.busy||state.loading||!!state.error" @click="files?.click()">重选原文件</el-button><el-button data-testid="upload-reselect-folder" :disabled="disabled||state.busy||state.loading||!!state.error" @click="folder?.click()">重选原文件夹</el-button><el-button v-if="state.canRetry" :data-testid="retryTestId" :disabled="disabled||state.busy||state.loading||!!state.error" @click="$emit('retry')">仅重试未导入材料</el-button></div>
    <p v-if="state.rows.length" class="upload-footnote">移除仅取消待上传项，不删除已导入资料；之后由你决定是否继续整理。</p>
    <input ref="files" data-testid="upload-recovery-files" type="file" multiple hidden @change="selected" /><input ref="folder" data-testid="upload-recovery-folder" type="file" multiple webkitdirectory hidden @change="selected" />
  </section>
</template>
<script setup lang="ts">
import {ref} from 'vue'
defineProps<{state:any,disabled?:boolean,dismissTestId?:string,retryTestId?:string}>()
const emit=defineEmits<{reload:[],remove:[id:string],retry:[],recover:[files:File[]]}>()
const files=ref<HTMLInputElement|null>(null),folder=ref<HTMLInputElement|null>(null)
defineExpose({selectFiles:()=>files.value?.click()})
function selected(event:Event){const input=event.target as HTMLInputElement;const values=Array.from(input.files||[]);input.value='';if(values.length)emit('recover',values)}
</script>
<style scoped>
.upload-recovery{margin:14px 0;padding:14px 18px;border:1px solid #e7dec9;border-radius:10px;background:#fffdf7;color:#84765b;font-size:12px;line-height:1.8}.upload-recovery p{overflow-wrap:anywhere;margin:8px 0}.upload-recovery strong{font-weight:500}.upload-actions{display:flex;flex-wrap:wrap;gap:8px}.upload-actions .el-button{margin:0}.upload-footnote{font-size:11px;color:#99917e}
</style>
