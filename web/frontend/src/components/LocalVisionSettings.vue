<template>
  <section class="local-vision" aria-label="本地视觉引擎">
    <div class="local-title"><strong>{{ status?.preset?.name || '本地视觉模型' }}</strong><span>Ollama · 工作站本机</span></div>
    <p class="hint">资料在工作站处理。连接失败会停止，不会自动发送云端。</p>
    <el-form-item label="部署配置"><el-select :model-value="tier" style="width:100%" :disabled="!!busy" @update:model-value="value=>emit('update:tier',value)"><el-option v-for="(item,key) in status?.presets || {}" :key="key" :value="key" :label="item.label+' · '+item.hardware" /></el-select></el-form-item>
    <p v-if="status?.preset" class="hint">{{ status.preset.model }} · Q4_K_M · 下载约 {{ status.preset.download_gb }} GB</p>
    <template v-if="status"><details><summary>工作站检测结果</summary>
      <p class="hardware">内存 {{ status.hardware.ram_gb }} GB <span>可用 {{ status.hardware.available_ram_gb }} GB</span></p>
      <p class="hardware" v-for="gpu in status.hardware.gpus" :key="gpu.name">{{ gpu.name }} · {{ gpu.total_gb }} GB <span>可用 {{ gpu.free_gb }} GB</span></p>
      <p v-if="!status.hardware.gpu_verified" class="hint">未检测到可核验的 NVIDIA 独立显卡，其他显卡需另行验证。</p>
      <p class="advice">{{ status.advice }}</p>
      <p v-for="issue in status.issues" :key="issue" class="hint">{{ issue }}</p>
      </details><p v-if="status.download_running" role="status">模型正在下载；可稍后点击“检测工作站”。</p>
      <p v-if="status.benchmark">试跑{{ status.benchmark.passed?'通过':'未通过' }} · {{ status.benchmark.seconds }} 秒<br><span class="hint">单张虚构图片读取与 JSON 返回；不代表整卷速度或识别准确率。GPU 驻留 {{ status.benchmark.loaded_vram_gb }} GB。</span></p>
      <p v-else class="hint">尚未完成视觉试跑。</p>
    </template>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="local-actions">
      <el-button :loading="busy==='check'" :disabled="!!busy && busy!=='check'" @click="check">检测工作站</el-button>
      <el-button v-if="auth.isAdmin && status?.engine_ready" :loading="busy==='benchmark'" :disabled="!!busy && busy!=='benchmark'" @click="run('benchmark')">试跑视觉识别</el-button>
    </div>
    <details>
      <summary>建议配置与准备</summary>
      <table><thead><tr><th>部署配置</th><th>推荐视觉模型</th></tr></thead><tbody><tr v-for="item in status?.presets || {}" :key="item.model"><td>{{ item.label }}<br>{{ item.hardware }}</td><td>{{ item.name }}</td></tr></tbody></table>
      <p class="hint">四档为固定部署标准，不随本机调整。独立显存按单卡计，统一内存另需核验 GPU 可用容量和带宽。下载大小不是推理总占用；以上模型均待真实整卷及断网验收，不承诺速度或准确率。</p>
      <template v-if="auth.isAdmin">
        <p v-if="status && !status.installed" class="hint">管理员先在工作站安装 <a href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">Ollama</a>，再准备引擎。无需让普通用户配置。</p>
        <div class="local-actions"><el-button :disabled="!!busy||!status?.installed" :loading="busy==='prepare'" @click="run('prepare')">准备引擎</el-button><el-button :disabled="!!busy||!status?.installed||status?.download_running||status?.engine_ready" :loading="busy==='download'" @click="run('download')">下载模型（约 {{ status?.preset?.download_gb || '—' }} GB）</el-button></div>
        <p class="hint">下载只获取模型文件。归档与试跑不使用云服务；本地服务的云功能由工作站关闭。</p>
      </template>
    </details>
  </section>
</template>
<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
const props=defineProps<{tier:string}>()
import client from '../api/client'
import { useAuthStore } from '../stores/auth'
let active=true
onUnmounted(()=>{active=false})
const auth=useAuthStore(),status=ref<any>(null),busy=ref(''),message=ref('')
const emit=defineEmits<{(event:'ready',value:boolean):void;(event:'update:tier',value:string):void}>()
async function read(){const tier=props.tier||'minimum';const data=(await client.get('/settings/local-vision',{params:{tier}})).data;if(!active||tier!==(props.tier||'minimum'))return;status.value=data;emit('ready',data.ready===true)}
async function check(){if(busy.value)return;busy.value='check';message.value='';try{await read()}catch{status.value=null;emit('ready',false);message.value='暂时无法检测，请检查工作站连接。'}finally{busy.value=''}}
async function run(action:string){if(busy.value)return;busy.value=action;message.value='';try{const {data}=await client.post('/settings/local-vision/'+action,{tier:props.tier||'minimum'},{timeout:210000});message.value=data.message||(data.passed?'视觉试跑通过':'视觉试跑未通过');await read()}catch(error:any){message.value=typeof error.response?.data?.detail==='string'?error.response.data.detail:'操作未完成，请重新检测工作站。';try{await read()}catch{emit('ready',false)}}finally{busy.value=''}}
watch(()=>props.tier,()=>{emit('ready',false);status.value=null;check()})
onMounted(check)
</script>
<style scoped>
.local-vision{margin:18px 0}.local-title{display:flex;gap:12px;align-items:center}.local-title span,.hint,.hardware span{color:#777;font-size:12px;line-height:1.8}.local-title strong{font-weight:500}.hardware{font-size:13px;margin:8px 0}.hardware span{margin-left:12px}.advice{font-size:13px}.local-actions{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.local-actions .el-button{margin-left:0}details{border-top:1px solid #eee;margin-top:18px;padding-top:12px}summary{cursor:pointer;color:#777;font-size:12px}table{font-size:12px;width:100%;text-align:left;border-collapse:collapse;margin-top:12px}td,th{padding:8px;border-bottom:1px solid #eee;font-weight:400}a{color:#176bd6}
</style>
