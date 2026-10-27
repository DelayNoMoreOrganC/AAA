export const CASE_TYPES = [
  { value:'civil', label:'民事诉讼' }, { value:'criminal', label:'刑事业务' },
  { value:'admin', label:'行政诉讼' }, { value:'nonlit', label:'非诉业务' },
  { value:'counsel', label:'法律顾问' }, { value:'arbitration', label:'仲裁业务', templateReady:false },
  { value:'consultation', label:'法律咨询与代书', templateReady:false },
]
export const STAGE_LABELS = {
  first_instance:'一审', appeal:'二审', retrial:'再审', execution:'执行',
  investigation:'侦查', prosecution:'审查起诉', engagement:'接受委托', delivery:'成果交付', closed:'业务办结',
  service_period:'顾问服务期', renewal:'续约', termination:'终止', arbitration:'仲裁程序',
  judicial_review:'司法审查', consultation:'法律咨询', drafting:'法律文书代书',
}
export const CASE_STAGES = {
  civil:['first_instance','appeal','retrial','execution'],
  criminal:['investigation','prosecution','first_instance','appeal','retrial'],
  admin:['first_instance','appeal','retrial','execution'],
  nonlit:['engagement','delivery','closed'], counsel:['service_period','renewal','termination'],
  arbitration:['arbitration','judicial_review','execution'], consultation:['consultation','drafting','closed'],
}
export const caseTypeLabel = value => CASE_TYPES.find(item => item.value === value)?.label || '案件'
export const canCreateArchive = value => CASE_TYPES.some(item => item.value === value && item.templateReady !== false)
export const caseStageLabel = value => STAGE_LABELS[value] || ''
export const stageOptions = type => (CASE_STAGES[type] || []).map(value => ({ value, label:STAGE_LABELS[value] }))
export const defaultStage = type => CASE_STAGES[type]?.[0] || ''
