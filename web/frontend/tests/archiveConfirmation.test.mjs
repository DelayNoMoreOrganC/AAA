import test from 'node:test'
import assert from 'node:assert/strict'
import {archiveConfirmationAction} from '../src/domain/taskExperience.js'

const draft=()=>({has_archive:true,delivery_kind:'draft',status:'awaiting_review',can_assemble:true,formal_ready:false})

test('reviewable draft has a direct confirmation entry even when legal readiness is separately unverified',()=>{
  assert.deepEqual(archiveConfirmationAction(draft()),{visible:true,disabled:false,label:'确认成卷'})
})
test('missing or conflicting material cannot use the shortcut to bypass review',()=>{
  for(const patch of [{can_assemble:false},{can_assemble:undefined},{source_changed:true}]){
    assert.equal(archiveConfirmationAction({...draft(),...patch}).disabled,true)
  }
  assert.equal(archiveConfirmationAction(draft(),{unresolved:1}).disabled,true)
})
test('unfinished uploads, classification edits and concurrent writes block confirmation',()=>{
  for(const flag of ['locked','documentDraft','uploadBlocked']){
    assert.equal(archiveConfirmationAction(draft(),{[flag]:true}).disabled,true)
  }
})
test('history and confirmed outputs do not suggest another confirmation',()=>{
  assert.equal(archiveConfirmationAction(draft(),{historical:true}).visible,false)
  assert.equal(archiveConfirmationAction({...draft(),delivery_kind:'reviewed',status:'done'}).visible,false)
})
test('processing, failed and absent draft states cannot be confirmed',()=>{
  for(const task of [null,{...draft(),has_archive:false},...['pending','running','failed'].map(status=>({...draft(),status}))]){
    const result=archiveConfirmationAction(task);assert.equal(result.visible,false);assert.equal(result.disabled,true)
  }
})
