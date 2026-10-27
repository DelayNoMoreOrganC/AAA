// Presentation of server-owned source projections; never asserts signature or service.
const draftForms={
  '案情简介':'立案审批表','立案审批日期':'立案审批表','法院文件清单':'送达材料清单',
  '委托人联系地址及电话':'质量监督卡','案件或项目名称':'结案报告表','结案小结':'结案报告表',
}
export function draftFieldTemplate(field){return draftForms[field]||''}
export function sourceFormFieldsPreserved(fields,name){
  const originals=fields?._original_forms?.[name]
  if(Array.isArray(originals)&&originals.length)return true
  if(name==='立案审批表'&&Array.isArray(fields?._source_intake_approval)&&fields._source_intake_approval.length)return true
  const components=fields?._original_form_components?.['质量监督卡']
  return name==='质量监督卡'&&Array.isArray(components)&&components.some(ref=>ref?.component==='quality_card')
}
export function draftFieldNeedsGeneratedForm(fields,field){
  return !sourceFormFieldsPreserved(fields,draftForms[field])
}
