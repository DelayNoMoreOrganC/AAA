import test from 'node:test'
import assert from 'node:assert/strict'
import { archiveSummary,nextArchiveAction,materialRequirementLabel,canUseTaskAssistant,parseVisualStageProgress } from '../src/domain/taskExperience.js'

test('printed civil directory count excludes the cover for both 17 and 18 item layouts',()=>{
  for(const count of [17,18]){
    const rows=Array.from({length:count+1},(_,seq)=>({seq,found:true}))
    assert.equal(archiveSummary({catalog_status:rows}).stats[0].value,count)
    rows[0].seq='0'
    assert.equal(archiveSummary({catalog_status:rows}).stats[0].value,count)
  }
})

test('reviewed artifacts do not claim all form content is complete',()=>{
  for(const formal_ready of [false,true]){
    const result=archiveSummary({status:'done',has_archive:true,delivery_kind:'reviewed',formal_ready})
    assert.equal(result.title,'确认版已保存')
    assert.match(result.description,/表格待补充/)
    assert.doesNotMatch(result.title,/完整|合规/)
  }
})

test('summary counts only persisted catalogue/artifact facts and whitelists meaningful case fields',()=>{
  const task={status:'awaiting_review',progress:88,catalog_status:[{found:true},{found:false},{found:true}],fields:{案号:'（虚构）123号',委托人名称:'虚构甲',_saved_to:'private path',任意字段:'不要进入摘要'}}
  const summary=archiveSummary(task,{unresolved:2,sourceCount:4})
  assert.deepEqual(summary.stats,[{label:'已导入材料',value:4,unit:'份'},{label:'已有材料归入目录',value:2,unit:'项'}])
  assert.deepEqual(summary.facts,[{label:'案号',value:'（虚构）123号'},{label:'委托人',value:'虚构甲'}])
  assert.ok(!JSON.stringify(summary).includes('88'));assert.ok(!JSON.stringify(summary).includes('private path'))
})

test('rendering and incomplete artifacts never become a completed result summary',()=>{
  for(const phase of ['rendering','assembling','verifying']){
    const summary=archiveSummary({status:'running',phase,has_archive:false,artifacts:[{name:'temporary.pdf'}]})
    assert.equal(summary.title,'正在准备完整成果');assert.equal(summary.stats.length,0)
  }
  assert.match(archiveSummary({status:'done',has_archive:true,formal_ready:false,artifacts:[{},{}]}).description,/规则仍待核验/)
})

test('primary action generates an archive draft without forcing review and downloads an existing result',()=>{
  const review={id:1,status:'awaiting_review',can_assemble:true,has_archive:false}
  assert.equal(nextArchiveAction(review,{unresolved:3}).kind,'draft')
  assert.equal(nextArchiveAction(review,{unresolved:0}).kind,'draft')
  assert.equal(nextArchiveAction({...review,status:'done',has_archive:true}).kind,'download')
  assert.equal(nextArchiveAction({...review,status:'done',has_archive:true},{hasUnsaved:true}).kind,'draft')
  assert.equal(nextArchiveAction({...review,can_assemble:false}).disabled,true)
})

test('necessary missing material remains disclosed but cannot block creating an explicitly labelled draft',()=>{
  const task={id:1,status:'awaiting_review',phase:'needs_input',can_assemble:true,catalog_status:[{seq:1,found:false,requirement:'required',legal_requirement_verified:true}]}
  assert.equal(nextArchiveAction(task,{unresolved:0}).kind,'draft')
  assert.equal(nextArchiveAction(task,{unresolved:1}).kind,'draft')
  assert.match(archiveSummary(task).title,/生成档案草稿/)
  assert.equal(nextArchiveAction({...task,status:'running'}).disabled,true)
  assert.equal(nextArchiveAction({...task,source_changed:true}).kind,'resume')
})

test('draft summaries distinguish incomplete field extraction and never present supplements as the current complete archive',()=>{
  const review={status:'awaiting_review',can_assemble:true,issues:[{kind:'field_extraction_review',blocking:false}]}
  assert.match(archiveSummary(review).description,/识别疑问保留/)
  assert.equal(nextArchiveAction(review).kind,'draft')
  assert.match(archiveSummary({...review,issues:[{kind:'empty_fields',blocking:true}]},{unresolved:1}).title,/生成档案草稿/)
  assert.equal(nextArchiveAction({...review,issues:[{kind:'field_conflict',blocking:true}]},{unresolved:1}).kind,'draft')
  const changed={status:'done',has_archive:true,source_changed:true,artifacts:[{}]}
  assert.match(archiveSummary(changed).title,/新增材料待整理/)
  assert.match(archiveSummary(changed).description,/不包含之后/)
  assert.equal(archiveSummary({...changed,status:'running',source_changed:false}).title,'正在读取和整理材料')
})

test('unsaved document classification cannot be hidden behind finalize or download',()=>{
  const task={status:'done',has_archive:true,can_assemble:true}
  assert.equal(nextArchiveAction(task,{documentDraft:true}).kind,'catalog')
  assert.equal(nextArchiveAction(task,{locked:true}).disabled,true)
})

test('supplemented source requires fresh cloud consent before resume and never presents old outputs as the next result',()=>{
  const task={id:1,status:'done',has_archive:true,source_changed:true}
  assert.equal(nextArchiveAction(task,{historical:true,latestTaskId:1,cloudConsentRequired:true,cloudApproved:false}).kind,'consent')
  assert.equal(nextArchiveAction(task,{historical:true,latestTaskId:1,cloudConsentRequired:true,cloudApproved:true}).kind,'resume')
  assert.equal(nextArchiveAction(task,{historical:true,latestTaskId:2}).kind,'latest')
})

test('running work is not clickable; partial import and failed required artifacts retain meaningful recovery actions',()=>{
  assert.equal(nextArchiveAction({status:'running',phase:'analyzing'}).disabled,true)
  assert.equal(nextArchiveAction({status:'awaiting_review'},{uploadErrors:2}).kind,'retry_uploads')
  assert.equal(nextArchiveAction({status:'failed',phase:'artifacts_invalid',can_resume:true,has_archive:false}).kind,'resume')
  assert.equal(nextArchiveAction({status:'failed',can_resume:false}).kind,'issues')
})

test('unverified rules never turn into a necessary-material compliance claim',()=>{
  assert.equal(materialRequirementLabel({requirement:'required',legal_requirement_verified:false}),'适用性待核验')
  assert.equal(materialRequirementLabel({requirement:'required',legal_requirement_verified:true}),'必要材料')
  assert.equal(materialRequirementLabel({requirement:'optional',legal_requirement_verified:true}),'可选材料')
})

test('read-only assistant is available only for supported frozen profiles; unsupported cloud does not get a failing button',()=>{
  assert.equal(canUseTaskAssistant({execution_profile:{processing_mode:'deepseek_cloud'}}),true)
  assert.equal(canUseTaskAssistant({execution_profile:{processing_mode:'local'}}),true)
  assert.equal(canUseTaskAssistant({execution_profile:{processing_mode:'glm_cloud'}}),false)
  assert.equal(canUseTaskAssistant({execution_profile:{processing_mode:'cloud'}}),false)
})

test('visual classification reports real source pages, while field extraction reports documents without overall percentages',()=>{
  assert.deepEqual(parseVisualStageProgress('视觉分类：已核对 35 / 85 页'),{phase:'classification',title:'识别文书边界与归属',done:35,total:85,unit:'页'})
  const extraction=parseVisualStageProgress('文书提取：已处理 2 / 16 份文书')
  assert.deepEqual(extraction,{phase:'extraction',title:'提取文书中的关键字段',done:2,total:16,unit:'份文书'})
  assert.ok(!('percent' in extraction));assert.ok(!('pages' in extraction))
})

test('invalid counters, arbitrary log content and fragments cannot pretend to be source-page progress',()=>{
  for(const line of ['视觉分类：已核对 86 / 85 页','视觉分类：已核对 0 / 0 页','文书提取：已处理 -1 / 16 份文书','文书提取：已处理 1 / 16 页','来源核对完成，已处理 2 / 10 个页面片段','材料正文：视觉分类：已核对 1 / 3 页','视觉分类：已核对 1 / 9007199254740992 页',null])assert.equal(parseVisualStageProgress(line),null)
})

