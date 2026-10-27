// UI decisions use persisted task facts; lack of rule verification is never a pass.
export function taskPresentation(task) {
  if (!task) return { title: '正在读取任务', label: '连接中' }
  if (task.status === 'failed') return { title: '有一件事需要处理', label: '处理未完成' }
  if (task.has_archive && (task.delivery_kind === 'draft' || task.status === 'awaiting_review')) return { title: '档案草稿已生成', label: '草稿可下载' }
  if (task.has_archive) return task.formal_ready === true && !task.preview_draft
    ? { title: '归档成果已生成', label: '已生成' }
    : { title: '体验归档已完成', label: '规则待核验' }
  if (task.status === 'awaiting_review') return { title: '材料已整理，可以生成档案草稿', label: '待生成草稿' }
  if (task.status === 'done') return { title: '核对草稿已保存', label: '草稿' }
  return { title: '助理正在整理案件材料', label: '处理中' }
}

export function unresolvedIssues(issues, decisions) {
  return (issues || []).filter(issue => issue.blocking && (issue.kind === 'field_conflict'
    ? issue.detail?.fact_resolved !== true
    : decisions[issue.id]?.action !== 'acknowledged' || !String(decisions[issue.id]?.reason || '').trim()))
}

// Completion alone cannot hide unresolved work or locally edited decisions.
export function canSummarizeCompletedReview(task, unresolvedCount, hasUnsaved) {
  return task?.status === 'done' && task.has_archive === true && unresolvedCount === 0 && !hasUnsaved
}

export function isHistoricalTask(task, latestTaskId) {
  return !!task && (!!task.source_changed || (latestTaskId != null && String(task.id) !== String(latestTaskId)))
}

// A partial import must remain visible. The caller decides when to start analysis.
export async function importFiles(files, capabilities, upload, onProgress = () => {}) {
  const failed = [], imported = []
  for (let index = 0; index < files.length; index++) {
    const file = files[index]
    const name = file.webkitRelativePath || file.name
    const extension = '.' + file.name.split('.').pop().toLowerCase()
    let message = ''
    if (!capabilities.supported_extensions.includes(extension)) message = '此格式暂不支持'
    else if (file.size > capabilities.max_upload_mb * 1024 * 1024) message = '超过单份 ' + capabilities.max_upload_mb + ' MB 限制'
    else {
      try { await upload(file); imported.push(file) }
      catch (error) { message = typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error?.code === 'secure_random_unavailable' ? error.message : '导入失败，请重试' }
    }
    if (message) failed.push({ file, name, message })
    onProgress(index + 1, files.length, name)
  }
  return { imported, failed }
}

// A new selection is not permission to discard a previous failed selection.
// Use the File object's identity: filenames alone can refer to different bytes.
// Retried entries are replaced by their latest result; successes leave the queue.
export function reconcileImportFailures(previous, attemptedFiles, failed) {
  const attempted = new Set(attemptedFiles), seen = new Set()
  return [...previous.filter(item => !attempted.has(item.file)), ...failed]
    .filter(item => { if (seen.has(item.file)) return false; seen.add(item.file); return true })
}

// randomUUID requires a secure context; getRandomValues also supports LAN HTTP.
// Both paths use Web Crypto, and unavailable cryptography is an explicit error.
export function createRequestId(cryptoSource = globalThis.crypto) {
  if (typeof cryptoSource?.randomUUID === 'function') return cryptoSource.randomUUID()
  if (typeof cryptoSource?.getRandomValues !== 'function') {
    const error = new Error('浏览器无法生成安全请求编号，请使用支持安全随机数的浏览器或联系管理员配置 HTTPS。')
    error.code = 'secure_random_unavailable'
    throw error
  }
  const bytes = new Uint8Array(16)
  cryptoSource.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-')
}

// Keep a queued File's key across lost-response retries. A newly selected File
// is a separate user action. No keys or bytes enter browser storage.
export function createImportRequestKeys() {
  const keys = new WeakMap()
  return file => {
    if (!keys.has(file)) keys.set(file, createRequestId())
    return keys.get(file)
  }
}

export function phaseDescription(task) {
  const phases = {
    queued: '材料已接收，等待处理', analyzing: '正在读取材料、识别文书并整理字段',
    needs_input: '异常已集中列出，等待你核对', ready_to_finalize: '草稿已准备好，等待最后确认',
    rendering: '正在生成表格文书', assembling: '正在编排完整卷宗',
    draft_ready: '档案草稿已生成，补充材料可随后完善', verifying: '正在校验页数和整理成果包', completed: '成果已保存', failed: '本次处理未完成',
  }
  return phases[task?.phase] || task?.stage || '正在读取任务状态'
}

// Refresh server acknowledgements without overwriting a user's unfinished edits.
export function reconcileDecisions(keys, current, baseline, incoming) {
  const draft = {}, saved = {}
  for (const key of keys) {
    const server = { action: incoming[key]?.action || 'pending', reason: incoming[key]?.reason || '' }
    saved[key] = server
    draft[key] = current[key] && JSON.stringify(current[key]) !== JSON.stringify(baseline[key]) ? current[key] : server
  }
  return { draft, saved }
}

export function archiveCoverTitle(caseType) {
  if (['nonlit', 'counsel', 'arbitration', 'consultation', '非诉', '顾问', '法律顾问', '仲裁', '咨询代书', '法律咨询与代书'].includes(caseType)) return '律师业务档案卷宗（非诉讼类）'
  if (['civil', 'criminal', 'admin', '民事', '刑事', '行政'].includes(caseType)) return '律师业务档案卷宗（诉讼类）'
  return '律师业务档案卷宗'
}

export function formatShanghaiTime(value) {
  if (!value) return ''
  const text = String(value).trim().replace(' ', 'T')
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : text + 'Z')
  if (Number.isNaN(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date)
}

export function canDeferMissing(item) {
  return !(item.legal_requirement_verified === true && item.requirement === 'required')
}

export function canLocateEvidence(entry) {
  return entry.method !== 'human' && !!entry.file_id && Number.isInteger(Number(entry.page)) && Number(entry.page) > 0
}

/** Display one source-page card without modifying stored provenance or its status. */
export function evidencePageCards(entries = []) {
  const cards = [], pages = new Map()
  for (const entry of Array.isArray(entries) ? entries : []) {
    if (!entry || typeof entry !== 'object') continue
    const key = canLocateEvidence(entry)
      ? JSON.stringify([entry.file_id, Number(entry.page), entry.historical === true]) : null
    let card = key && pages.get(key)
    if (!card) {
      card = { ...entry, entries: [], quotes: [] }
      cards.push(card)
      if (key) pages.set(key, card)
    }
    card.entries.push(entry)
    if (typeof entry.quote === 'string' && entry.quote.trim()) {
      const compact = value => value.replace(/\s+/gu, '')
      const quote = compact(entry.quote)
      if (!card.quotes.some(value => compact(value).includes(quote))) {
        card.quotes = card.quotes.filter(value => !quote.includes(compact(value)))
        card.quotes.push(entry.quote)
      }
    }
  }
  return cards
}

// Report the literal completed fragment count, never convert it into page/overall progress.
export function parseAgentFragmentProgress(line) {
  if (typeof line !== 'string') return null
  const match = line.match(/来源核对完成[，,]\s*已处理\s*(\d+)\s*\/\s*(\d+)\s*个页面片段/)
  if (!match) return null
  const done = Number(match[1]), total = Number(match[2])
  return Number.isSafeInteger(done) && Number.isSafeInteger(total) && total > 0 && done >= 0 && done <= total ? { done, total } : null
}

