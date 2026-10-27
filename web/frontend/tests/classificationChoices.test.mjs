import test from 'node:test'
import assert from 'node:assert/strict'
import {loadSfc,mount,content,click,settle,findType,esm} from './vueHarness.mjs'
import * as domain from '../src/domain/documentClassification.js'
import * as groups from '../src/domain/evidenceGroups.js'
import {materialDisplayName} from '../src/domain/materialCompleteness.js'

test('review offers named destinations without immediately writing or changing pages',async()=>{
 const choice={doc_type:'firm_letter',catalog_seq:4,label:'4 授权委托书 — 律师事务所函',reason:'按已确认的律所归档约定摆放'}
 const document={unit_key:'one',doc_type:'unknown',catalog_seq:7,title:'虚构律师事务所函',filename:'虚构.pdf',file_id:'f',page_start:17,page_end:17,match_tier:'pending',suggestions:[choice]}
 let writes=0,body
 const snapshot={revision:1,editable:true,documents:[document],options:[choice]}
 const client={get:async()=>({data:snapshot}),patch:async(_url,value)=>{writes++;body=value;return {data:{...snapshot,revision:2,task:{revision:2}}}}}
 const Component=await loadSfc('../src/components/DocumentClassificationReview.vue',{'../api/client':esm(client),'../domain/documentClassification.js':domain,'../domain/evidenceGroups.js':groups})
 const {root,app}=mount(Component,{taskId:'1',revision:1,disabled:false,unsaved:false,beforeWrite:()=>''})
 findType(root,'details').props.onToggle({target:{open:true}});await settle()
 const buttons=(n)=>[...(n.type==='button'?[n]:[]),...n.children.flatMap(buttons)]
 assert.match(content(root),/虚构律师事务所函/);assert.match(content(root),/待定/)
 click(buttons(root).find(n=>content(n)==='调整归属'));await settle()
 const nodes=n=>[n,...n.children.flatMap(nodes)]
 assert.ok(nodes(root).some(n=>n.props?.label==='待定（暂存目录 7）' && n.props.disabled!==undefined))
 click(buttons(root).find(n=>content(n)===choice.label));await settle()
 assert.equal(writes,0)
 click(buttons(root).find(n=>content(n)==='保存分类草稿'));await settle()
 assert.equal(writes,1);assert.equal(body.doc_type,'firm_letter');assert.equal(body.catalog_seq,4)
 assert.equal(document.page_start,17);assert.equal(document.page_end,17)
 app.unmount()
})

test('material labels distinguish preservation rulings and hearing formats without changing original names',()=>{
 const row={name:'诉讼保全 + 案件相关法院裁判书',expected_doc_types:['preservation']}
 assert.equal(materialDisplayName(row),'保全、先行给付申请及相关裁判书')
 assert.match(row.name,/案件相关法院裁判书/)
 assert.match(materialDisplayName({expected_doc_types:['summons']}),/传票、短信或系统截图/)
})
