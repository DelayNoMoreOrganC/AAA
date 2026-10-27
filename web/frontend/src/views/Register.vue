<template>
  <div class="register-wrap">
    <el-card class="register-card">
      <h2 class="register-title">注册案件归档系统</h2>
      <el-alert type="info" :closable="false" style="margin-bottom: 18px">
        每个注册账号会创建独立工作空间，案件和文件与其他用户隔离。
      </el-alert>
      <el-form :model="form" label-position="top" @submit.prevent="onRegister">
        <el-form-item label="律所或团队名称">
          <el-input v-model="form.org_name" placeholder="请输入律所或团队名称" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.display_name" placeholder="请输入姓名" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="3–32位字母、数字、点、横线或下划线" :prefix-icon="User" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="至少8位，同时包含字母和数字" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="form.confirm" type="password" placeholder="请再次输入密码" :prefix-icon="Lock" show-password @keyup.enter="onRegister" />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="onRegister">注册并登录</el-button>
        <div class="login-link">已有账号？<router-link to="/login">返回登录</router-link></div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(false)
const form = reactive({ org_name: '', display_name: '', username: '', password: '', confirm: '' })

async function onRegister() {
  if (!form.org_name || !form.username || !form.password) {
    ElMessage.warning('请填写律所或团队名称、用户名和密码')
    return
  }
  if (form.password !== form.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    await auth.register({
      org_name: form.org_name,
      display_name: form.display_name,
      username: form.username,
      password: form.password,
    })
    ElMessage.success('注册成功')
    router.push('/cases')
  } catch (e: any) {
    const detail = e.response?.data?.detail
    const message = Array.isArray(detail) ? detail.map((x: any) => x.msg).join('；') : detail
    ElMessage.error(message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-wrap { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 30px 0; background: linear-gradient(135deg, #1d2129 0%, #2a3548 100%); }
.register-card { width: 420px; }
.register-title { text-align: center; margin-bottom: 22px; color: #1d2129; }
.login-link { margin-top: 16px; text-align: center; color: #606266; font-size: 14px; }
</style>
