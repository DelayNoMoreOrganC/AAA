<template>
  <div v-loading="loading" class="settings-page">
    <div class="page-kicker">工作站管理</div><h1 class="page-heading">归档设置</h1>
    <p class="page-description">选择处理方式和成果位置。</p>
    <div class="settings-grid">
      <section class="surface connection-card">
        <div class="settings-title"><h2>处理方式</h2></div>
        <div class="mode-options" role="group" aria-label="选择处理方式">
          <button type="button" :class="{selected:form.processing_mode==='deepseek_cloud'}" :disabled="saving||policySaving||!externalAllowed" :aria-pressed="form.processing_mode==='deepseek_cloud'" @click="form.processing_mode='deepseek_cloud'"><strong>云端处理</strong><span>DeepSeek · 无需独立显卡</span></button>
          <button type="button" :class="{selected:form.processing_mode==='ollama_local'}" :disabled="saving||policySaving" :aria-pressed="form.processing_mode==='ollama_local'" @click="form.processing_mode='ollama_local'"><strong>本地保密处理</strong><span>Ollama · 资料留在工作站</span></button>
        </div>
        <p v-if="!['deepseek_cloud','ollama_local'].includes(form.processing_mode)" class="hint">当前保留旧版处理配置，可在高级设置查看。</p>
        <LocalVisionSettings v-model:tier="form.local_vision_tier" v-if="form.processing_mode==='ollama_local'" @ready="value=>localReady=value" />
        <el-form label-position="top" :disabled="saving||policySaving">
          <template v-if="form.processing_mode==='deepseek_cloud'">
            <p class="hint">获准的页面图像及必要文字发送至 DeepSeek。每案开始前确认。</p>
            <el-form-item label="API 密钥"><el-input v-model="secretDrafts.deepseek_api_key.value" type="password" show-password autocomplete="new-password" :placeholder="configured.deepseek?'已保存；留空保留':'输入 DeepSeek 标准 API 密钥'" @input="secretDrafts.deepseek_api_key.clear=false" /></el-form-item>
            <el-checkbox v-if="configured.deepseek" v-model="secretDrafts.deepseek_api_key.clear" :disabled="!!secretDrafts.deepseek_api_key.value.trim()">清除已保存的密钥</el-checkbox>
          </template>
          <details v-if="form.processing_mode!=='ollama_local'"><summary class="policy-summary">工作站云权限 · {{ externalAllowed?'已开启':'未开启' }}</summary>
          <section class="cloud-policy" aria-label="工作站云功能"><div class="policy-heading"><strong>工作站云功能</strong><span>{{ cloudPolicy?.locked?'部署策略已锁定':externalAllowed?'已开启':'未开启' }}</span></div><p>此设置影响整个工作站。开放功能后，每个新案件和新增材料仍须单独授权。</p><p v-if="cloudPolicy?.locked">当前部署策略禁止开启云端处理；密钥仍可先保存。</p><template v-else-if="cloudPolicy"><template v-if="externalAllowed"><el-button size="small" :loading="policySaving" @click="setCloudPolicy(false)">关闭云功能</el-button><small>关闭后，新的 DeepSeek / GLM 视觉请求将停止启动，已发出的请求不能撤回；历史任务的处理方式不会更改。</small></template><template v-else><el-checkbox v-model="cloudPolicyConfirmed">允许本工作站向外部 AI 发送已获准的材料</el-checkbox><el-button size="small" :disabled="!cloudPolicyConfirmed" :loading="policySaving" @click="setCloudPolicy(true)">开启云功能</el-button></template></template><p v-else>云功能状态尚未读取到。<el-button text @click="loadCloudPolicy">重新读取</el-button></p></section></details>
          <p class="mode-note">设置用于新归档；已有任务保留原处理方式。</p>
          <div class="setting-actions"><el-button type="primary" :loading="saving" :disabled="form.processing_mode==='ollama_local'&&!localReady" @click="onSave">保存配置</el-button><el-button v-if="form.processing_mode==='deepseek_cloud'" :loading="checkingProvider==='deepseek'" :disabled="!canTest('deepseek')" @click="testProvider('deepseek')">测试 DeepSeek 连接</el-button></div>
        </el-form>
        <el-alert v-if="providerCheck" :title="providerCheck.message" :type="providerCheck.ready?'success':'warning'" :closable="false" class="result-note" />
        <div v-if="readiness && readiness.mode===form.processing_mode && form.processing_mode!=='ollama_local'" class="readiness"><strong>{{ readiness.ready?'当前处理方式已就绪':'当前处理方式还需准备' }}</strong><p v-for="issue in readiness.issues || []" :key="issue">{{ issue }}</p><el-button text :loading="checking" @click="check">重新检查</el-button></div>
      </section>
      <aside>
        <section class="surface output-settings"><span class="eyebrow">自动保存</span><h2 class="section-title">成果放在哪里</h2><p class="hint">每个案件保存为独立文件夹，网页中也能下载完整成果包。</p><el-input v-model="outputDirectory" placeholder="工作站本机文件夹路径" /><el-button :loading="savingOutput" class="output-save" @click="saveOutput">保存目录</el-button></section>
        <p class="settings-footnote">密钥和处理设置仅适用于当前账号。普通使用者从导入材料开始。</p>
      </aside>
    </div>
    <details class="advanced-settings"><summary>其他模型与高级设置</summary>
      <section class="surface advanced-body"><el-form label-position="top" :disabled="saving||policySaving">
        <el-form-item label="兼容处理方式"><el-select v-model="form.processing_mode"><el-option value="deepseek_cloud" label="云端视觉归档" :disabled="!externalAllowed"/><el-option value="ollama_local" label="本地视觉归档"/><el-option value="local" label="本地文字模型（旧版）"/><el-option value="glm_cloud" label="GLM 视觉归档" :disabled="!externalAllowed"/><el-option value="cloud" label="云模型与 OCR（旧版）" :disabled="!externalAllowed"/></el-select></el-form-item>
        <h3 class="section-title">GLM 视觉归档</h3><p class="hint">固定使用 GLM-5.3-Flash，无需 MinerU。需要标准模型 API 额度，Coding Plan 套餐不能作为本网页调用额度。</p>
        <el-form-item label="智谱标准 API 密钥"><el-input v-model="secretDrafts.glm_api_key.value" type="password" show-password autocomplete="new-password" :placeholder="configured.glm?'已保存；留空保留':'输入 API 密钥'" @input="secretDrafts.glm_api_key.clear=false" /></el-form-item>
        <el-checkbox v-if="configured.glm" v-model="secretDrafts.glm_api_key.clear" :disabled="!!secretDrafts.glm_api_key.value.trim()">清除已保存的 GLM 密钥</el-checkbox>
        <el-button class="provider-test" :loading="checkingProvider==='glm'" :disabled="!canTest('glm')" @click="testProvider('glm')">测试已保存的 GLM 连接</el-button>
        <details class="provider-details"><summary>旧版本地文字模型</summary><el-form-item label="本机模型服务地址"><el-input v-model="form.local_llm_base_url" placeholder="http://127.0.0.1:11434/v1" /></el-form-item><el-form-item label="本机已加载的模型名称"><el-input v-model="form.local_llm_model" /></el-form-item><p class="hint">本地模型与 OCR 在工作站运行，模型服务仅允许本机回环地址。</p></details>
        <details class="provider-details"><summary>旧版云模型与独立 OCR</summary><p class="hint">仅“其他云模型与 OCR”使用下列配置。DeepSeek 视觉归档与 GLM 视觉归档均无需 MinerU。</p><el-form-item label="旧版模型服务地址"><el-input v-model="form.deepseek_base_url" /></el-form-item><el-form-item label="旧版模型名称"><el-input v-model="form.deepseek_model" /></el-form-item><el-form-item label="MinerU OCR 密钥"><el-input v-model="secretDrafts.mineru_api_token.value" type="password" show-password autocomplete="new-password" :placeholder="configured.mineru?'已保存；留空保留':'输入 OCR 密钥'" @input="secretDrafts.mineru_api_token.clear=false" /></el-form-item><el-checkbox v-if="configured.mineru" v-model="secretDrafts.mineru_api_token.clear" :disabled="!!secretDrafts.mineru_api_token.value.trim()">清除已保存的 MinerU 密钥</el-checkbox></details>
        <el-form-item label="默认正文排列"><el-radio-group v-model="form.order_mode"><el-radio value="catalog">按归档目录</el-radio><el-radio value="original">按原始页序</el-radio></el-radio-group></el-form-item>
        <el-button type="primary" :loading="saving" @click="onSave">保存高级设置</el-button>
      </el-form></section>
    </details>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import client from '../api/client'
import LocalVisionSettings from '../components/LocalVisionSettings.vue'
const localReady=ref(false)
import { processingSettingsPayload,cloudPolicyUpdate } from '../domain/processingPrivacy.js'
const loading=ref(false),saving=ref(false),checking=ref(false),externalAllowed=ref(false),savingOutput=ref(false),outputDirectory=ref('')
const readiness=ref<any>(null),checkingProvider=ref(''),providerCheck=ref<{ready:boolean,message:string}|null>(null)
const cloudPolicy=ref<any>(null),cloudPolicyConfirmed=ref(false),policySaving=ref(false)
const configured=reactive({deepseek:false,glm:false,mineru:false})
const secretDrafts=reactive({deepseek_api_key:{value:'',clear:false},glm_api_key:{value:'',clear:false},mineru_api_token:{value:'',clear:false}})
const form=reactive({processing_mode:'local',local_vision_tier:'minimum',local_llm_base_url:'http://127.0.0.1:11434/v1',local_llm_model:'',deepseek_base_url:'https://api.deepseek.com',deepseek_model:'deepseek-v4-flash',order_mode:'catalog'})
function applySettings(data:any){for(const key of Object.keys(form))if(typeof data[key]==='string')(form as any)[key]=data[key];configured.deepseek=data.deepseek_key_configured===true;configured.glm=data.glm_key_configured===true;configured.mineru=data.mineru_key_configured===true;if(typeof data.external_ai_allowed==='boolean')externalAllowed.value=data.external_ai_allowed}
async function check(){checking.value=true;try{readiness.value=(await client.get('/settings/readiness')).data}catch{readiness.value=null;ElMessage.error('无法检查工作站，请恢复连接后重试')}finally{checking.value=false}}
async function load(){loading.value=true;try{const [settings,capabilities]=await Promise.all([client.get('/settings'),client.get('/capabilities')]);applySettings(settings.data);externalAllowed.value=capabilities.data.external_ai_allowed===true;try{outputDirectory.value=(await client.get('/workstation/output')).data.output_directory}catch{ElMessage.warning('保存目录暂未读取到，请稍后重试')}await Promise.all([check(),loadCloudPolicy()])}catch{ElMessage.error('设置暂未读取到，请恢复连接后刷新')}finally{loading.value=false}}
async function onSave(){if(saving.value||policySaving.value)return;if(form.processing_mode==='ollama_local'&&!localReady){ElMessage.warning('请先准备本地引擎并完成视觉试跑');return;}saving.value=true;providerCheck.value=null;try{const {data}=await client.put('/settings',processingSettingsPayload(form,secretDrafts));applySettings(data);for(const draft of Object.values(secretDrafts)){draft.value='';draft.clear=false}ElMessage.success('配置已保存');await check()}catch{ElMessage.error('配置未能保存，输入仍保留在当前页面，请检查连接后重试')}finally{saving.value=false}}
async function loadCloudPolicy(){try{cloudPolicy.value=(await client.get('/settings/cloud-policy')).data;externalAllowed.value=cloudPolicy.value.allowed===true&&!cloudPolicy.value.locked;cloudPolicyConfirmed.value=false}catch{cloudPolicy.value=null}}
async function setCloudPolicy(allowed:boolean){if(policySaving.value||saving.value)return;try{const body=cloudPolicyUpdate(allowed,cloudPolicyConfirmed.value,cloudPolicy.value);policySaving.value=true;cloudPolicy.value=(await client.put('/settings/cloud-policy',body)).data;externalAllowed.value=cloudPolicy.value.allowed===true&&!cloudPolicy.value.locked;cloudPolicyConfirmed.value=false;providerCheck.value=null;await check();ElMessage.success(allowed?'云功能已开放，每个案件仍须单独授权':'云功能已关闭')}catch{ElMessage.error('云功能状态未能更新，请重新读取状态后重试');await loadCloudPolicy()}finally{policySaving.value=false}}
function canTest(provider:'deepseek'|'glm'){const draft=secretDrafts[provider==='deepseek'?'deepseek_api_key':'glm_api_key'];return externalAllowed.value&&configured[provider]&&!draft.value.trim()&&!draft.clear&&!saving.value&&!policySaving.value&&!checkingProvider.value}
async function testProvider(provider:'deepseek'|'glm'){if(!canTest(provider))return;checkingProvider.value=provider;providerCheck.value=null;try{const {data}=await client.post('/settings/'+provider+'/check');providerCheck.value={ready:data.ready===true,message:data.message||'连接检查已结束'}}catch{providerCheck.value={ready:false,message:'连接检查未通过，请核对已保存密钥、标准 API 额度及工作站外部 AI 开关。'}}finally{checkingProvider.value=''}}
async function saveOutput(){savingOutput.value=true;try{outputDirectory.value=(await client.put('/workstation/output',{output_directory:outputDirectory.value.trim()})).data.output_directory;ElMessage.success('成果保存目录已更新')}catch{ElMessage.error('目录未能保存，请检查工作站路径')}finally{savingOutput.value=false}}
onMounted(load)
</script>
<style scoped>
.settings-page{max-width:1000px;margin:auto}.settings-grid{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(250px,1fr);gap:24px;align-items:start}.settings-title{display:flex;justify-content:space-between;align-items:center;gap:12px}.settings-title h2{font-size:20px;font-weight:500;margin:6px 0 0}.eyebrow{font-size:11px;color:#8a998d;letter-spacing:.06em}.hint{font-size:12px;line-height:1.9;color:#7e8a7b}.connection-card>.hint{margin:18px 0 24px}.secret-hint{margin:8px 0 24px}.setting-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}.setting-actions .el-button{margin-left:0}.mode-note{font-size:12px;color:#8d927e;line-height:1.9}.result-note{margin-top:20px}.readiness{border-top:1px solid #e9ede3;margin-top:22px;padding-top:16px;font-size:12px;line-height:1.8;color:#74826d}.readiness strong{font-weight:500}.readiness p{margin:6px 0;color:#9d855e}.output-settings>.section-title{margin-top:8px}.output-save{margin-top:16px}.settings-footnote{font-size:11px;color:#9aa392;line-height:1.9;padding:8px}.advanced-settings{margin-top:28px;font-size:12px;color:#78866f}.advanced-settings>summary,.provider-details>summary{cursor:pointer;padding:12px 0}.advanced-body{margin-top:8px;max-width:690px}.provider-details{border-top:1px solid #e8ecdf;margin:22px 0;padding-top:4px}.provider-details .el-form-item{margin-top:12px}.provider-test{display:block;margin-top:12px}@media(max-width:800px){.settings-grid{grid-template-columns:1fr}.advanced-body{max-width:none}}
</style>
<style scoped>
.cloud-policy{padding:14px 15px;border:1px solid #e1e6d8;background:#f7f9f3;border-radius:7px;font-size:11px;line-height:1.9;margin:16px 0}.policy-heading{display:flex;justify-content:space-between;gap:12px;color:#6e8063}.policy-heading strong{font-weight:500}.policy-heading span{color:#a18c63}.cloud-policy p{margin:8px 0;color:#8b967f}.cloud-policy small{display:block;margin-top:8px;color:#9aa18c}.cloud-policy .el-checkbox{display:flex;white-space:normal;height:auto;margin:10px 0 12px}.cloud-policy :deep(.el-checkbox__label){white-space:normal;font-size:11px;line-height:1.8}.cloud-policy :deep(.el-checkbox__input){padding-top:4px}
</style>

<style scoped>
.mode-options{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0}.mode-options button{padding:18px 14px;text-align:left;border:1px solid #e2e4e8;border-radius:12px;background:white;cursor:pointer;color:#222}.mode-options button.selected{border-color:#1672e8;background:#f5f9ff}.mode-options button:disabled{opacity:.5;cursor:default}.mode-options strong{display:block;font-weight:500;font-size:15px;margin-bottom:8px}.mode-options span{font-size:12px;color:#777}.policy-summary{cursor:pointer;font-size:12px;color:#777;margin-top:20px}@media(max-width:500px){.mode-options{grid-template-columns:1fr}}
</style>
