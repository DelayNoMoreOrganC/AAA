export const classificationTargetKey = option => JSON.stringify([option.doc_type, option.catalog_seq])
export function locateDocumentUnit(documents, source) {
  const page = Number(source?.page_start || source?.page)
  if (!source?.file_id || !Number.isInteger(page) || page < 1) return null
  const matches = documents.filter(item => item.file_id === source.file_id && page >= item.page_start && page <= item.page_end)
  return matches.length === 1 ? matches[0] : null
}
export function documentClassificationDirty(state) {
  if (!state.draft) return false
  const document = state.documents.find(item => item.unit_key === state.draft.unit_key)
  return !!state.draft.reason || !document || state.draft.target !== classificationTargetKey(document)
}

export function documentClassificationError(error) {
  if (error?.response?.status === 409) return '任务版本、材料或处理状态已变化。请刷新文书清单、核对后再保存；你的选择和原因仍保留。'
  if (error?.response?.status === 404) return '当前文书不可访问，请返回案件检查材料和访问权限。'
  return '未能保存分类，请恢复连接后重试。你的选择和原因仍保留。'
}

function snapshot(data) {
  if (!Number.isInteger(data?.revision) || !Array.isArray(data.documents) || !Array.isArray(data.options)) throw new Error('Invalid document snapshot')
  return {
    revision: data.revision, documents: data.documents, options: data.options,
    editable: data.editable === true, source_changed: data.source_changed === true,
    blocked_reason: typeof data.blocked_reason === 'string' ? data.blocked_reason : '',
  }
}

// Drafts remain in page memory. A stale revision never silently becomes a write to a new revision.
export function createDocumentClassification({ read, write, beforeWrite = () => '', onSaved = () => {}, onChange = () => {} }) {
  let taskId = '', generation = 0, controller = null, disposed = false, observedRevision = 0
  let state = initialState()
  function initialState() { return { revision: null, documents: [], options: [], editable: false, source_changed: false, blocked_reason: '', loading: false, saving: false, stale: false, error: '', message: '', draft: null } }
  const publish = () => onChange({ ...state, documents: [...state.documents], options: [...state.options], draft: state.draft ? { ...state.draft } : null })
  const valid = current => !disposed && current === generation

  function reset(id) {
    generation++; controller?.abort(); controller = null
    taskId = String(id || ''); observedRevision = 0; state = initialState(); publish()
  }
  function invalidate(revision) {
    observedRevision = Math.max(observedRevision, Number(revision) || 0)
    if (state.revision !== null && observedRevision > state.revision) { state.stale = true; publish() }
  }
  async function load() {
    if (disposed || !taskId || state.loading || state.saving) return false
    const current = generation
    controller = new AbortController(); state.loading = true; state.error = ''; publish()
    try {
      const data = snapshot(await read(taskId, controller.signal))
      if (!valid(current)) return false
      const draft = state.draft
      Object.assign(state, data, { stale: observedRevision > data.revision })
      if (draft && !data.documents.some(item => item.unit_key === draft.unit_key)) {
        state.draft = null; state.error = '该文书已不在当前清单中，请重新选择。'
      }
      return true
    } catch (error) {
      if (!valid(current)) return false
      state.error = '文书清单读取失败。已填写的内容仍保留，请重试。'
      return false
    } finally { if (valid(current)) { state.loading = false; controller = null; publish() } }
  }
  function select(unitKey) {
    if (state.saving || state.loading || state.draft) return false
    const document = state.documents.find(item => item.unit_key === unitKey)
    if (!document) return false
    state.draft = { unit_key: unitKey, target: classificationTargetKey(document), reason: '' }
    state.error = ''; state.message = ''; publish(); return true
  }
  function updateDraft(values) {
    if (!state.draft || state.saving) return
    if (typeof values.target === 'string') state.draft.target = values.target
    if (typeof values.reason === 'string') state.draft.reason = values.reason
    publish()
  }
  function cancel() { if (!state.saving) { state.draft = null; state.error = ''; publish() } }
  async function save() {
    if (disposed || !taskId || state.saving || state.loading || !state.draft) return false
    if (state.stale || !state.editable || state.source_changed) {
      state.error = state.stale ? '清单版本已变化，请刷新文书清单并核对后重试。' : state.blocked_reason || '当前任务不能调整分类，请完成正在进行的处理后重试。'
      publish(); return false
    }
    const draft = { ...state.draft }, target = state.options.find(item => classificationTargetKey(item) === draft.target)
    const reason = draft.reason.trim()
    if (!target || !reason || reason.length > 1000) { state.error = '请选择清单中的归属，并填写 1 至 1000 字的核对原因。'; publish(); return false }
    const current = generation
    state.saving = true; state.error = ''; state.message = ''; publish()
    try {
      const blocked = await beforeWrite(state.revision)
      if (!valid(current)) return false
      if (blocked) { state.error = blocked; return false }
      if (state.stale) { state.error = '任务版本已变化，请刷新文书清单并核对后重试。'; return false }
      controller = new AbortController()
      const result = await write(taskId, draft.unit_key, {
        expected_revision: state.revision, doc_type: target.doc_type, catalog_seq: target.catalog_seq, reason,
      }, controller.signal)
      if (!valid(current)) return false
      const data = snapshot(result)
      if (!result.task || result.task.revision !== data.revision) throw new Error('Missing updated task')
      const message = data.revision === state.revision ? '当前分类与保存值一致，无需变更。确认状态未因本次操作改变。' : '分类草稿已保存，目录已更新。更新草稿后即可下载；正式归档仍需最终确认。'
      Object.assign(state, data, { draft: null, stale: observedRevision > data.revision, message })
      onSaved(result.task)
      return true
    } catch (error) {
      if (!valid(current)) return false
      state.error = documentClassificationError(error)
      if (error?.response?.status === 409) state.stale = true
      return false
    } finally { if (valid(current)) { state.saving = false; controller = null; publish() } }
  }
  function dispose() { disposed = true; generation++; controller?.abort(); state = initialState() }
  return { reset, load, invalidate, select, updateDraft, cancel, save, dispose }
}
