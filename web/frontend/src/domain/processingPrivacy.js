export function isCloudProcessing(mode) { return ['deepseek_cloud','glm_cloud','cloud'].includes(mode) }

export function cloudProviderName(mode) { return ({deepseek_cloud:'DeepSeek',glm_cloud:'智谱'})[mode] || '所选云服务商' }

export function cloudMaterialDescription(mode) { return ['deepseek_cloud','glm_cloud'].includes(mode)?'页面图像及必要文字':'原始材料或识别文本' }

export function processingLabel(mode) {
  return ({local:'本地文字处理（旧版）',ollama_local:'视觉归档 · 本地',deepseek_cloud:'视觉归档 · 云端',glm_cloud:'GLM 视觉归档 · 智谱云端',cloud:'云端模型与 OCR'})[mode] || '处理方式尚未确认'
}

export function taskProcessingLabel(task) {
  if (!task) return ''
  const profile=task?.execution_profile
  if (!profile || !['local','ollama_local','deepseek_cloud','glm_cloud','cloud'].includes(profile.processing_mode)) return '历史任务未记录处理方式'
  return processingLabel(profile.processing_mode)
}

export function resumeProcessingMode(task) { return task?.execution_profile?.processing_mode || 'local' }
export function capturedFormPolicyToken(task) { return task?.form_policy_update?.token || undefined }
export function validateFormPolicyRefresh(selected,task) {
  const current=capturedFormPolicyToken(task)
  // An absent current plan may mean the first request already created a child.
  // Send the captured token so the server can recover only that exact child.
  if(current && current!==selected)throw new Error('可更新的栏目或填写规则已变化，请核对最新状态后重新确认。')
  return selected
}
export function taskNeedsCloudConsent(task) {
  if (!isCloudProcessing(resumeProcessingMode(task))) return false
  const profile=task.execution_profile
  return task.form_policy_update?.available === true || task.source_changed === true || profile.cloud_consent !== true || !task.source_version || profile.authorized_source_version !== task.source_version
}

// The API key is write-only: an untouched input omits the field, explicit removal sends ''.
export function glmKeyUpdate(value, clear=false) {
  return secretKeyUpdate('glm_api_key',value,clear)
}
export function secretKeyUpdate(field,value,clear=false) {
  if (!['glm_api_key','deepseek_api_key','mineru_api_token'].includes(field)) throw new Error('Unknown secret setting')
  const key=String(value || '').trim()
  if (key) return {[field]:key}
  return clear ? {[field]:''} : {}
}

export function processingSettingsPayload(form, secrets={}) {
  const fields=['local_vision_tier','processing_mode','local_llm_base_url','local_llm_model','deepseek_base_url','deepseek_model','order_mode']
  const payload=Object.fromEntries(fields.filter(field=>typeof form[field]==='string').map(field=>[field,form[field]]))
  for(const field of ['deepseek_api_key','glm_api_key','mineru_api_token'])Object.assign(payload,secretKeyUpdate(field,secrets[field]?.value,secrets[field]?.clear===true))
  return payload
}

export function cloudPolicyUpdate(allowed,confirmed,policy) {
  if (typeof allowed!=='boolean' || !policy) throw new Error('请先读取工作站云功能状态。')
  if (allowed && policy.locked===true) throw new Error('部署策略禁止启用外部 AI。')
  if (allowed && confirmed!==true) throw new Error('请先确认允许本工作站处理获准使用云服务的材料。')
  return {allowed,confirm_external_processing:allowed&&confirmed===true}
}

export function materialConsentKey(files) {
  return JSON.stringify((Array.isArray(files)?files:[]).map(file=>[
    file.id ?? file.webkitRelativePath ?? file.name ?? '', file.filename ?? file.name ?? '',
    file.file_size ?? file.size ?? 0, file.doc_type ?? '', file.updated_at ?? file.lastModified ?? '',
  ]).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b))))
}

// Consent is bound to this visible batch and selected processing mode, in page memory only.
export function createCloudConsent() {
  let context='',mode='',approvedContext=''
  return {
    update(nextMode, batch) {
      const next=JSON.stringify([String(nextMode||''),String(batch||'')])
      if (next!==context) approvedContext=''
      mode=String(nextMode||'');context=next
    },
    approve(value) { approvedContext=value===true && isCloudProcessing(mode)?context:'' },
    reset() { approvedContext='' },
    get approved() { return isCloudProcessing(mode) && approvedContext===context && !!context },
    payload() {
      if (!['local','ollama_local','deepseek_cloud','glm_cloud','cloud'].includes(mode)) throw new Error('尚未确认处理方式，请重新检查工作站设置。')
      if (!isCloudProcessing(mode)) return {cloud_consent:false,expected_processing_mode:mode}
      if (!approvedContext || approvedContext!==context) throw new Error('请先确认本案材料获准发送云端；新增材料需要重新确认。')
      return {cloud_consent:true,expected_processing_mode:mode}
    },
  }
}
