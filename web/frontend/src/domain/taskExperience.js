import { isRequiredMissing } from './review.js'

// A shortcut to the existing confirmation flow, never a substitute for server checks.
export function archiveConfirmationAction(task,{historical=false,locked=false,documentDraft=false,unresolved=0,uploadBlocked=false}={}){
  const visible=task?.has_archive===true && task.delivery_kind==='draft' && !historical
    && ['awaiting_review','done'].includes(task.status)
  const disabled=!visible || locked || documentDraft || unresolved>0 || uploadBlocked
    || task.can_assemble!==true || task.source_changed===true
  return {visible,disabled,label:'确认成卷'}
}

// Display-only state. No recognition, acknowledgement, or model request is made here.
export function companionPresentation(task,{error=false,historical=false,consent=false,unresolved=0,materials=0}={}){
  if(error||task?.status==='failed'||task?.error)return {state:'error',label:'整理遇到问题，请查看页面提示。',short:'需要处理'}
  if(historical)return {state:'question',label:'正在查看历史成果。',short:'历史成果'}
  if(task?.source_changed)return {state:'question',label:'补件已收到，等待继续整理。',short:'补件待整理'}
  if(consent)return {state:'question',label:'请先确认本次材料的处理方式。',short:'等待授权'}
  if(['pending','running'].includes(task?.status))return {state:'working',label:['rendering','assembling','verifying'].includes(task.phase)?'正在编排并校验成果。':'正在识别文书、整理信息。',short:'整理中'}
  if(task?.has_archive&&['done','awaiting_review'].includes(task.status)){
    const draft=task.delivery_kind==='draft'||task.status!=='done'
    return {state:unresolved>0?'question':'ready',label:(draft?'档案草稿已生成。':'成果已保存。')+(unresolved>0?'疑点已集中列在“补充与核对”。':materials>0?'目录缺项已单列，可按需查看。':''),short:draft?'草稿已生成':'成果已保存'}
  }
  if(task?.status==='awaiting_review')return {state:'question',label:'材料已整理，可以生成草稿。',short:'待生成草稿'}
  return {state:'idle',label:'导入材料后，我来整理。',short:'问助理'}
}

// Case lists and the material page share the task's persisted delivery state.
// Older servers may omit the summary; an awaiting_review status alone is not a download.
export function caseTaskSummary(record){
  if(record?.last_task_summary)return record.last_task_summary
  if(!record?.last_task_id)return null
  return {id:record.last_task_id,status:record.last_task_status,has_archive:false}
}
// A recoverable original-form layout error is not an ordinary review queue.
// The public code is fixed by the server; never infer a field from prose.
export function needsOriginalFormCorrection(task){
  return task?.status==='awaiting_review' && task.phase==='needs_input' && task.has_archive!==true
    && typeof task.error==='string' && task.error.includes('[GD_ORIGINAL_TEMPLATE_OVERFLOW]')
}
export function caseTaskPresentation(task){
  if(!task)return {label:'尚未开始',title:'材料准备好后，一次开始整理',action:'开始归档',description:'助理会读取材料、整理目录并生成整套档案草稿，缺失材料集中列出。'}
  if(task.source_changed)return {label:'补件待整理',title:task.has_archive?'此前草稿已保存，补件待整理':'补件已收到',action:'根据当前材料继续归档',description:'已有成果不包含新增材料。继续整理会保留已保存的人工修改。'}
  if(['pending','running'].includes(task.status))return {label:'正在整理',title:'助理正在整理材料',action:'查看整理进度',description:'处理会继续保存在工作站，无需重复启动。'}
  if(task.status==='failed')return {label:'需要处理',title:'整理暂时停在这里',action:'查看并继续处理',description:'已保存材料仍保留，任务页提供具体原因和下一步。'}
  if(task.has_archive){const draft=task.delivery_kind==='draft'||task.status!=='done';return {label:draft?'草稿可下载':'成果可下载',title:draft?'档案草稿已生成':'归档成果已保存',action:draft?'查看与下载草稿':'查看与下载成果',description:'整卷 PDF、可编辑表格和核对记录已生成，补充材料可随后完善。'}}
  if(needsOriginalFormCorrection(task))return {label:'原表待调整',title:'原表内容需要简要填写',action:'打开并修改原表',description:'本次草稿尚未生成。任务页会显示具体原因；修改保存后可以重新生成。'}
  return {label:'已整理，可查看',title:'材料已整理',action:'打开归档草稿',description:'可在任务页生成完整草稿，缺项和识别疑问不要求逐项确认后才出卷。'}
}

export function archiveSummary(task,{unresolved=0,sourceCount=null}={}){
  const catalog=Array.isArray(task?.catalog_status)?task.catalog_status:[]
  const delivered=task?.has_archive===true&&['awaiting_review','done'].includes(task?.status)
  const draft=delivered&&(task.delivery_kind==='draft'||task.status!=='done')
  const facts=[]
  for(const [label,keys] of [['案号',['案号']],['委托人',['委托人名称','委托人']],['案件名称',['案件名称','案由']]]){
    const value=keys.map(key=>task?.fields?.[key]).find(value=>typeof value==='string'&&value.trim())
    if(value)facts.push({label,value:value.trim()})
  }
  const stats=[]
  if(Number.isInteger(sourceCount)&&sourceCount>=0)stats.push({label:'已导入材料',value:sourceCount,unit:'份'})
  if(catalog.length)stats.push({label:'已有材料归入目录',value:catalog.filter(item=>item.found===true&&item.seq!==0&&item.seq!=='0').length,unit:'项'})
  if(delivered&&Array.isArray(task.artifacts))stats.push({label:task.source_changed?'此前保存成果':'已生成成果',value:task.artifacts.length,unit:'份'})
  let title='材料已接收',description='归档助理将读取、分类并生成整卷档案草稿。需要补充的材料会集中列出。'
  if(task?.status==='failed'){title='整理暂时停在这里';description='已保存的材料和人工修改仍然保留。处理提示后可以继续。'}
  else if(task?.source_changed){title=delivered?'此前成果已保存，新增材料待整理':'材料已有变化，等待继续整理';description='人工修改会保留。已有成果不包含之后的材料变化。'}
  else if(draft){title='档案草稿已生成';description='可以先下载整卷 PDF、可编辑表格和成果包。补充清单与核对提示一并保留，尚未正式确认归档。'}
  else if(delivered){title='确认版已保存';description=task.formal_ready===true&&!task.preview_draft?'可下载卷宗和归档成果包；仍需留意表格待补充事项。':'已生成确认版；广东规则仍待核验，表格待补充事项仍保留。'}
  else if(needsOriginalFormCorrection(task)){title='原表内容需要简要填写';description='本次草稿尚未生成。请根据下方原因修改原表，保存后重新生成；其他核对事项仍可随后处理。'}
  else if(['rendering','assembling','verifying'].includes(task?.phase)){title='正在准备完整成果';description='正在生成表格、编排卷宗并校验成果。校验成功后提供下载。'}
  else if(task?.status==='running'){title='正在读取和整理材料';description='助理正在识别文书、整理信息并准备档案草稿。你可以离开页面，稍后回来。'}
  else if(task?.status==='awaiting_review'){title='材料已整理，可以生成档案草稿';description='先生成完整草稿，缺失材料和识别疑问保留在清单中，随后可随时补充完善。'}
  return {title,description,stats,facts}
}

export function nextArchiveAction(task,context={}){
  const {hasUnsaved=false,documentDraft=false,locked=false,uploadErrors=0,historical=false,latestTaskId=null,cloudConsentRequired=false,cloudApproved=false}=context
  const action=(kind,label,hint,disabled=false)=>({kind,label,hint,disabled:disabled||locked})
  if(!task)return action('none','正在读取','正在恢复案件状态',true)
  if(uploadErrors)return action('retry_uploads','重试未导入材料','已成功导入的材料会保留')
  if(['pending','running'].includes(task.status))return action('none',['rendering','assembling','verifying'].includes(task.phase)?'正在生成档案':'助理正在整理','处理进度保存在工作站，离开页面不会停止任务',true)
  if(historical&&latestTaskId!=null&&String(latestTaskId)!==String(task.id))return action('latest','打开最新任务','这份历史成果仍保留，可在工具中下载')
  if(task.source_changed){if(cloudConsentRequired&&!cloudApproved)return action('consent','确认补件处理方式','新增材料需要重新确认云端授权');return action('resume','补件已收到，继续整理','人工修改和核对记录会保留')}
  if(task.status==='failed'){
    if(task.can_resume&&cloudConsentRequired&&!cloudApproved)return action('consent','确认本次云端处理','核对授权后从已保存的进度继续')
    return task.can_resume?action('resume','继续处理','从已保存的进度继续'):action('issues','查看需要处理的问题','修复问题后继续整理')
  }
  if(documentDraft)return action('catalog','保存文书分类调整','有一项分类调整尚未保存，请保存或取消')
  if(task.has_archive&&!hasUnsaved)return action('download',task.delivery_kind==='draft'||task.status!=='done'?'下载档案草稿':'下载全部成果','整卷 PDF、可编辑表格和核对记录一并下载')
  if(needsOriginalFormCorrection(task))return action('repair_form','修改原表内容','保存修改后可重新生成，无需逐项处理其他核对事项')
  if(['awaiting_review','done'].includes(task.status))return action('draft',hasUnsaved?'保存修改并更新草稿':'生成档案草稿',task.can_assemble?'缺失材料保留在补充清单中，生成草稿无需逐项确认':'文书生成组件尚未就绪，已整理信息会保留',!task.can_assemble)
  return action('issues','查看任务详情','当前状态尚不能生成档案草稿')
}

export function materialRequirementLabel(item){if(item?.legal_requirement_verified!==true)return '适用性待核验';return ({required:'必要材料',conditional:'条件必要',optional:'可选材料'})[item.requirement]||'待核对'}
export function canUseTaskAssistant(task){return !task?.execution_profile||['local','ollama_local','deepseek_cloud'].includes(task.execution_profile.processing_mode)}
export function parseVisualStageProgress(line){
  if(typeof line!=='string')return null
  for(const [pattern,phase,title,unit] of [
    [/^视觉分类：已核对\s*(\d+)\s*\/\s*(\d+)\s*页\s*$/,'classification','识别文书边界与归属','页'],
    [/^文书提取：已处理\s*(\d+)\s*\/\s*(\d+)\s*份文书\s*$/,'extraction','提取文书中的关键字段','份文书'],
  ]){const match=line.trim().match(pattern);if(!match)continue;const done=Number(match[1]),total=Number(match[2]);if(Number.isSafeInteger(done)&&Number.isSafeInteger(total)&&total>0&&done>=0&&done<=total)return {phase,title,done,total,unit}}
  return null
}

