import test from 'node:test'
import assert from 'node:assert/strict'
import { buildDecisionQueue,selectDecision,stepDecision,decisionAfterSave,formDraftSummary,defaultCaseTitle } from '../src/domain/decisionQueue.js'

test('retained source forms suppress only replacement-form summaries',()=>{
  for(const [field,name] of Object.entries({'案情简介':'立案审批表','法院文件清单':'送达材料清单','委托人联系地址及电话':'质量监督卡','案件或项目名称':'结案报告表'})){
    const task={fields:{_original_forms:{[name]:[{file_id:'fixture',page:1}]},_form_drafts:{fields:{[field]:{status:'insufficient'}}}}}
    const before=structuredClone(task)
    assert.deepEqual(formDraftSummary(task),[])
    assert.deepEqual(task,before)
  }
  const task={fields:{_original_form_components:{'质量监督卡':[{component:'client_notice'}]},_form_drafts:{fields:{'委托人联系地址及电话':{status:'insufficient'}}}}}
  assert.equal(formDraftSummary(task).length,1)
  task.fields._original_form_components['质量监督卡'][0].component='quality_card'
  assert.deepEqual(formDraftSummary(task),[])
})
import { lineCellValue,updateLineCell } from '../src/domain/lineCells.js'
import { nextArchiveAction,archiveSummary } from '../src/domain/taskExperience.js'
const task={id:1,status:'awaiting_review',phase:'draft_ready',delivery_kind:'draft',has_archive:true,can_assemble:true,formal_ready:false,catalog_status:[{seq:1,name:'必要项',found:false,requirement:'required',legal_requirement_verified:true},{seq:2,name:'待核验项',found:false,requirement:'unknown'}],issues:[{id:'conflict',kind:'field_conflict',blocking:true,message:'核对案号',detail:{field:'案号',filename:'虚构.pdf',page:2}},{id:'extract',kind:'field_extraction_review',blocking:false}],fields:{}}

test('complete draft download is primary despite necessary missing material and field conflicts, without creating acknowledgements',()=>{
  const before=structuredClone(task)
  const action=nextArchiveAction(task,{unresolved:3})
  assert.equal(action.kind,'download');assert.equal(action.label,'下载档案草稿');assert.equal(action.disabled,false)
  const summary=archiveSummary(task,{unresolved:3});assert.equal(summary.title,'档案草稿已生成');assert.match(summary.description,/尚未正式确认/)
  assert.deepEqual(task,before)
  assert.equal(nextArchiveAction(task,{hasUnsaved:true}).kind,'draft')
})
test('optional review queue uses genuine unresolved state, locates source, preserves selection and never acknowledges on movement',()=>{
  const drafts={conflict:{action:'pending',reason:'尚未保存的解释'}}
  const before=structuredClone(drafts);const queue=buildDecisionQueue(task,{},drafts)
  assert.equal(queue.length,3);assert.equal(queue[0].key,'missing:1');assert.match(queue[1].location,/第 2 页/)
  const selected=selectDecision(queue);assert.equal(selected,'missing:1')
  assert.equal(stepDecision(queue,selected),'issue:conflict')
  assert.equal(selectDecision(queue,'issue:conflict'),'issue:conflict')
  assert.deepEqual(drafts,before)
  const checked=buildDecisionQueue(task,{}, {conflict:{action:'acknowledged',reason:'已核对'}})
  assert.equal(checked.find(item=>item.key==='issue:conflict').resolved,false)
  assert.equal(checked[0].resolved,false)
  const decided=structuredClone(task)
  decided.issues[0].detail.fact_resolved=true
  assert.equal(buildDecisionQueue(decided).find(item=>item.key==='issue:conflict').resolved,true)
})
test('court list fifth row renders and saves the entire tail without truncation; earlier edits preserve tail',()=>{
  const lines=['一','二','三','四','五','六','七']
  assert.equal(lineCellValue(lines,4,true),'五\n六\n七')
  assert.equal(updateLineCell(lines,4,'修改五\n修改六\n七',true),'一\n二\n三\n四\n修改五\n修改六\n七')
  assert.equal(updateLineCell(lines,1,'二修订'),'一\n二修订\n三\n四\n五\n六\n七')
  assert.equal(updateLineCell(lines,4,'',true),'一\n二\n三\n四')
})
test('grounded form summary shows only allowed metadata and accurately preserves insufficient or human status',()=>{
  const summary=formDraftSummary({fields:{_form_drafts:{fields:{'案情简介':{status:'generated',source_count:2,body:'不得进入摘要'},'法院文件清单':{status:'insufficient',source_count:0},'委托人联系地址及电话':{status:'human_modified',source_count:0},'任意字段':{status:'generated',source_count:50}}}}})
  assert.equal(summary.length,3);assert.equal(summary[0].label,'有依据草稿');assert.equal(summary[1].label,'待补全依据');assert.equal(summary[2].label,'人工值已保留');assert.doesNotMatch(JSON.stringify(summary),/不得进入摘要|任意字段/)
  assert.equal(defaultCaseTitle([{name:'虚构卷.pdf'}]),'虚构卷')
  assert.equal(defaultCaseTitle([{name:'甲.pdf',webkitRelativePath:'虚构案/甲.pdf'}]),'虚构案')
})

test('form summary distinguishes an original-cell space limit from missing material and includes the project name',()=>{
  const fields={
    '案情简介':{status:'insufficient',reason_codes:['draft_too_long_for_original_cell'],source_count:2,body:'不显示正文'},
    '法院文件清单':{status:'insufficient',reason_codes:['no_document_sources'],source_count:0},
    '委托人联系地址及电话':{status:'human_modified',reason_codes:['draft_too_long_for_original_cell'],source_count:1},
    '案件或项目名称':{status:'insufficient',reason_codes:['draft_too_long_for_original_cell'],source_count:3},
  }
  const before=structuredClone(fields)
  const summary=formDraftSummary({fields:{_form_drafts:{fields}}})
  assert.deepEqual(summary.map(item=>[item.field,item.label]),[
    ['案情简介','待简要填写'],['法院文件清单','待补全依据'],['委托人联系地址及电话','人工值已保留'],['案件或项目名称','待简要填写'],
  ])
  assert.equal(summary[0].status,'insufficient');assert.equal(summary[0].sourceCount,2)
  assert.equal(summary[3].status,'insufficient');assert.equal(summary[3].sourceCount,3)
  assert.doesNotMatch(JSON.stringify(summary),/不显示正文|draft_too_long_for_original_cell/)
  assert.deepEqual(fields,before)
})

test('legacy draft metadata without reason codes stays compatible and unrelated reason values cannot claim a layout issue',()=>{
  for(const reason_codes of [undefined,null,'draft_too_long_for_original_cell',['unrecognized_reason']]){
    const summary=formDraftSummary({fields:{_form_drafts:{fields:{'案件或项目名称':{status:'insufficient',reason_codes}}}}})
    assert.equal(summary[0].label,'待补全依据')
  }
  assert.equal(formDraftSummary({fields:{_form_drafts:{fields:{'案件或项目名称':{status:'generated',source_count:2}}}}})[0].label,'有依据草稿')
  assert.deepEqual(formDraftSummary({}),[])
})


test('after-save navigation respects unresolved facts, grouped membership, removed items and completion',()=>{
  const before=[{key:'a',resolved:false},{key:'b',resolved:false},{key:'c',resolved:false}]
  assert.equal(decisionAfterSave(before,'a',before),'a')
  assert.equal(decisionAfterSave([{...before[0],resolved:true},...before.slice(1)],'a',before),'b')
  assert.equal(decisionAfterSave([before[0],before[2]],'b',before),'c')
  assert.equal(decisionAfterSave(before.map(i=>({...i,resolved:true})),'c',before),null)
  const grouped=buildDecisionQueue({issues:[{id:'a',kind:'field_conflict',blocking:true,detail:{field:'案号',fact_resolved:true}},{id:'b',kind:'field_conflict',blocking:true,detail:{field:'案号'}}]})
  assert.equal(grouped.length,1);assert.equal(decisionAfterSave(grouped,grouped[0].key),grouped[0].key)
})


test('review sections separate uncertain and optional gaps without acknowledging or losing necessary material',async()=>{
  const {reviewQueueSections}=await import('../src/domain/decisionQueue.js')
  const current=structuredClone(task);current.catalog_status.push({seq:3,found:false,requirement:'optional',legal_requirement_verified:true})
  const queue=buildDecisionQueue(current),before=structuredClone(queue)
  const sections=reviewQueueSections(queue)
  assert.equal(sections.attentionCount,2);assert.equal(sections.materialCount,2)
  assert.ok(sections.attention.some(item=>item.key==='missing:1'))
  assert.deepEqual(queue,before)
  const {companionPresentation}=await import('../src/domain/taskExperience.js')
  const presentation=companionPresentation(current,{unresolved:0,materials:2})
  assert.doesNotMatch(presentation.label,/2 项待核对|已核验|已齐备/)
  assert.match(presentation.label,/目录缺项已单列/)
})
