import test from 'node:test'
import assert from 'node:assert/strict'
import { Vue,loadSfc,mount,find,findType,content,click,input,settle,esm } from './vueHarness.mjs'
import * as domain from '../src/domain/templateFields.js'
const initial=[{key:'委托人',label:'委托人',value:'虚构甲',multiline:false},{key:'法院文件清单',label:'法院文件清单',value:'一\n二\n三\n四\n五\n六\n七',multiline:true}]
const findField=(n,key)=>['input','textarea'].includes(n.type)&&n.props['data-field']===key?n:n.children.map(child=>findField(child,key)).find(Boolean)
const findButton=(n,text)=>n.type==='button'&&content(n).includes(text)?n:n.children.map(child=>findButton(child,text)).find(Boolean)

test('intake date convention stays labelled and edits use the intake-only key',async()=>{
  const h=await harness();try{
    h.state.fields=[{key:'立案审批日期',label:'立案日期',value:'2026年1月5日',
      display_value:'2026年1月5日（按合同日期默认）',display_note:'仅用于审批表，不证明已审批。',
      assurance:{status:'convention_default',anchors:[{file_id:'contract',page:1}]}}]
    await h.instance.loadPreview();await settle();click(find(h.root,'toggle-template-fields'));await settle()
    assert.match(content(find(h.root,'template-field-assurance')),/按合同日期默认（仅审批表）/)
    assert.match(content(find(h.root,'template-field-display')),/不证明已审批/)
    assert.equal(findField(h.root,'立案审批日期').props.value,'2026年1月5日')
    click(find(h.root,'template-field-source'));await settle();assert.deepEqual(h.sources,['立案审批日期'])
    input(findField(h.root,'立案审批日期'),'');await settle();click(find(h.root,'save-template-fields'));await settle()
    assert.deepEqual(h.calls.find(([method])=>method==='put')[2].values,{立案审批日期:''})
  }finally{h.app.unmount()}
})

test('fee short display is explained without replacing complete editable terms or becoming a save value',async()=>{
  const h=await harness();try{
    const full='一审基础律师费5000元；另按实际回款2%计费，付款条件见合同。'
    h.state.fields=[{key:'收费标准',label:'收费标准',value:full,multiline:true,display_value:'基础5000元\n回款2%详合同',display_note:'一审收费条款及付款条件详合同。'}]
    await h.instance.loadPreview();await settle();click(find(h.root,'toggle-template-fields'));await settle()
    assert.equal(findField(h.root,'收费标准').props.value,full)
    assert.match(content(find(h.root,'template-field-display')),/基础5000元/)
    assert.deepEqual(domain.templateValues(domain.normalizeTemplateFields(h.state.fields)),{收费标准:full})
    assert.equal(h.instance.hasUnsavedChanges(),false)
    input(findField(h.root,'收费标准'),'人工简述');await settle()
    assert.equal(find(h.root,'template-field-display'),undefined)
    click(find(h.root,'save-template-fields'));await settle()
    assert.deepEqual(h.calls.find(([method])=>method==='put')[2].values,{收费标准:'人工简述'})
  }finally{h.app.unmount()}
})
async function harness({readOnly=false,pdfMode='original',putFailure=null,delayedPdf=false,pdfRevision=null}={}){
  const state={revision:7,fields:structuredClone(initial),styles:{'field:委托人':{color:'#000000'}},custom_values:{'p0-b0-r0-c0':'历史已存值'}},calls=[],saved=[],busy=[],sources=[];let resolvePdf
  const client={get:async(path)=>{
    calls.push(['get',path])
    if(path.includes('/preview-fields/'))return {data:structuredClone(state)}
    if(delayedPdf)return new Promise(done=>{resolvePdf=done})
    if(pdfMode==='error')throw {response:{status:500,data:new Blob([JSON.stringify({detail:'原表转换失败，请重试'})],{type:'application/json'})}}
    return {data:new Blob(['synthetic page'],{type:'image/png'}),headers:{'content-type':'image/png','x-template-page':String(new URL('http://fixture'+path).searchParams.get('page')),'x-template-pages':'2','x-task-revision':String(pdfRevision??state.revision),'x-template-fidelity':pdfMode}}
  },put:async(path,body)=>{calls.push(['put',path,structuredClone(body)]);if(putFailure)throw putFailure;assert.equal(body.expected_revision,state.revision);for(const field of state.fields)if(field.key in body.values)field.value=body.values[field.key];state.revision++;return {data:{id:3,revision:state.revision,has_archive:false,fields:{}}}}}
  const Component=await loadSfc('../src/components/PreviewFieldEditor.vue',{'../api/client':esm(client),'../domain/templateFields.js':domain})
  const props=Vue.reactive({taskId:'3',templateName:'送达材料清单',active:true,revision:7,sourceVersion:'synthetic-source',readOnly,disabled:false});let instance
  const Parent={setup:()=>()=>Vue.h(Component,{...props,ref:value=>{instance=value},onSaved:task=>{saved.push(task);props.revision=task.revision},onBusy:value=>busy.push(value),onSource:field=>sources.push(field)})}
  const h=mount(Parent);await settle()
  return {...h,state,calls,saved,busy,sources,props,get instance(){return instance},resolvePdf:response=>resolvePdf(response)}
}

test('five-form editor renders the actual authenticated PDF only, with no recreated table or editable fixed text',async()=>{
  const h=await harness();try{assert.ok(find(h.root,'original-template-pdf'));assert.match(find(h.root,'original-template-pdf').props.src,/^blob:/);assert.equal(findType(h.root,'iframe'),undefined);assert.equal(find(h.root,'original-template-pdf').type,'img');assert.equal(findType(h.root,'table'),undefined);assert.equal(find(h.root,'template-fields').style.display,'none');assert.equal(h.calls.filter(([m])=>m==='put').length,0);assert.equal(findField(h.root,'法院文件清单').props.value,'一\n二\n三\n四\n五\n六\n七')}finally{h.app.unmount()}
})

test('original-template field targeting expands and highlights the exact field without overwriting dirty values or saving',async()=>{
  const h=await harness();try{input(findField(h.root,'法院文件清单'),'手工尚未保存');await settle();assert.equal(await h.instance.revealField('法院文件清单'),true);await settle();assert.notEqual(find(h.root,'template-fields').style.display,'none');assert.equal(findField(h.root,'法院文件清单').props.value,'手工尚未保存');assert.equal(h.instance.hasUnsavedChanges(),true);assert.equal(await h.instance.revealField('不存在字段'),false);assert.equal(h.calls.filter(([m])=>m==='put').length,0)}finally{h.app.unmount()}
})
test('explicit manual clearing saves only that empty field with CAS, preserves legacy metadata and refreshes true PDF',async()=>{
  const h=await harness();try{click(find(h.root,'toggle-template-fields'));await settle();input(findField(h.root,'委托人'),'');await settle();assert.equal(h.instance.hasUnsavedChanges(),true);assert.match(content(h.root),/尚未包含右侧未保存修改/);const oldUrl=find(h.root,'original-template-pdf').props.src;click(find(h.root,'save-template-fields'));await settle();const put=h.calls.find(([method])=>method==='put');assert.deepEqual(put[2],{values:{委托人:''},styles:h.state.styles,custom_values:h.state.custom_values,expected_revision:7});assert.equal(h.saved[0].has_archive,false);assert.equal(findField(h.root,'委托人').props.value,'');assert.equal(h.instance.hasUnsavedChanges(),false);assert.notEqual(find(h.root,'original-template-pdf').props.src,oldUrl);assert.ok(h.busy.includes(true));assert.equal(h.busy.at(-1),false)}finally{h.app.unmount()}
})
test('inactive tabs and revision refresh retain unsaved input; uncontested shared fields save against latest revision',async()=>{
  const h=await harness();try{input(findField(h.root,'法院文件清单'),'一\n二\n三\n四\n五\n六\n七\n八');await settle();h.props.active=false;await settle();h.state.fields[0].value='另一表已改';h.state.revision=8;h.props.revision=8;h.props.active=true;await settle();assert.match(findField(h.root,'法院文件清单').props.value,/八/);assert.equal(h.instance.hasUnsavedChanges(),true);await h.instance.saveChanges();await settle();const body=h.calls.find(([method])=>method==='put')[2];assert.equal(body.expected_revision,8);assert.deepEqual(Object.keys(body.values),['法院文件清单']);assert.equal(findField(h.root,'委托人').props.value,'另一表已改')}finally{h.app.unmount()}
})
test('conflicting shared field keeps local text and requires an explicit choice before overwrite',async()=>{
  const h=await harness();try{input(findField(h.root,'委托人'),'本页修改');await settle();h.state.fields[0].value='其他位置修改';h.state.revision=8;assert.equal(await h.instance.saveChanges(),false);await settle();assert.equal(h.calls.filter(([method])=>method==='put').length,0);assert.equal(findField(h.root,'委托人').props.value,'本页修改');assert.match(content(find(h.root,'template-field-conflict')),/其他位置修改/);click(findButton(h.root,'保留我的输入'));await settle();assert.equal(await h.instance.saveChanges(),true);assert.equal(h.calls.find(([method])=>method==='put')[2].expected_revision,8)}finally{h.app.unmount()}
})
test('history is read-only but sources and original PDF remain available',async()=>{
  const h=await harness({readOnly:true});try{assert.ok(find(h.root,'original-template-pdf'));assert.equal(findField(h.root,'委托人').props.disabled,true);assert.equal(find(h.root,'save-template-fields'),undefined);assert.equal(await h.instance.saveChanges(),false);click(find(h.root,'template-field-source'));assert.deepEqual(h.sources,['委托人']);assert.equal(h.calls.filter(([method])=>method==='put').length,0)}finally{h.app.unmount()}
})
test('unverified renderer and actual PDF failure never silently fall back to HTML or show a synthetic table',async()=>{
  for(const pdfMode of ['legacy','error']){const h=await harness({pdfMode});try{assert.equal(find(h.root,'original-template-pdf'),undefined);assert.ok(find(h.root,'template-pdf-error'));assert.equal(findType(h.root,'table'),undefined);if(pdfMode==='error')assert.match(content(h.root),/原表转换失败/);else assert.match(content(h.root),/尚未确认此预览来自原始模板/)}finally{h.app.unmount()}}
})
test('409 during save leaves manual edits dirty and does not claim a saved or regenerated result',async()=>{
  const h=await harness({putFailure:{response:{status:409,data:{detail:'任务版本已变化'}}}});try{input(findField(h.root,'委托人'),'未保存');await settle();assert.equal(await h.instance.saveChanges(),false);await settle();assert.equal(h.instance.hasUnsavedChanges(),true);assert.equal(findField(h.root,'委托人').props.value,'未保存');assert.match(content(h.root),/任务版本已变化/);assert.deepEqual(h.saved,[])}finally{h.app.unmount()}
})
test('leaving template discards a late PDF response rather than restoring a document from the previous task',async()=>{
  const h=await harness({delayedPdf:true});h.app.unmount();h.resolvePdf({data:new Blob(['%PDF late']),headers:{'content-type':'application/pdf','x-task-revision':'7','x-template-fidelity':'original'}});await settle();assert.equal(find(h.root,'original-template-pdf'),undefined);assert.deepEqual(h.saved,[])
})


test('PDF response from an older task revision is rejected even when the original-template header is present',async()=>{
  const h=await harness({pdfRevision:6});try{assert.equal(find(h.root,'original-template-pdf'),undefined);assert.match(content(find(h.root,'template-pdf-error')),/版本已变化/);assert.equal(h.instance.isLoaded(),true)}finally{h.app.unmount()}
})
test('normalization changes no data until edited, preserves all multiline rows, and never treats an empty clear as missing',()=>{
  const fields=domain.normalizeTemplateFields(initial),baseline=domain.templateValues(fields);assert.deepEqual(domain.changedTemplateValues(fields,baseline),{});fields[0].value='';assert.deepEqual(domain.changedTemplateValues(fields,baseline),{委托人:''});assert.equal(fields[1].value.split('\n').length,7);assert.deepEqual(domain.conflictingTemplateFields({委托人:''},baseline,initial),[])
})

test('saved field assurance is visible beside fields, preserves source action, and is not carried over to unsaved input',async()=>{
  const h=await harness();try{
    h.state.fields[0].assurance={status:'source_supported',label:'有原文依据，待核对',source_count:1,anchors:[{file_id:'fixture',page:2}],reason_codes:['literal_source_not_independent_truth_verification']}
    await h.instance.loadPreview();await settle();click(find(h.root,'toggle-template-fields'));await settle()
    assert.match(content(find(h.root,'template-field-assurance')),/有原文依据，待核对 · 1 处原文/)
    click(find(h.root,'template-field-source'));assert.deepEqual(h.sources,['委托人'])
    input(findField(h.root,'委托人'),'手工改值');await settle()
    assert.equal(find(h.root,'template-field-assurance').props['data-status'],'unsaved')
    assert.match(content(find(h.root,'template-field-assurance')),/未保存修改，尚未核验/)
    assert.equal(h.calls.filter(([method])=>method==='put').length,0)
  }finally{h.app.unmount()}
})

test('assurance normalizer preserves known meanings, strips private data, and never promotes unknown legacy fields',()=>{
  const normalized=domain.normalizeFieldAssurance({status:'derived_draft',label:'已完整核验',source_count:99,anchors:[{file_id:'f',page:1,path:'secret',quote:'body'},{file_id:'f',page:1},{file_id:'f',page:-1}],reason_codes:['draft_not_signed_or_served_record'],path:'secret'})
  assert.equal(normalized.label,'依据材料预填，待核对');assert.equal(normalized.source_count,1)
  assert.deepEqual(normalized.anchors,[{file_id:'f',page:1}]);assert.doesNotMatch(JSON.stringify(normalized),/secret|body/)
  assert.equal(domain.normalizeFieldAssurance().status,'unverified')
  assert.equal(domain.normalizeFieldAssurance({status:'signed_and_approved'}).status,'unverified')
  assert.equal(domain.normalizeTemplateFields([{key:'委托人',value:'',assurance:{status:'human_confirmed'}}])[0].assurance.label,'人工填写或确认')
})

test("original page navigation requests page two while retaining dirty form input",async()=>{const h=await harness();try{input(findField(h.root,"委托人"),"未保存输入");await settle();click(findButton(h.root,"下一页"));await settle();assert.ok(h.calls.some(([method,path])=>method==="get"&&path.endsWith("?page=2")));assert.match(find(h.root,"original-template-pdf").props.alt,/第 2 页/);assert.equal(findField(h.root,"委托人").props.value,"未保存输入");assert.equal(h.instance.hasUnsavedChanges(),true)}finally{h.app.unmount()}})
