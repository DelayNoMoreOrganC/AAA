<template>
  <section v-if="isCloudProcessing(mode)" class="cloud-consent" aria-label="本案云端处理授权">
    <strong>{{ processingLabel(mode) }}</strong>
    <p>本次{{ cloudMaterialDescription(mode) }}将发送至{{ cloudProviderName(mode) }}云端。请确认这些材料可以使用云服务。</p>
    <el-checkbox :model-value="modelValue" :disabled="disabled" @update:model-value="value=>$emit('update:modelValue',value===true)">本案材料获准发送{{ cloudProviderName(mode) }}云端</el-checkbox>
    <small>授权仅适用于当前材料；补充或更换材料后需要重新确认。</small>
  </section>
</template>
<script setup lang="ts">
import { isCloudProcessing,processingLabel,cloudProviderName,cloudMaterialDescription } from '../domain/processingPrivacy.js'
defineProps<{mode:string,modelValue:boolean,disabled?:boolean}>()
defineEmits(['update:modelValue'])
</script>
<style scoped>
.cloud-consent{padding:15px;background:#fcf6e9;border:1px solid #eee0be;border-radius:6px;margin:16px 0;color:#8c7549;font-size:12px;line-height:1.8}.cloud-consent strong{font-weight:500}.cloud-consent p{margin:7px 0}.cloud-consent small{display:block;margin-top:6px;color:#9b8c71}.cloud-consent :deep(.el-checkbox){height:auto;white-space:normal;align-items:flex-start}.cloud-consent :deep(.el-checkbox__label){white-space:normal;line-height:1.6}.cloud-consent :deep(.el-checkbox__input){padding-top:3px}
</style>
