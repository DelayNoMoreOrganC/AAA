import { unresolvedMissing,isRequiredMissing } from './review.js'
import { unresolvedIssues } from './workflow.js'
import { issueCardSummary } from './issueReview.js'
import { draftFieldNeedsGeneratedForm,draftFieldTemplate } from './sourceForms.js'
import { materialSupplementState } from './materialCompleteness.js'

export function materialChecklistCount(task) {
  const state = materialSupplementState(task?.catalog_status || [])
  return state.required.length + state.applicability.length + state.optional.length
}

export function buildDecisionQueue(task,missingDecisions={},issueDecisions={}) {
  const missing=(task?.catalog_status||[]).filter(item=>!item.found).map(item=>({key:'missing:'+item.seq,kind:'missing',source:item,members:[item],title:item.name||'目录第 '+item.seq+' 项',type:isRequiredMissing(item)?'补充必要材料':'材料缺项',location:'',resolved:unresolvedMissing([item],missingDecisions).length===0,reasons:[],sources:[],field_targets:[]}))
  const issues=(task?.issues||[]).filter(issue=>issue.blocking).map(issue=>({key:'issue:'+issue.id,kind:'issue',source:issue,members:[issue],...issueCardSummary(issue),title:issue.message,resolved:unresolvedIssues([issue],issueDecisions).length===0,reasons:[{id:issue.id,message:issue.message,kind:issue.kind}],sources:validSources([issue.detail,...(issue.detail?.pages||[])]),field_targets:[]}))
  const raw=[...missing,...issues],used=new Set(),grouped=[]
  for(const group of Array.isArray(task?.review_queue)?task.review_queue:[]){
    if(!['missing','issue'].includes(group.kind))continue
    const ids=group.kind==='issue'?group.issue_ids:group.catalog_seqs
    if(!Array.isArray(ids))continue
    const entries=raw.filter(item=>item.kind===group.kind&&!used.has(item.key)&&ids.map(String).includes(String(group.kind==='issue'?item.source.id:item.source.seq)))
    if(!entries.length)continue
    entries.forEach(item=>used.add(item.key))
    grouped.push({...entries[0],server:true,key:String(group.key||entries[0].key),title:group.title||entries[0].title,members:entries.flatMap(item=>item.members),resolved:entries.every(item=>item.resolved),reasons:entries.flatMap(item=>item.reasons),sources:validSources(group.sources||[]),field:group.field||'',field_candidates:Array.isArray(group.field_candidates)?group.field_candidates:[],field_targets:(group.field_targets||[]).filter(item=>typeof item?.template_name==='string'&&typeof item.field==='string')})
  }
  // Old tasks have no queue. Group only an exact field identity, never merely
  // a shared page or catalogue slot (those do not prove the same material).
  for(const item of raw.filter(item=>!used.has(item.key))){
    const field=item.kind==='issue'?item.source.detail?.field:''
    const same=field&&grouped.find(group=>group.kind==='issue'&&group.field===field&&!group.server)
    if(same){same.members.push(...item.members);same.reasons.push(...item.reasons);same.sources=validSources([...same.sources,...item.sources]);same.resolved= same.resolved&&item.resolved}
    else grouped.push({...item,field:field||''})
  }
  return [...grouped.filter(item=>item.kind==='missing'&&item.members.some(isRequiredMissing)),...grouped.filter(item=>item.kind==='issue'),...grouped.filter(item=>item.kind==='missing'&&!item.members.some(isRequiredMissing))]
}

function validSources(values){const seen=new Set();return values.filter(item=>item&&typeof item.file_id==='string'&&Number.isInteger(Number(item.page))&&Number(item.page)>0).map(item=>({file_id:item.file_id,page:Number(item.page),filename:item.filename||'来源材料'})).filter(item=>{const key=item.file_id+':'+item.page;if(seen.has(key))return false;seen.add(key);return true})}

// Priority is presentation only: do not mutate decisions or bypass final gates.
export function reviewQueueSections(queue=[]) {
  const attention=queue.filter(item=>item.kind==='issue'||item.members.some(isRequiredMissing))
  const materials=queue.filter(item=>!attention.includes(item))
  return {attention,materials,attentionCount:attention.filter(item=>!item.resolved).length,
    materialCount:materials.filter(item=>!item.resolved).length}
}

export function selectDecision(queue,current=null,preferUnresolved=false) {
  if(!preferUnresolved&&queue.some(item=>item.key===current))return current
  return queue.find(item=>!item.resolved)?.key||null
}

export function stepDecision(queue,current,direction=1,unresolvedOnly=false) {
  if(!queue.length)return null
  const at=queue.findIndex(item=>item.key===current)
  for(let step=1;step<=queue.length;step++){
    const candidate=queue[(Math.max(at,0)+step*direction+queue.length*2)%queue.length]
    if(!unresolvedOnly||!candidate.resolved)return candidate.key
  }
  return null
}

// Call only after a successful save, with the server's persisted decisions.
// A note cannot resolve a field conflict; passive refreshes never advance.
export function decisionAfterSave(queue,current,previous=[]) {
  const item=queue.find(item=>item.key===current)
  if(item&&!item.resolved)return current
  if(item)return stepDecision(queue,current,1,true)
  const at=previous.findIndex(item=>item.key===current)
  if(at>=0){
    for(let step=1;step<=previous.length;step++){
      const key=previous[(at+step)%previous.length].key
      if(queue.some(item=>item.key===key&&!item.resolved))return key
    }
  }
  return selectDecision(queue,null,true)
}

export function defaultCaseTitle(files) {
  const first=files?.[0]
  return String(first?.webkitRelativePath?.split('/')[0]||first?.name?.replace(/\.[^.]+$/,'')||'新案件').slice(0,150)
}

export function formDraftSummary(task) {
  const entries=Object.entries(task?.fields?._form_drafts?.fields||{})
  const allowed=['generated','insufficient','human_modified','preserved']
  const fields=['案情简介','立案审批日期','法院文件清单','委托人联系地址及电话','案件或项目名称']
  return entries.filter(([field,entry])=>fields.includes(field)&&entry&&allowed.includes(entry.status)&&draftFieldNeedsGeneratedForm(task?.fields,field)).map(([field,entry])=>{
    const needsShorterValue=entry.status==='insufficient'&&Array.isArray(entry.reason_codes)&&entry.reason_codes.includes('draft_too_long_for_original_cell')
    return {field,status:entry.status,sourceCount:Number.isInteger(entry.source_count)&&entry.source_count>=0?entry.source_count:null,label:needsShorterValue?'待简要填写':({generated:'有依据草稿',insufficient:'待补全依据',human_modified:'人工值已保留',preserved:'已有值待核对'})[entry.status]}
  })
}

export function pendingFormEntries(task){
  return formDraftSummary(task).filter(item=>item.status==='insufficient').map(item=>({
    ...item,template:draftFieldTemplate(item.field),label:item.field==='立案审批日期'?'立案日期':item.field,
  })).filter(item=>item.template)
}

