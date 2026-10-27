<template>
  <article class="issue-review-card" :class="{expanded,complete}" data-testid="issue-review-card" :data-issue-id="issueId">
    <button type="button" class="issue-card-toggle" data-testid="issue-review-toggle" :aria-expanded="expanded" :aria-controls="'issue-panel-'+issueId" @click="$emit('toggle')">
      <span class="issue-card-copy"><span class="issue-card-type">{{ summary.type }}</span><strong>{{ summary.message }}</strong><span v-if="summary.location" class="issue-card-location" :title="summary.location">{{ summary.location }}</span></span>
      <span class="issue-card-state">{{ complete?'已核对':'待核对' }}</span><span class="issue-card-chevron" aria-hidden="true">⌄</span>
    </button>
    <div v-show="expanded" :id="'issue-panel-'+issueId" class="issue-card-body" data-testid="issue-review-body"><slot /></div>
  </article>
</template>
<script setup lang="ts">
defineProps<{issueId:string,summary:{type:string,message:string,location:string},expanded:boolean,complete:boolean}>()
defineEmits(['toggle'])
</script>
<style scoped>
.issue-review-card{border:1px solid #e3e8dc;border-radius:8px;margin:9px 0;background:#fffefb;overflow:hidden}.issue-card-toggle{width:100%;display:flex;align-items:center;gap:12px;border:0;background:transparent;text-align:left;color:#556b4d;padding:13px 15px;cursor:pointer;font:inherit}.issue-card-toggle:focus-visible{outline:2px solid #668b57;outline-offset:-3px}.issue-card-copy{display:flex;flex-direction:column;min-width:0;flex:1;gap:4px}.issue-card-type{font-size:10px;color:#8c987f}.issue-card-copy strong{font-size:12px;font-weight:500;line-height:1.8;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.issue-card-location{font-size:10px;color:#87947b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.issue-card-state{flex:none;font-size:10px;color:#a38a5f;background:#f7f2e8;padding:4px 7px;border-radius:4px}.issue-card-chevron{font-size:18px;line-height:1;color:#91a083;transition:transform .15s}.expanded .issue-card-chevron{transform:rotate(180deg)}.expanded{border-color:#cbdcc0}.expanded .issue-card-toggle{background:#f5f8f0}.complete .issue-card-state{background:#edf3e7;color:#748e62}.issue-card-body{padding:15px;border-top:1px solid #e7ecdf;font-size:12px;line-height:1.8}.issue-card-body :deep(.el-checkbox){margin-top:6px}@media(max-width:600px){.issue-card-toggle{gap:8px;padding:12px}.issue-card-state{padding:3px 5px}.issue-card-body{padding:12px}}
</style>
