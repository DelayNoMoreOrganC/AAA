<template>
  <div v-loading="loading">
    <div class="page-header">
      <h3 style="margin:0">用户管理</h3>
      <el-button type="primary" :icon="Plus" @click="openCreate">添加用户</el-button>
    </div>
    <p style="font-size:12px;color:#88937d;line-height:1.8">本站管理员仅管理本机构账号与案件；普通用户仅访问自己创建的案件。</p>
    <el-table :data="users" stripe style="width: 100%">
      <el-table-column prop="username" label="用户名" width="160" />
      <el-table-column prop="display_name" label="姓名" width="140" />
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">{{ row.role === 'admin' ? '管理员' : '律师' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="toggleActive(row)">{{ row.is_active ? '禁用' : '启用' }}</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showCreate" title="添加用户" width="440px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width:100%">
            <el-option label="律师" value="lawyer" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '../api/client'

const loading = ref(false)
const users = ref([])
const showCreate = ref(false)
const form = reactive({ username: '', display_name: '', password: '', role: 'lawyer' })

async function load() {
  loading.value = true
  try { const { data } = await client.get('/admin/users'); users.value = data }
  catch { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

function openCreate() { Object.assign(form, { username: '', display_name: '', password: '', role: 'lawyer' }); showCreate.value = true }

async function onCreate() {
  if (!form.username || !form.password) { ElMessage.warning('请填写用户名和密码'); return }
  try {
    await client.post('/admin/users', { ...form })
    showCreate.value = false
    ElMessage.success('已创建')
    await load()
  } catch { ElMessage.error('创建失败') }
}

async function toggleActive(row: any) {
  try { await client.put('/admin/users/' + row.id, { is_active: !row.is_active }); await load() }
  catch { ElMessage.error('操作失败') }
}

async function onDelete(row: any) {
  try {
    await ElMessageBox.confirm('确认删除用户 ' + row.username + '？', '提示', { type: 'warning' })
    await client.delete('/admin/users/' + row.id)
    await load()
  } catch { /* cancelled */ }
}

onMounted(load)
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
</style>
