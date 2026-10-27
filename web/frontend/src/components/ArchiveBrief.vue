<template>
  <section class="archive-brief" aria-label="归档整理摘要">
    <h2>{{ summary.title }}</h2>
    <p v-if="activity" class="brief-activity" role="status" data-testid="archive-stage-progress">{{ activity.title }} <strong>{{ activity.done }} / {{ activity.total }} {{ activity.unit }}</strong></p>
    <div v-if="summary.stats.length" class="brief-stats"><span v-for="stat in summary.stats" :key="stat.label">{{ {'已导入材料':'材料','已有材料归入目录':'目录','此前保存成果':'历史成果','已生成成果':'成果'}[stat.label] || stat.label }} <strong>{{ stat.value }}</strong> {{ stat.unit }}</span></div>
    <details class="brief-details"><summary>案件摘要</summary><p>{{ summary.description }}</p><dl v-if="summary.facts.length" class="brief-facts"><div v-for="fact in summary.facts" :key="fact.label"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl></details>
  </section>
</template>
<script setup lang="ts">
defineProps<{summary:any,activity?:any}>()
</script>
<style scoped>
.archive-brief{padding:10px 0 18px;color:#6e6e73}.brief-kicker{font-size:11px;color:#6e6e73}.archive-brief h2{font-size:25px;font-weight:500;color:#424245;line-height:1.5;margin:12px 0}.archive-brief p{font-size:13px;line-height:1.95;margin:0;max-width:650px}.brief-stats{display:flex;flex-wrap:wrap;gap:20px;font-size:11px;color:#6e6e73;margin-top:20px}.brief-stats strong{font-weight:500;color:#424245}.brief-facts{font-size:11px;line-height:1.8;margin:18px 0 0}.brief-facts>div{display:flex;gap:14px;margin-top:5px}.brief-facts dt{flex:none;width:55px;color:#6e6e73}.brief-facts dd{margin:0;overflow-wrap:anywhere}.archive-brief .brief-activity{margin-top:20px;padding:12px 15px;border-left:2px solid #d2d2d7;background:#f5f5f7;color:#424245}.brief-activity strong{font-weight:500;margin-left:14px;font-variant-numeric:tabular-nums}@media(max-width:600px){.archive-brief h2{font-size:21px}.brief-stats{gap:12px}}
</style>
