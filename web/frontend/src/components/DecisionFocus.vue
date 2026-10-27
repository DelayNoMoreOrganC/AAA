<template>
  <section class="decision-focus" data-testid="decision-focus"><header><span>核对记录</span><strong>{{ breakdown || (remaining+' 项尚未处理') }}</strong></header><div class="decision-navigation"><el-button text :disabled="disabled||total<2" @click="$emit('previous')">上一项</el-button><span>{{ position }} / {{ total }}</span><el-button text :disabled="disabled||total<2" @click="$emit('next')">下一项</el-button></div><div class="decision-label"><span>{{ item.type }}</span><small>{{ item.resolved?'本项已有核对记录':'待核对' }}</small></div><h3>{{ item.title }}</h3><p v-if="item.location" class="decision-location">{{ item.location }}</p><slot /></section>
</template>
<script setup lang="ts">
defineProps<{item:any,remaining:number,position:number,total:number,disabled?:boolean,breakdown?:string}>()
defineEmits(['previous','next'])
</script>
<style scoped>
.decision-focus{border:1px solid #e1e8d9;border-radius:12px;padding:20px;background:white;color:#687c5b;font-size:12px}.decision-focus header{display:flex;justify-content:space-between;gap:14px;font-size:11px;color:#98a38b}.decision-focus header strong{font-weight:400;color:#a38b64}.decision-navigation{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eef1e7;margin:10px 0 20px;font-size:10px;color:#a2ac96}.decision-label{display:flex;gap:12px;align-items:center;font-size:10px;color:#8d9b7e}.decision-label small{font-size:10px;color:#a3ac98}.decision-focus h3{font-size:15px;font-weight:500;color:#56704b;line-height:1.9;margin:10px 0}.decision-location{font-size:11px;color:#99a58c;line-height:1.8;overflow-wrap:anywhere;margin:0 0 18px}
</style>
