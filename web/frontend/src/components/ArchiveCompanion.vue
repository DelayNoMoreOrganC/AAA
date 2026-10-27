<template>
  <div ref="dock" class="archive-companion" :class="{ suppressed, dragging:!!dragging }" :style="position?{left:position.x+'px',top:position.y+'px',right:'auto',bottom:'auto'}:{}" @keydown.esc.stop="close">
    <section v-show="opened&&!suppressed" id="archive-companion-panel" class="companion-panel" :style="panelStyle" role="dialog" aria-label="卷小助" data-testid="companion-panel">
      <header><strong>卷小助</strong><button ref="closeButton" type="button" aria-label="收起助理" data-testid="companion-close" @click="close">×</button></header>
      <p class="companion-status" role="status">{{ presentation.label }}</p>
      <nav v-if="actions.length" aria-label="归档快捷操作"><button v-for="action in actions" :key="action.kind" type="button" :data-testid="'companion-action-'+action.kind" :disabled="action.disabled" @click="choose(action.kind)">{{ action.label }} <span aria-hidden="true">↗</span></button></nav>
      <div class="companion-content"><slot v-if="activated" /></div>
      <footer><details class="companion-actions"><summary>小动作</summary><div class="motion-options" aria-label="预览卷小助动作"><button v-for="item in motions" :key="item.id" type="button" :data-testid="'companion-motion-'+item.id" :aria-pressed="motionPreview===item.id" @click="motionPreview=item.id">{{ item.label }}</button></div></details><button type="button" data-testid="companion-motion" @click="motionPaused=!motionPaused">{{ motionPaused?'开启动效':'暂停动效' }}</button><button type="button" data-testid="companion-hide" @click="hide">隐藏形象</button><button type="button" data-testid="companion-reset" @click="resetPosition">恢复位置</button><details><summary>形象来源</summary><p><a href="/pet/CHARACTER.txt" target="_blank" rel="noopener">卷小助 · 素材说明</a></p></details></footer>
    </section>
    <button v-if="hidden" class="companion-restore" type="button" data-testid="companion-restore" @click="hidden=false">助理</button>
    <button v-else ref="launcher" type="button" class="companion-launcher" :class="presentation.state" data-testid="companion-open" :aria-label="'卷小助：'+presentation.label" :aria-expanded="opened" aria-controls="archive-companion-panel" title="点击对话，拖动摆放；方向键微调位置" @pointerdown="beginDrag" @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="cancelDrag" @lostpointercapture="cancelDrag" @keydown="moveByKey" @click="activate">
      <span class="companion-character" :class="[activeMotion,{still:motionPaused||reducedMotion||assetFailed}]" :data-motion="activeMotion"><img v-if="!assetFailed" src="/pet/juanzhu-actions-v2.png" :style="motionGeometry" alt="" draggable="false" width="720" height="720" @error="assetFailed=true" /><span v-else class="character-fallback">卷小助</span></span>
      <span class="companion-caption">{{ opened?'收起':presentation.short||'问助理' }}</span>
    </button>
  </div>
</template>
<script setup lang="ts">
import {ref,computed,watch,nextTick,onMounted,onUnmounted} from 'vue'
import {clampCompanion,restoreCompanion,saveCompanion,companionPanel} from '../domain/companionPosition.js'
const props=withDefaults(defineProps<{presentation?:{state:string,label:string,short?:string},actions?:{kind:string,label:string,disabled?:boolean}[],suppressed?:boolean}>(),{presentation:()=>({state:'idle',label:'导入材料后，我来整理。'}),actions:()=>[],suppressed:false})
const emit=defineEmits<{action:[kind:string]}>()
const opened=ref(false),activated=ref(false),hidden=ref(false),motionPaused=ref(false),reducedMotion=ref(false),assetFailed=ref(false)
const launcher=ref<HTMLButtonElement|null>(null),closeButton=ref<HTMLButtonElement|null>(null)
const dock=ref<HTMLElement|null>(null),position=ref<{x:number,y:number}|null>(null)
const viewport=ref({width:1000,height:800}),size=ref({width:180,height:212}),dragging=ref<any>(null)
const positionKey='aaa-companion-position-v1'
const motions=[{id:'auto',label:'自动'},{id:'reading',label:'看卷宗'},{id:'thinking',label:'思考'},{id:'greeting',label:'招手'}]
const motionPreview=ref('auto')
const activeMotion=computed(()=>motionPreview.value!=='auto'?motionPreview.value:props.presentation.state==='working'?'reading':props.presentation.state==='ready'?'greeting':['question','error'].includes(props.presentation.state)?'thinking':'idle')
// Use transparent row gutters in the generated atlas so no neighbouring feet
// or hair appear while animating. Horizontal frame widths remain equal.
const motionGeometry=computed(()=>{const rows:Record<string,number[]>={idle:[0,322],reading:[322,316],thinking:[638,314],greeting:[952,302]};const [top,height]=rows[activeMotion.value]||rows.idle;return {top:(-top/height*100)+'%',height:(1254/height*100)+'%'}})
let savedPosition:any=null,suppressClick=false
const panelStyle=computed(()=>position.value?companionPanel(position.value,viewport.value,size.value):{})
function measure(){viewport.value={width:window.innerWidth||1000,height:window.innerHeight||800};size.value=viewport.value.width<=600?{width:144,height:176}:{width:180,height:212}}
function persist(){if(!position.value)return;savedPosition=saveCompanion(position.value,viewport.value,size.value);try{window.localStorage?.setItem(positionKey,JSON.stringify(savedPosition))}catch{}}
function resize(){measure();position.value=restoreCompanion(savedPosition,viewport.value,size.value)}
function resetPosition(){savedPosition=null;try{window.localStorage?.removeItem(positionKey)}catch{};resize()}
function beginDrag(event:PointerEvent){
  if(event.button!==0||event.isPrimary===false)return
  suppressClick=false;measure()
  const rect=dock.value?.getBoundingClientRect?.()
  const start=position.value||(rect?{x:rect.left,y:rect.top}:restoreCompanion(null,viewport.value,size.value))
  dragging.value={id:event.pointerId,x:event.clientX,y:event.clientY,start,moved:false}
  try{(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)}catch{}
}
function moveDrag(event:PointerEvent){
  const drag=dragging.value;if(!drag||drag.id!==event.pointerId)return
  const dx=event.clientX-drag.x,dy=event.clientY-drag.y
  if(!drag.moved&&Math.hypot(dx,dy)<6)return
  drag.moved=true;opened.value=false;suppressClick=true;event.preventDefault()
  position.value=clampCompanion({x:drag.start.x+dx,y:drag.start.y+dy},viewport.value,size.value)
}
function endDrag(event:PointerEvent){if(!dragging.value||dragging.value.id!==event.pointerId)return;const moved=dragging.value.moved;dragging.value=null;if(moved)persist();try{(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId)}catch{}}
function cancelDrag(){if(dragging.value?.moved)persist();dragging.value=null}
function activate(event:MouseEvent){if(suppressClick&&event.detail!==0){suppressClick=false;return}suppressClick=false;toggle()}
function moveByKey(event:KeyboardEvent){
  const delta:Record<string,number[]>={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}
  if(!delta[event.key])return
  event.preventDefault();measure();const current=position.value||restoreCompanion(null,viewport.value,size.value),step=event.shiftKey?40:12
  position.value=clampCompanion({x:current.x+delta[event.key][0]*step,y:current.y+delta[event.key][1]*step},viewport.value,size.value);persist()
}

function close(){opened.value=false;nextTick(()=>launcher.value?.focus?.())}
function toggle(){if(opened.value){close();return}activated.value=true;opened.value=true;nextTick(()=>closeButton.value?.focus?.())}
function hide(){opened.value=false;hidden.value=true}
function choose(kind:string){emit('action',kind);close()}
watch(()=>props.suppressed,value=>{if(value)opened.value=false})
watch(()=>props.presentation.state,()=>{assetFailed.value=false;motionPreview.value='auto'})
let media:MediaQueryList|undefined
function motionChanged(){reducedMotion.value=media?.matches===true}
onMounted(()=>{try{savedPosition=JSON.parse(window.localStorage?.getItem(positionKey)||'null')}catch{};resize();window.addEventListener?.('resize',resize);media=window.matchMedia?.('(prefers-reduced-motion: reduce)');motionChanged();media?.addEventListener?.('change',motionChanged)})
onUnmounted(()=>{window.removeEventListener?.('resize',resize);media?.removeEventListener?.('change',motionChanged)})
</script>
<style scoped>
.archive-companion{position:fixed;right:22px;bottom:18px;z-index:1100;font-size:12px;color:#3c3c43}.archive-companion.dragging .companion-launcher{cursor:grabbing}.archive-companion.suppressed{visibility:hidden;pointer-events:none}.companion-launcher{touch-action:none;user-select:none;display:flex;align-items:center;flex-direction:column;width:180px;padding:0;border:0;background:transparent;cursor:pointer;color:inherit;float:right}.companion-character{position:relative;display:block;width:180px;height:180px;overflow:hidden;animation:companion-breathe 4s ease-in-out infinite;transform-origin:bottom center}.companion-launcher img{position:absolute;left:0;top:0;display:block;object-fit:fill;width:400%;height:400%;max-width:none;filter:drop-shadow(0 4px 7px #1d1d1f12)}.companion-character.still{animation:none}.companion-caption{background:#ffffffed;border:1px solid #e9e9ed;border-radius:20px;padding:5px 12px;font-size:11px;box-shadow:0 2px 10px #00000006}.companion-launcher.error .companion-caption{color:#936345}.companion-panel{position:absolute;right:0;bottom:213px;width:min(420px,calc(100vw - 32px));max-height:calc(100dvh - 218px);display:flex;flex-direction:column;background:#fffffff7;backdrop-filter:blur(18px);border:1px solid #e5e5ea;border-radius:20px;box-shadow:0 16px 64px #1d1d1f1c;overflow:hidden}.companion-panel header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 0}.companion-panel strong{font-weight:600;font-size:14px}.companion-panel header button{font-size:22px;padding:0 6px}.companion-panel button{font-family:inherit;cursor:pointer}.companion-panel header button,.companion-panel footer button{border:0;background:transparent;color:#6e6e73}.companion-status{margin:10px 20px;color:#6e6e73;line-height:1.7;overflow-wrap:anywhere}.companion-panel nav{display:flex;gap:7px;flex-wrap:wrap;margin:0 20px 8px}.companion-panel nav button{border:1px solid #e8e8ed;background:#f8f8fa;border-radius:9px;padding:7px 10px;color:#424245;font-size:11px}.companion-panel button:disabled{opacity:.5;cursor:default}.companion-content{overflow:auto;overscroll-behavior:contain;padding:0 20px;min-height:0}.companion-content :deep(.archive-assistant){margin:4px 0 12px}.companion-content :deep(.assistant-heading){display:none}.companion-content :deep(.conversation){max-height:32dvh}.companion-panel footer{display:flex;align-items:baseline;gap:12px;padding:12px 20px;border-top:1px solid #f0f0f3;font-size:10px;color:#8a8a90;flex-wrap:wrap}.companion-panel footer button{font-size:10px;padding:0}.companion-panel footer details{margin-left:auto}.companion-panel footer p{margin-bottom:0}.companion-panel a{color:inherit}.companion-restore{border:1px solid #e5e5ea;background:#fff;border-radius:20px;padding:8px 14px;color:#6e6e73;font-size:11px;cursor:pointer}.companion-panel button:focus-visible,.companion-launcher:focus-visible,.companion-restore:focus-visible{outline:2px solid #7893bc;outline-offset:3px}@media(max-width:600px){.archive-companion{right:12px;bottom:12px}.companion-launcher{width:144px}.companion-character{width:144px;height:144px}.companion-panel{bottom:177px;width:calc(100vw - 24px);max-height:calc(100dvh - 182px)}}

.companion-panel footer .companion-actions{margin-left:0}.motion-options{display:flex;gap:6px;flex-wrap:wrap;padding:8px 0}.companion-panel footer .motion-options button{padding:6px 10px;border:1px solid #e5e5ea;border-radius:7px}.companion-panel footer .motion-options button[aria-pressed="true"]{background:#424245;color:#fff;border-color:#424245}.character-fallback{display:grid;place-items:center;height:100%;color:#6e6e73;font-size:14px}.companion-launcher.working .companion-character:not(.still){animation-duration:2.4s}.companion-launcher.ready .companion-character:not(.still){animation:companion-ready .7s ease-out 1,companion-breathe 4s .7s ease-in-out infinite}
@keyframes companion-breathe{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}@keyframes companion-ready{0%,100%{transform:translateY(0)}45%{transform:translateY(-8px)}}@media(prefers-reduced-motion:reduce){.companion-character{animation:none!important}}

.companion-character img{animation:pet-blink 5.4s steps(1,end) infinite}.companion-character.reading img{animation:pet-reading 4.8s steps(1,end) infinite}.companion-character.thinking img{animation:pet-thinking 6s steps(1,end) infinite}.companion-character.greeting img{animation:pet-greeting 4.8s steps(1,end) infinite}.companion-character.still img{animation:none;left:0}.archive-companion.suppressed .companion-character img,.archive-companion.dragging .companion-character img{animation-play-state:paused}
@keyframes pet-blink{0%,78%,100%{left:0}80%,85%{left:-100%}82%,84%{left:-200%}87%{left:-300%}}
@keyframes pet-reading{0%,45%,100%{left:0}52%{left:-100%}63%{left:-200%}78%,96%{left:-300%}}
@keyframes pet-thinking{0%,32%,100%{left:0}38%,52%{left:-100%}60%,72%{left:-200%}80%,95%{left:-300%}}
@keyframes pet-greeting{0%,35%,100%{left:0}40%,60%{left:-100%}50%,70%{left:-200%}80%,95%{left:-300%}}
@media(prefers-reduced-motion:reduce){.companion-character img{animation:none!important;left:0}}
</style>
