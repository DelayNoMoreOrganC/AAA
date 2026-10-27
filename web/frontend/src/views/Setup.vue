<template>
<div class="auth-page"><section class="auth-form" v-loading="checking"><span class="brand-mark">GD</span><h1>欢迎使用归档助理</h1><p>为这台工作站建立首个管理员账号。</p>
<el-alert v-if="!setupToken" type="warning" :closable="false" title="请在工作站本机打开首次启动链接" description="初始化需要本机启动程序提供的一次性链接。" style="margin-bottom:20px" />
<el-form label-position="top" @submit.prevent="submit"><el-form-item label="律所名称"><el-input v-model="form.org_name" placeholder="输入律所名称" /></el-form-item><el-form-item label="管理员账号"><el-input v-model="form.username" autocomplete="username" placeholder="3–32 位字母、数字或 . _ -" /></el-form-item><el-form-item label="管理员密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="至少 12 位，包含字母和数字" /></el-form-item><el-form-item label="成果保存目录（可选）"><el-input v-model="form.output_directory" placeholder="留空则保存在工作站默认成果目录" /><span class="muted">填写工作站本机的文件夹路径，之后可由管理员修改。</span></el-form-item><el-button type="primary" native-type="submit" :disabled="!setupToken" :loading="saving" style="width:100%">创建工作站</el-button></el-form>
<el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-top:16px" /></section></div>
</template>
<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import client from '../api/client'
const router=useRouter(), form=reactive({org_name:'',username:'',password:'',output_directory:''}), saving=ref(false), checking=ref(true), error=ref('')
const setupToken=new URLSearchParams(window.location.hash.slice(1)).get('token')||''
if(window.location.hash)window.history.replaceState(window.history.state,'',window.location.pathname+window.location.search)
onMounted(async()=>{try{const {data}=await client.get('/setup/status');if(!data.required)router.replace('/login')}catch{error.value='无法连接工作站，请确认服务已启动'}finally{checking.value=false}})
async function submit(){error.value='';if(!form.org_name.trim()||!form.username.trim()||form.password.length<12){error.value='请填写律所、账号，并设置至少 12 位的密码';return}if(!/^[A-Za-z0-9_.-]{3,32}$/.test(form.username.trim())){error.value='账号需为 3–32 位字母、数字或 . _ -';return}if(!/[A-Za-z]/.test(form.password)||!/[0-9]/.test(form.password)||new TextEncoder().encode(form.password).length>72){error.value='密码需同时含字母和数字，且不超过 72 字节';return}if(form.org_name.trim().length<2){error.value='请填写至少 2 个字的律所名称';return}if(!setupToken)return;saving.value=true;try{await client.post('/setup',{...form,org_name:form.org_name.trim(),username:form.username.trim(),display_name:form.username.trim(),setup_token:setupToken});form.password='';router.replace('/login')}catch(e:any){error.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:'初始化失败，请检查信息后重试'}finally{saving.value=false}}
</script>

