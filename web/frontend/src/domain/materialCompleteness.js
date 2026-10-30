/** Catalog occupancy and document presence have deliberately separate meanings. */
export function materialDisplayName(item){
  if(item?.expected_doc_types?.includes('preservation'))return '保全、先行给付申请及相关裁判书'
  if(item?.expected_doc_types?.includes('summons'))return '开庭通知（传票、短信或系统截图）'
  return item?.name||'待核对材料'
}
export function materialRequirement(item){
  if(item?.legal_requirement_verified!==true)return '适用性待核验'
  return ({required:'必要材料',conditional:'条件必要',optional:'可选材料'})[item.requirement]||'适用性待核验'
}
export function materialSupplementState(catalog){
  const rows=Array.isArray(catalog)?catalog:[],modern=rows.some(row=>typeof row?.material_status_version==='string')
  const all=modern?rows.flatMap(row=>[...(Array.isArray(row.material_checks)?row.material_checks:[]),...(Array.isArray(row.additional_material_checks)?row.additional_material_checks:[])]):rows.filter(row=>!row.found).map(row=>({...row,id:'legacy:'+row.seq,check_kind:'source_material',status:'unverified',message:'历史任务仅记录目录空位，尚不能据此判断本案材料是否齐备',related_sources:[]}))
  const seen=new Set(),checks=all.filter(item=>item&&item.id&&!seen.has(item.id)&&seen.add(item.id))
  const applicableRequired=item=>item.legal_requirement_verified===true&&(item.requirement==='required'||item.requirement==='conditional'&&item.applicable===true)
  // Match the server's formal gate: recognizing a required document does not
  // by itself verify its execution/completeness. Unknown applicability must
  // not be presented as a mandatory supplement or silently called optional.
  const missing=checks.filter(item=>item.check_kind==='source_material'&&item.applicable!==false&&item.status!=='processing_incomplete'&&
    (applicableRequired(item)?item.status!=='verified':!['recognized','verified'].includes(item.status)))
  const optional=missing.filter(item=>item.requirement==='optional'&&item.legal_requirement_verified===true)
  const required=missing.filter(applicableRequired)
  const applicability=missing.filter(item=>!required.includes(item)&&!optional.includes(item))
  const unknown=new Map()
  for(const row of rows)for(const source of Array.isArray(row?.unclassified_sources)?row.unclassified_sources:[]){if(source?.file_id&&Number.isSafeInteger(source.page)&&source.page>0)unknown.set(source.file_id+':'+source.page,source)}
  return {modern,required,applicability,optional,pendingProcessing:checks.filter(item=>item.status==='processing_incomplete'),unknown:[...unknown.values()],executionReview:checks.some(item=>item.check_kind==='execution_review')}
}
export function materialSourceLabel(source){return (source.filename||'来源材料')+' · 第 '+(source.page_start||source.page)+(source.page_end>source.page_start?'—'+source.page_end:'')+' 页'}
