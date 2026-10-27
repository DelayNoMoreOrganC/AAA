<template>
  <div ref="wrapRef" class="docx-review-wrap">
    <div v-if="loading" class="docx-loading">正在加载 Word 文档…</div>
    <div v-else-if="error" class="docx-error">{{ error }}</div>
    <div v-else-if="docBuffer" class="docx-paper-frame">
      <DocxEditor
        ref="editorRef"
        :document-buffer="docBuffer"
        :document-name="templateName"
        :show-file-open="false"
        :initial-zoom="initialZoom"
        :on-change="onDocumentChange"
        class="docx-editor-pane"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { DocxEditor } from '@eigenpal/docx-editor-vue'
import '@eigenpal/docx-editor-vue/styles.css'
import client from '../api/client'

const A4_PAGE_WIDTH_PX = 794 // 210mm @ 96dpi

const props = defineProps<{ taskId: string; templateName: string; active: boolean }>()
const wrapRef = ref<HTMLElement | null>(null)
const editorRef = ref<any>(null)
const docBuffer = ref<ArrayBuffer | null>(null)
const loading = ref(false)
const error = ref('')
const dirty = ref(false)
const loaded = ref(false)
let changeVersion = 0
function onDocumentChange() { if (loaded.value) { dirty.value = true; changeVersion++ } }
function isLoaded() { return loaded.value && !!editorRef.value }
function hasUnsavedChanges() { return dirty.value }
const wrapWidth = ref(0)

const initialZoom = computed(() => {
  const w = wrapWidth.value
  if (!w) return 1
  const fit = (w - 16) / A4_PAGE_WIDTH_PX
  return Math.min(1, Math.max(0.55, fit))
})

let resizeObserver: ResizeObserver | null = null

function updateWrapWidth() {
  wrapWidth.value = wrapRef.value?.clientWidth ?? 0
}

function syncEditorZoom() {
  const ed = editorRef.value
  if (ed?.setZoom) ed.setZoom(initialZoom.value)
}

async function loadDocx() {
  if (!props.active || loaded.value || loading.value) return
  loading.value = true
  error.value = ''
  docBuffer.value = null
  try {
    const { data } = await client.get(
      '/tasks/' + props.taskId + '/docx/' + encodeURIComponent(props.templateName),
      { responseType: 'arraybuffer' },
    )
    docBuffer.value = data
    await nextTick()
    syncEditorZoom()
    loaded.value = true
    dirty.value = false
  } catch (e: any) {
    error.value = e.response?.data?.detail || '无法加载文档，请确认表格已生成'
  } finally {
    loading.value = false
  }
}

async function saveDocx(): Promise<boolean> {
  const ed = editorRef.value
  if (!ed?.save) return false
  try {
    const submittedVersion = changeVersion
    const buf: ArrayBuffer = await ed.save()
    if (!buf || !buf.byteLength) return false
    const blob = new Blob([buf], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
    const fd = new FormData()
    fd.append('file', blob, props.templateName + '.docx')
    await client.put(
      '/tasks/' + props.taskId + '/docx/' + encodeURIComponent(props.templateName),
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    if (changeVersion === submittedVersion) dirty.value = false
    return true
  } catch {
    return false
  }
}

defineExpose({ saveDocx, loadDocx, isLoaded, hasUnsavedChanges })

watch(initialZoom, () => syncEditorZoom())
watch(() => [props.templateName, props.active], () => { if (props.active) loadDocx() }, { immediate: true })

onMounted(() => {
  updateWrapWidth()
  if (wrapRef.value) {
    resizeObserver = new ResizeObserver(() => {
      updateWrapWidth()
      syncEditorZoom()
    })
    resizeObserver.observe(wrapRef.value)
  }
  if (props.active) loadDocx()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.docx-review-wrap {
  width: 100%;
  max-height: 85vh;
  margin: 0;
  padding: 4px 8px 8px;
  border: 1px solid #dcdfe6;
  border-top: none;
  border-radius: 0 0 4px 4px;
  overflow: auto;
  background: #e8eaed;
  box-sizing: border-box;
}

.docx-paper-frame {
  width: 210mm;
  max-width: 100%;
  margin: 0 auto;
  background: #fff;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.docx-editor-pane {
  width: 100%;
}

.docx-loading,
.docx-error {
  padding: 16px 20px;
  color: #606266;
  text-align: center;
  min-width: 240px;
}

.docx-error {
  color: #f56c6c;
}
</style>
