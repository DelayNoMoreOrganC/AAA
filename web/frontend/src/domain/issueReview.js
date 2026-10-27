import { unresolvedIssues } from './workflow.js'

// Preserve the reader's choice during polling and editing. Opening a card never
// acknowledges it, and resolving it does not collapse an unfinished explanation.
export function reconcileIssueExpansion(issues, decisions={}, selected) {
  const blocking=(issues||[]).filter(issue=>issue.blocking)
  if(!blocking.length)return undefined
  if(selected===null || blocking.some(issue=>issue.id===selected))return selected
  return unresolvedIssues(blocking,decisions)[0]?.id ?? null
}

export function toggleIssueExpansion(selected,id) { return selected===id?null:id }

export function issueCardSummary(issue) {
  const types={field_conflict:'字段冲突',classification:'文书归属',classification_stale:'分类需重核',ocr:'页面识别',template:'系统表格',outcome:'办理结果',empty_fields:'案件信息'}
  const detail=issue?.detail||{},locations=[]
  if(typeof detail.field==='string'&&detail.field.trim())locations.push('字段：'+detail.field.trim())
  let source=typeof detail.filename==='string'?detail.filename.trim():''
  const start=Number(detail.page_start??detail.page),end=Number(detail.page_end)
  if(Number.isSafeInteger(start)&&start>0){
    const pages='第 '+start+(Number.isSafeInteger(end)&&end>start?'—'+end:'')+' 页'
    source=source?source+' · '+pages:pages
  }
  if(source)locations.push(source)
  return {type:types[issue?.kind]||'材料核对',message:issue?.message||'请核对本项材料',location:locations.join(' · ')}
}
