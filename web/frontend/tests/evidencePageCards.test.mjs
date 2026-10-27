import test from 'node:test'
import assert from 'node:assert/strict'
import { evidencePageCards } from '../src/domain/workflow.js'

test('same source page has one navigation card while all distinct excerpts and original records survive',()=>{
  const base={file_id:'fictional-a',filename:'虚构判决.pdf',page:8,method:'local_agent'}
  const refs=[{...base,quote:'被告偿还本金1000元。'},
    {...base,quote:'法院记载律师到庭。被告偿还本金1000元。',source_role:'client_identity'},
    {...base,quote:'驳回其他诉讼请求。'}, {...base,quote:'被告偿还 本金1000元。'}]
  const before=structuredClone(refs),cards=evidencePageCards(refs)
  assert.equal(cards.length,1)
  assert.deepEqual(cards[0].quotes,['法院记载律师到庭。被告偿还本金1000元。','驳回其他诉讼请求。'])
  assert.deepEqual(cards[0].entries,refs)
  assert.deepEqual(refs,before)
})

test('different files, pages, historical status, and human edits never merge',()=>{
  const base={file_id:'fictional-a',filename:'相同文件名.pdf',page:8,quote:'原文',method:'local_agent'}
  const refs=[base,{...base,file_id:'fictional-b'},{...base,page:9},{...base,historical:true},
    {method:'human',value:'',edited_at:'2026-10-27'},{method:'human',value:'人工值'}]
  const cards=evidencePageCards(refs)
  assert.equal(cards.length,6)
  assert.equal(cards[3].historical,true)
  assert.equal(cards[4].value,'')
})

test('unlocated records and divergent OCR excerpts are retained rather than collapsed by filename or similarity',()=>{
  const refs=[{filename:'同名.pdf',quote:'1000元'},{filename:'同名.pdf',quote:'1000元'},
    {file_id:'a',page:1,quote:'1000元'},{file_id:'a',page:1,quote:'10000元'}]
  const cards=evidencePageCards(refs)
  assert.equal(cards.length,3)
  assert.deepEqual(cards[2].quotes,['1000元','10000元'])
})
