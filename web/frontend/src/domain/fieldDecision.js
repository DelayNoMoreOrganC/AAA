import { createRequestId } from './workflow.js'

export function hasFieldConflict(item, unresolvedOnly = false) {
  return (item?.members || []).some(issue => issue.kind === 'field_conflict' && (!unresolvedOnly || issue.detail?.fact_resolved !== true))
}

// Only the server's checked projection resolves a factual conflict. Reading a
// warning, an arbitrary raw `resolved` flag, or a form alias is not that proof.
function fieldDecisionBase(task, item, allowBlank = false) {
  if (!task || !['awaiting_review', 'done'].includes(task.status) || task.source_changed) return null
  const conflicts = (item?.members || []).filter(issue => issue.kind === 'field_conflict' && issue.detail?.fact_resolved !== true)
  if (!conflicts.length) return null
  const fields = new Set(conflicts.map(issue => issue.detail?.field))
  if (fields.size !== 1) return null
  const field = [...fields][0]
  if (typeof field !== 'string' || !field.trim() || field.startsWith('_') || field.length > 80 || (item.field && item.field !== field)) return null
  if (!Object.hasOwn(task.fields || {}, field)) return null
  const value = task.fields[field]
  if (typeof value !== 'string' || (!allowBlank && !value.trim()) || value.length > 20000 || !Number.isInteger(task.revision) || task.revision < 1 || !/^[a-f0-9]{64}$/.test(task.source_version || '')) return null
  return { action: 'accept_current', field, current_value: value, expected_revision: task.revision, source_version: task.source_version }
}

export function currentFieldDecision(task, item) { return fieldDecisionBase(task, item) }

export function candidateFieldDecisions(task, item) {
  const target = fieldDecisionBase(task, item, true)
  if (!target) return []
  return (item?.field_candidates || []).filter(row => typeof row?.value === 'string' && row.value.trim() && row.value.length <= 20000 && Array.isArray(row.sources) && row.sources.length)
    .map(row => ({ ...target, action: 'accept_candidate', selected_value: row.value, sources: row.sources }))
}

// An uncertain response retains this exact request in memory. Only an explicit
// successful refresh lets the user make a new decision; there is no auto retry.
export function createFieldDecision({ request, onChange = () => {}, newRequestId = createRequestId }) {
  const initial = () => ({ busy: false, error: '', needsRefresh: false, retryable: false })
  let state = initial(), pending = null, generation = 0, controller = null
  const publish = () => onChange({ ...state })
  function reset() { generation++; controller?.abort(); controller = null; pending = null; state = initial(); publish() }
  function refreshed() { if (state.busy) return; pending = null; state = initial(); publish() }
  async function accept(target) {
    if (state.busy || state.needsRefresh || !target) return null
    if (pending && JSON.stringify(pending.target) !== JSON.stringify(target)) {
      state = { ...state, needsRefresh: true, retryable: false, error: '字段或任务版本已变化，请刷新后重新核对；此前的确认不会自动重发。' }; publish(); return null
    }
    const current = generation
    state = { ...state, busy: true, error: '' }; publish()
    try {
      if (!pending) pending = { target: { ...target }, body: { ...target, request_id: newRequestId() } }
      controller = new AbortController()
      const data = await request({ ...pending.body }, controller.signal)
      if (current !== generation) return null
      if (!data || !Number.isInteger(data.revision) || data.revision <= target.expected_revision || data.source_version !== target.source_version) throw new Error('unverified response')
      pending = null; state = initial(); publish(); return data
    } catch (error) {
      if (current !== generation) return null
      const stale = error?.response?.status === 409
      const detail = error?.response?.data?.detail
      state = { busy: false, needsRefresh: stale, retryable: !stale && !!pending,
        error: typeof detail === 'string' && detail.trim() ? detail + (stale ? ' 请刷新后重新核对。' : '') : error?.code === 'secure_random_unavailable' ? error.message : '尚未取得确认结果，当前内容仍保留。可用原请求编号重试，或刷新核对工作站状态。' }
      publish(); return null
    } finally {
      if (current === generation) { controller = null; if (state.busy) { state.busy = false; publish() } }
    }
  }
  return { accept, reset, refreshed }
}
