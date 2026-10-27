<template>
  <div class="entry-page" :class="{ connecting: loading, entering }">
    <div v-if="entering" class="entry-scan" aria-hidden="true"></div>
    <div class="entry-glass" aria-hidden="true"><i></i><i></i><i></i></div>
    <header class="entry-header"><a href="/login" class="entry-brand">AAA<span>AI ARCHIVING ASSISTANT</span></a><span class="entry-edition">卷小助 · WORKSPACE</span></header>
    <main class="entry-main">
      <div class="entry-orbit" aria-hidden="true"><i></i><i></i></div>
      <section class="entry-content">
        <p class="entry-kicker">{{ entering ? 'WELCOME TO YOUR WORKSPACE' : adminMode ? 'ADMINISTRATOR' : 'YOUR ARCHIVE WORKSPACE' }}</p>
        <h1>{{ entering ? '欢迎，'+(auth.user?.display_name || name || account) : adminMode ? '工作站管理' : '欢迎回来' }}<span aria-hidden="true">_</span></h1>
        <p class="entry-subtitle">卷小助智能归档</p>
        <div v-if="entering" class="entry-welcome" role="status" aria-live="polite" data-testid="entry-welcome"><span>你的工作空间已就绪</span><div class="entry-progress" aria-hidden="true"><i></i></div><small>让每一份材料，各归其位。</small></div>
        <form v-else @submit.prevent="onLogin" class="entry-form" data-testid="entry-form">
          <label :for="adminMode?'admin-name':'profile-name'">{{ adminMode ? '登录标识' : '怎么称呼你' }}<span>{{ adminMode?'ACCOUNT':'NAME' }}</span></label>
          <input v-if="!adminMode" id="profile-name" :value="name" @input="name=($event.target as HTMLInputElement).value" maxlength="40" autocomplete="nickname" placeholder="输入你的姓名或常用称呼" :disabled="loading" data-testid="profile-name" />
          <input v-else id="admin-name" :value="account" @input="account=($event.target as HTMLInputElement).value" autocomplete="username" :disabled="loading" />
          <template v-if="adminMode"><label for="admin-password">密码<span>PASSWORD</span></label><input id="admin-password" :value="password" @input="password=($event.target as HTMLInputElement).value" type="password" autocomplete="current-password" :disabled="loading" /></template>
          <p v-if="!adminMode" class="entry-note">同一称呼进入同一空间；同名请加区分。仅用于可信内部环境。</p>
          <p v-if="!adminMode && availability==='unavailable'" class="entry-error" role="status">姓名入口尚未启用，请由管理员更新并启动新版后台。</p>
          <p v-if="availability==='error'" class="entry-error" role="status">暂时无法连接工作站。<button type="button" @click="loadOptions">重新连接</button></p>
          <p v-if="error" class="entry-error" role="alert">{{ error }}</p>
          <button class="entry-submit" type="submit" :disabled="loading || (!adminMode && availability!=='ready')" data-testid="enter-workspace"><span>{{ loading ? '正在打开' : '进入工作空间' }}</span><span aria-hidden="true">↗</span></button>
        </form>
        <button v-if="!entering" class="entry-mode" type="button" :disabled="loading" @click="switchMode">{{ adminMode?'返回姓名登录':'工作站管理' }}</button>
      </section>
    </main>
    <footer class="entry-footer"><span>01 / ARCHIVE</span><span>材料交给我，成果留给你。</span><span>AAA · 卷小助</span></footer>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import client from '../api/client'
const auth=useAuthStore(), router=useRouter()
const name=ref(''),account=ref('admin'),password=ref(''),adminMode=ref(false),loading=ref(false),error=ref('')
const availability=ref('loading'),entering=ref(false)
let disposed=false, entranceTimer:ReturnType<typeof setTimeout>|undefined, finishEntrance:((active:boolean)=>void)|undefined
onBeforeUnmount(()=>{disposed=true;clearTimeout(entranceTimer);finishEntrance?.(false)})
function playEntrance(){
  entering.value=true
  return new Promise<boolean>(resolve=>{finishEntrance=resolve;entranceTimer=setTimeout(()=>{finishEntrance=undefined;resolve(!disposed)},2600)})
}
function switchMode(){adminMode.value=!adminMode.value;error.value='';password.value=''}
async function loadOptions(){
  availability.value='loading'
  try { const {data}=await client.get('/auth/options'); availability.value=data.name_login_enabled?'ready':'unavailable' }
  catch(e:any){availability.value=e.response?.status===404?'unavailable':'error'}
}
onMounted(async()=>{try{const {data}=await client.get('/setup/status');if(data.required){router.replace('/setup');return}}catch{}await loadOptions()})
async function onLogin(){
  if(loading.value)return
  error.value=''
  if(adminMode.value ? (!account.value.trim()||!password.value) : !name.value.trim()){error.value=adminMode.value?'请输入登录标识和密码':'请先填写称呼';return}
  if(!adminMode.value&&availability.value!=='ready')return
  loading.value=true
  try{
    if(adminMode.value) await auth.login(account.value.trim(),password.value)
    else await auth.loginByName(name.value.trim())
    password.value=''
    if(disposed)return
    if(await playEntrance()) await router.replace('/cases')
  }catch(e:any){entering.value=false;const detail=e.response?.data?.detail;error.value=typeof detail==='string'?(detail==='bad credentials'?'登录标识或密码不正确':detail):'未能进入工作空间，请检查连接后重试'}
  finally{loading.value=false}
}
</script>
<style scoped>
.entry-page{--paper:#eeedeb;--ink:#232624;--accent:#c57b38;position:relative;min-height:100svh;overflow:hidden;background:radial-gradient(ellipse at 85% 0%,#ffffffb8,transparent 50%),linear-gradient(130deg,#f2f1ee,#e8e7e4);color:var(--ink)}
.entry-glass{position:absolute;inset:24px 4%;display:flex;justify-content:space-between;pointer-events:none}.entry-glass i{width:12%;border:1px solid #fff8;background:linear-gradient(100deg,#fff2,#fff0)}.entry-glass i:nth-child(2){margin-left:40%;width:20%}
.entry-header{position:absolute;top:44px;left:5%;right:5%;display:flex;justify-content:space-between;align-items:center}.entry-brand{font:600 40px/1 Arial,sans-serif;letter-spacing:.06em}.entry-brand span{display:block;font:9px/1.8 monospace;letter-spacing:.17em;margin-top:9px}.entry-edition{font:10px monospace;letter-spacing:.12em;color:#77776e}
.entry-main{min-height:100svh;padding:170px 24px 120px;display:grid;place-items:center;position:relative}.entry-content{position:relative;z-index:1;width:min(580px,100%);text-align:center}.entry-kicker{font:9px monospace;letter-spacing:.23em;color:#8b897e;margin:0 0 22px}.entry-content h1{position:relative;font-size:38px;letter-spacing:.15em;font-weight:400;margin:0}.entry-content h1>span{position:absolute;color:var(--accent);margin-left:8px;font-family:monospace}.entry-subtitle{font-size:12px;letter-spacing:.23em;color:#767568;margin:15px 0 44px;padding-bottom:24px;border-bottom:1px solid #24242420}
.entry-welcome{width:min(340px,100%);margin:0 auto;min-height:196px;padding-top:18px;animation:entry-reveal .6s ease both}.entry-welcome>span{font-size:14px;letter-spacing:.1em;color:#625e54}.entry-welcome small{display:block;color:#91897c;font-size:11px;letter-spacing:.07em;margin-top:20px}.entry-progress{height:2px;margin:26px auto 0;background:#b8aa9428;overflow:hidden;width:220px}.entry-progress i{display:block;height:100%;width:100%;background:var(--accent);transform-origin:left;animation:entry-progress 2.6s cubic-bezier(.2,.6,.35,1) both}.entry-scan{position:absolute;z-index:2;left:0;right:0;top:0;height:1px;background:linear-gradient(90deg,transparent,#c57b3866,transparent);box-shadow:0 0 18px #c57b3828;pointer-events:none;animation:entry-scan 2.3s ease both}.entering .entry-content h1{font-size:clamp(24px,3.5vw,36px);overflow-wrap:anywhere;letter-spacing:.06em}.entering .entry-orbit{opacity:1}.entering .entry-orbit i{border-top-color:#c57b38;animation-duration:8s}.entering .entry-orbit i+i{animation-duration:5s}.entering .entry-content{animation:entry-arrival 2.6s ease both}@keyframes entry-progress{from{transform:scaleX(0)}to{transform:scaleX(1)}}@keyframes entry-scan{from{top:0;opacity:0}15%{opacity:1}to{top:100%;opacity:0}}@keyframes entry-reveal{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}@keyframes entry-arrival{0%{opacity:.3}18%,90%{opacity:1}100%{opacity:.4}}
.entry-form{width:min(340px,100%);margin:auto;text-align:left}.entry-form label{font-size:12px;color:#74736a;display:flex;justify-content:space-between;margin:18px 0 8px}.entry-form label span{font:9px monospace;letter-spacing:.16em;color:#9b968e}.entry-form input{width:100%;height:46px;border:0;border-top:1px solid #d4d0c7;border-bottom:1px solid #858277;border-radius:0;background:#fff3;padding:10px 12px;font-size:16px;color:#252721}.entry-form input:focus{outline:none;border-bottom-color:var(--accent);box-shadow:0 1px 0 var(--accent)}.entry-form input::placeholder{font-size:12px;color:#a19a8f}.entry-note{font-size:10px;line-height:1.9;color:#898378;margin:12px 0 24px}.entry-submit{width:100%;border:0;background:#242624;color:#f3f1ec;padding:14px 17px;display:flex;align-items:center;justify-content:space-between;font-size:13px;cursor:pointer;transition:background .2s}.entry-submit:hover{background:#3f4239}.entry-submit:disabled{opacity:.45;cursor:default}.entry-error{color:#995923;font-size:12px;line-height:1.8}.entry-error button{background:none;border:0;text-decoration:underline;color:inherit;cursor:pointer}.entry-mode{margin-top:23px;padding:6px;background:none;border:0;color:#827d72;font-size:11px;cursor:pointer}.entry-mode:focus-visible,.entry-submit:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
.entry-footer{position:absolute;bottom:30px;left:5%;right:5%;display:flex;justify-content:space-between;gap:20px;font:9px monospace;color:#8d877d;letter-spacing:.12em}.entry-footer span:nth-child(2){font-size:11px;letter-spacing:.02em}.entry-orbit{position:absolute;width:min(650px,90vw);aspect-ratio:1;left:50%;top:50%;transform:translate(-50%,-50%);pointer-events:none;opacity:0;transition:opacity .3s}.entry-orbit i{position:absolute;inset:0;border:1px solid #b8aa9438;border-top-color:#c57b38;border-radius:50%;animation:entry-orbit 5s linear infinite}.entry-orbit i+i{inset:20px;border-top-color:transparent;border-right-color:#b6ae9a;animation-direction:reverse}.connecting .entry-orbit{opacity:1}@keyframes entry-orbit{to{transform:rotate(360deg)}}
@media(max-width:600px){.entry-header{top:28px;left:26px;right:26px}.entry-brand{font-size:32px}.entry-edition{display:none}.entry-main{padding:150px 28px 110px}.entry-content h1{font-size:30px}.entry-footer{left:26px;right:26px;flex-wrap:wrap;bottom:24px}.entry-footer span:nth-child(2){order:-1;flex-basis:100%;text-align:center}.entry-glass i:nth-child(2){margin-left:10%;width:35%}}
@media(prefers-reduced-motion:reduce){.entry-orbit i,.entry-welcome,.entry-progress i,.entry-scan,.entering .entry-content{animation:none}.entry-scan{display:none}.entry-orbit,.entry-submit{transition:none}}
</style>
