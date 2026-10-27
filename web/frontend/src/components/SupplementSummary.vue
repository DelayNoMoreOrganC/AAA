<template>
  <section v-if="hasContent" class="supplement-summary" data-testid="supplement-summary">
    <details ref="disclosure" data-testid="material-checklist-disclosure" class="supplement-disclosure"><summary class="supplement-toggle">补充与核对<span v-if="state.required.length">{{ state.required.length }} 项必要材料</span><span v-if="issueCount">{{ issueCount }} 项疑问</span></summary>
    <div class="supplement-heading"><div><strong>{{ state.required.length?'必要材料待补齐或核验':'材料清单' }}</strong><p v-if="hasArchive">草稿可以先下载。</p></div><el-button v-if="state.required.length||state.applicability.length||state.optional.length" text :disabled="disabled" @click="$emit('upload')">补充材料</el-button></div>
    <details v-if="state.required.length" data-testid="material-supplement-list"><summary>{{ state.required.length }} 项材料</summary><div v-for="item in state.required" :key="item.id" class="supplement-item" data-testid="material-supplement-item"><div class="material-heading"><span>{{ materialDisplayName(item) }}</span><small>{{ materialRequirement(item) }}</small></div><p>{{ item.message }}</p><el-button v-for="source in item.related_sources||[]" :key="source.file_id+':'+source.page" text class="source-link" data-testid="material-source" @click="$emit('source',source)">{{ materialSourceLabel(source) }}</el-button></div><p class="supplement-note">以上是尚未识别或无法核实的文书，不因占有目录位置而消除缺项。规则尚未核验的项目，不能据此认定为现行法定必需。</p></details>
    <details v-if="state.applicability.length" data-testid="applicability-materials"><summary>{{ state.applicability.length }} 项适用性待核验</summary><p class="supplement-note">尚不能认定本案必须补交，也不表示可省略。</p><div v-for="item in state.applicability" :key="item.id" class="supplement-item"><div class="material-heading"><span>{{ materialDisplayName(item) }}</span></div><p>{{ item.message }}</p><el-button v-for="source in item.related_sources||[]" :key="source.file_id+':'+source.page" text class="source-link" data-testid="material-source" @click="$emit('source',source)">{{ materialSourceLabel(source) }}</el-button></div></details>
    <details v-if="state.optional.length" data-testid="optional-materials"><summary>{{ state.optional.length }} 项可选材料 · 不影响草稿</summary><p v-for="item in state.optional" :key="item.id">{{ item.name }} · {{ item.message }}</p></details>
    <details v-if="state.unknown.length" data-testid="unclassified-materials"><summary>{{ state.unknown.length }} 段材料尚待明确类别，原页已保留</summary><p class="supplement-note">暂归入证据目录，不代表已经确认属于证据或证据齐备。</p><el-button v-for="source in state.unknown" :key="source.file_id+':'+source.page" text class="source-link" @click="$emit('source',source)">{{ materialSourceLabel(source) }}</el-button></details>
    <p v-if="state.executionReview" class="supplement-note" data-testid="generated-form-not-proof">系统填写的审批表、监督卡、送达清单和结案表，不证明已审批、签署或实际送达。</p>
    <button v-if="issueCount" class="review-more" @click="$emit('review')">核对 {{ issueCount }} 项识别疑问 →</button>
    </details>
  </section>
</template>
<script setup lang="ts">
import { computed,ref } from 'vue'
import { materialSupplementState,materialRequirement,materialSourceLabel,materialDisplayName } from '../domain/materialCompleteness.js'
const props=defineProps<{items:any[],issueCount:number,disabled?:boolean,hasArchive?:boolean}>()
defineEmits(['upload','review','source'])
const state=computed(()=>materialSupplementState(props.items))
const hasContent=computed(()=>state.value.required.length||state.value.applicability.length||state.value.optional.length||state.value.unknown.length||state.value.executionReview||props.issueCount)
const disclosure=ref<HTMLDetailsElement|null>(null)
function reveal(){if(disclosure.value){disclosure.value.open=true;disclosure.value.scrollIntoView?.({behavior:'smooth',block:'center'})}}
defineExpose({reveal})
</script>
<style scoped>
.supplement-summary{border:1px solid #e5e5ea;border-radius:12px;padding:18px 20px;margin:22px 0;background:#fafafa;font-size:12px;color:#6e6e73}.supplement-heading{display:flex;justify-content:space-between;align-items:center;gap:16px}.supplement-heading strong{font-weight:500;color:#424245}.supplement-heading p{margin:6px 0 0;font-size:11px;line-height:1.8;color:#6e6e73}.supplement-summary details{margin-top:16px}.supplement-summary summary{cursor:pointer;font-size:11px;color:#6e6e73}.supplement-item{display:flex;justify-content:space-between;align-items:baseline;gap:15px;padding:11px 0;border-bottom:1px solid #e5e5ea;line-height:1.8}.supplement-item small{font-size:10px;color:#a19578;text-align:right}.supplement-note{font-size:10px;color:#6e6e73;line-height:1.9}.review-more{border:0;background:none;padding:14px 0 0;text-align:left;font-size:11px;color:#6e6e73;cursor:pointer}
</style>
<style scoped>
.supplement-item{display:block}.material-heading{display:flex;justify-content:space-between;align-items:baseline;gap:15px}.supplement-item p{font-size:11px;margin:5px 0;color:#6e6e73}.source-link{font-size:10px;padding:2px 0;height:auto;display:block;margin:4px 0!important;white-space:normal;text-align:left}
</style>

