import test from 'node:test'
import assert from 'node:assert/strict'
import { CASE_TYPES, stageOptions, defaultStage } from '../src/domain/caseTypes.js'
import { archiveCoverTitle } from '../src/domain/workflow.js'

test('seven explicit business types offer compatible stage choices and defaults',()=>{
  assert.equal(CASE_TYPES.length,7)
  assert.deepEqual(stageOptions('arbitration').map(s=>s.value),['arbitration','judicial_review','execution'])
  assert.deepEqual(stageOptions('consultation').map(s=>s.value),['consultation','drafting','closed'])
  for(const item of CASE_TYPES) assert.ok(stageOptions(item.value).some(stage=>stage.value===defaultStage(item.value)))
  assert.equal(defaultStage('unknown'),'')
  assert.deepEqual(stageOptions('unknown'),[])
})
test('arbitration and consultation covers match backend non-litigation classification',()=>{
  for(const type of ['arbitration','consultation']) assert.equal(archiveCoverTitle(type),'律师业务档案卷宗（非诉讼类）')
})
