import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceGroups } from '../src/domain/evidenceGroups.js'
const row=(id,start,end,title='附件',extra={})=>({unit_key:id,file_id:'file',page_start:start,page_end:end,title,doc_type:'evidence',catalog_seq:7,match_tier:'confirmed',...extra})
test('groups index and contiguous attachments, never changes units or assumes list is complete',()=>{
 const docs=[row('list',8,8,'证据材料清单（虚构案）'),row('id',9,9),row('contract',10,31),row('statement',32,37,'截图',{match_tier:'pending'}),row('court',38,38,'受理案件通知书',{doc_type:'acceptance_notice',catalog_seq:5})]
 const before=structuredClone(docs),groups=evidenceGroups(docs)
 assert.equal(groups.length,2);assert.equal(groups[0].page_end,37);assert.equal(groups[0].pending,1)
 assert.deepEqual(groups.flatMap(g=>g.documents),docs);assert.deepEqual(docs,before)
})
test('unknowns, page gaps, files, slots and a new index all end a group',()=>{
 for(const change of [{doc_type:'unknown'},{page_start:4},{file_id:'other'},{catalog_seq:8},{title:'证据目录'}]){
  const groups=evidenceGroups([row('list',1,1,'证据目录'),row('next',2,2,'附件',change)])
  assert.equal(groups.length,2)
 }
 assert.equal(evidenceGroups([row('a',1,1,'民事起诉状中提及证据目录'),row('b',2,3)]).length,2)
})
