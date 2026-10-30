import test from 'node:test'
import assert from 'node:assert/strict'
import { loadSfc,mount,find,findType,content,click,settle } from './vueHarness.mjs'
import * as domain from '../src/domain/materialCompleteness.js'
import { nextArchiveAction } from '../src/domain/taskExperience.js'
import { canCreateArchive,caseTypeLabel } from '../src/domain/caseTypes.js'
const notice={file_id:'synthetic',filename:'虚构通知.pdf',page:5,page_start:5,page_end:6}
const contract={id:'material:contract',seq:3,name:'委托合同',check_kind:'source_material',requirement:'unknown',legal_requirement_verified:false,status:'missing',material_found:false,message:'委托代理通知书不能证明委托合同已提供或签署',related_sources:[notice]}
const row={seq:3,name:'委托合同',found:true,material_status_version:'v1',material_checks:[contract],unclassified_sources:[]}
const Component=await loadSfc('../src/components/SupplementSummary.vue',{'../domain/materialCompleteness.js':domain})

test('unprocessed pages do not become a repetitive material supplement list',()=>{
  const stopped={...row,material_checks:[{...contract,status:'processing_incomplete',message:'识别未完成，不表示材料缺失'}]}
  const result=domain.materialSupplementState([stopped])
  assert.equal(result.required.length+result.applicability.length+result.optional.length,0)
  assert.equal(result.pendingProcessing.length,1)
})

test('occupied contract row still appears once in consolidated list with real source navigation and no automatic decision',async()=>{
  const sources=[],uploads=[],h=mount(Component,{items:[row],issueCount:0,onSource:item=>sources.push(item),onUpload:()=>uploads.push(true)})
  try{await settle();assert.equal(find(h.root,'material-supplement-list'),undefined);assert.match(content(find(h.root,'applicability-materials')),/1 项适用性待核验/);assert.match(content(h.root),/通知书不能证明/);assert.match(content(h.root),/不表示可省略/);assert.equal(find(h.root,'applicability-materials').props.open,undefined);assert.equal(findType(h.root,'input'),undefined);click(find(h.root,'material-source'));assert.deepEqual(sources,[notice]);assert.deepEqual(uploads,[])}finally{h.app.unmount()}
})

test('optional and out-of-scope material do not become required prompts; system forms and unknown pages never imply completed evidence',async()=>{
  const optional={...contract,id:'optional',name:'可选附件',requirement:'optional',legal_requirement_verified:true}
  const inapplicable={...contract,id:'other-stage',name:'其他程序材料',requirement:'conditional',applicable:false}
  const generated={id:'system:delivery',check_kind:'execution_review',status:'unverified'}
  const items=[{...row,material_checks:[optional,inapplicable,generated],unclassified_sources:[notice]}]
  const state=domain.materialSupplementState(items);assert.deepEqual(state.required,[]);assert.equal(state.optional.length,1)
  const h=mount(Component,{items,issueCount:0});try{await settle();assert.equal(find(h.root,'material-supplement-list'),undefined);assert.ok(find(h.root,'optional-materials'));assert.equal(find(h.root,'optional-materials').props.open,undefined);assert.match(content(find(h.root,'unclassified-materials')),/不代表已经确认属于证据/);assert.match(content(find(h.root,'generated-form-not-proof')),/不证明已审批、签署或实际送达/)}finally{h.app.unmount()}
})

test('old catalog-only tasks show uncertainty without fabricated material recognition; draft download remains primary',()=>{
  const state=domain.materialSupplementState([{seq:3,name:'合同',found:false,requirement:'required',legal_requirement_verified:false}])
  assert.equal(state.modern,false);assert.equal(state.required.length,0);assert.equal(state.applicability.length,1);assert.match(state.applicability[0].message,/尚不能据此判断/)
  assert.equal(domain.materialRequirement(state.applicability[0]),'适用性待核验')
  assert.equal(nextArchiveAction({status:'awaiting_review',delivery_kind:'draft',has_archive:true,catalog_status:[row]}).kind,'download')
})

test('verified applicable requirements remain visible until verified, while unknown conditions never become mandatory or optional',async()=>{
  const needed={...contract,id:'required',requirement:'required',legal_requirement_verified:true,status:'recognized'}
  const conditional={...needed,id:'conditional',requirement:'conditional',applicable:true,status:'missing'}
  const undecided={...conditional,id:'unknown-condition',applicable:null}
  const unverified={...needed,id:'unverified-rule',legal_requirement_verified:false,status:'missing'}
  const finished={...needed,id:'finished',status:'verified'}
  const items=[{...row,material_checks:[needed,conditional,undecided,unverified,finished]}]
  const state=domain.materialSupplementState(items)
  assert.deepEqual(state.required.map(x=>x.id),['required','conditional'])
  assert.deepEqual(state.applicability.map(x=>x.id),['unknown-condition','unverified-rule'])
  assert.deepEqual(state.optional,[])
  const h=mount(Component,{items,issueCount:2})
  try{await settle();assert.match(content(h.root),/2 项必要材料/);assert.match(content(find(h.root,'material-supplement-list')),/必要材料/);assert.match(content(find(h.root,'applicability-materials')),/2 项适用性待核验/)}finally{h.app.unmount()}
})

test('five original-template case types remain available while unsupported historical types keep readable labels',()=>{
  for(const type of ['civil','criminal','admin','nonlit','counsel'])assert.equal(canCreateArchive(type),true)
  for(const type of ['arbitration','consultation','invented',''])assert.equal(canCreateArchive(type),false)
  assert.equal(caseTypeLabel('arbitration'),'仲裁业务');assert.equal(caseTypeLabel('consultation'),'法律咨询与代书')
})
