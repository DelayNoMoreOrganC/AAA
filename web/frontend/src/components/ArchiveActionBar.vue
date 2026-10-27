<template><footer class="archive-action-bar" aria-label="下一步"><details class="action-help"><summary>说明</summary><p>{{ action.hint }}</p></details><el-button data-testid="archive-primary-action" type="primary" size="large" :disabled="action.disabled" :loading="busy" @click="$emit('action',action.kind)">{{ action.label }}<el-icon v-if="!action.disabled&&!busy" style="margin-left:10px"><ArrowRight /></el-icon></el-button></footer></template>
<script setup lang="ts">
import { ArrowRight } from '@element-plus/icons-vue'
defineProps<{action:any,busy?:boolean}>()
defineEmits(['action'])
</script>
<style scoped>
.archive-action-bar{position:sticky;bottom:16px;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:20px;padding:15px 20px;margin-top:26px;border:1px solid #e5e5ea;border-radius:10px;background:rgba(255,255,252,.97);box-shadow:0 5px 24px #1d1d1f0c;backdrop-filter:blur(10px)}.action-eyebrow{font-size:10px;color:#6e6e73}.archive-action-bar p{margin:5px 0 0;font-size:12px;line-height:1.8;color:#6e6e73}.archive-action-bar .el-button{flex:none;min-width:180px}@media(max-width:650px){.archive-action-bar{bottom:8px;padding:12px;align-items:stretch;flex-direction:column;gap:10px}.archive-action-bar .el-button{width:100%}.archive-action-bar p{font-size:11px}}
</style>
