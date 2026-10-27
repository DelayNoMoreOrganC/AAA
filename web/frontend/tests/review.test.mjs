import test from 'node:test'
import assert from 'node:assert/strict'
import { saveReviewEditors, unresolvedMissing } from '../src/domain/review.js'
const changedEditor = (save) => {
  let dirty = true
  return { isLoaded: () => true, hasUnsavedChanges: () => dirty, saveChanges: async () => { const ok = await save(); if(ok)dirty=false; return ok } }
}
test('a failed save blocks subsequent saves and keeps the failing draft dirty', async () => {
  const calls=[]
  const first=changedEditor(async()=>{calls.push('first');return false})
  const second=changedEditor(async()=>{calls.push('second');return true})
  await assert.rejects(saveReviewEditors(['first','second'],{first,second}), /保存失败/)
  assert.deepEqual(calls,['first'])
  assert.equal(first.hasUnsavedChanges(),true)
})
test('unopened and unchanged templates are not reported as saved', async () => {
  const untouched={isLoaded:()=>true,hasUnsavedChanges:()=>false,saveChanges:()=>{throw new Error('must not save')}}
  const unloaded={isLoaded:()=>false}
  const changed=changedEditor(async()=>true)
  assert.equal(await saveReviewEditors(['untouched','unloaded','changed'],{untouched,unloaded,changed}),1)
})
test('an active editor loading failure blocks saving and generation', async () => {
  await assert.rejects(saveReviewEditors(['active'],{active:{isLoaded:()=>false}},'active'),/尚未加载/)
})
test('new edits made during a save cannot be silently considered saved', async () => {
  const editor={isLoaded:()=>true,hasUnsavedChanges:()=>true,saveChanges:async()=>true}
  await assert.rejects(saveReviewEditors(['form'],{form:editor}),/新修改/)
})
test('every missing item needs an explicit supported decision and reason', () => {
  const items=[{seq:1},{seq:2},{seq:3},{seq:4}]
  const decisions={1:{action:'skip',reason:'尚未收齐'},2:{action:'not_applicable',reason:'本案未发生'},3:{action:'pending',reason:'待补充'},4:{action:'skip',reason:'   '}}
  assert.deepEqual(unresolvedMissing(items,decisions).map(i=>i.seq),[3,4])
  assert.equal(unresolvedMissing([{seq:5}],{}).length,1)
})

test('verified necessary material remains unresolved even after a saved skip or inapplicable decision',()=>{
  const items=[{seq:1,found:false,requirement:'required',legal_requirement_verified:true},{seq:2,found:false,requirement:'conditional',legal_requirement_verified:true},{seq:3,found:false,requirement:'required',legal_requirement_verified:false}]
  for(const action of ['skip','not_applicable']){
    const decisions=Object.fromEntries(items.map(item=>[item.seq,{action,reason:'既有核对说明'}]))
    assert.deepEqual(unresolvedMissing(items,decisions).map(item=>item.seq),[1])
  }
})

