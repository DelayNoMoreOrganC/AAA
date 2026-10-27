import test from 'node:test'
import assert from 'node:assert/strict'
import { createCloudConsent,glmKeyUpdate,isCloudProcessing,materialConsentKey,processingLabel,resumeProcessingMode,taskNeedsCloudConsent,taskProcessingLabel,secretKeyUpdate,processingSettingsPayload,cloudProviderName,cloudMaterialDescription,cloudPolicyUpdate } from '../src/domain/processingPrivacy.js'

test('loading a task does not label it as a historical task without a processing profile',()=>{
  assert.equal(taskProcessingLabel(null),'')
  assert.equal(taskProcessingLabel(undefined),'')
  assert.equal(taskProcessingLabel({id:1,execution_profile:null}),'历史任务未记录处理方式')
})

test('GLM key update omits untouched values and clears only with explicit removal',()=>{
  for(const value of ['',null,undefined,'   '])assert.deepEqual(glmKeyUpdate(value),{})
  assert.deepEqual(glmKeyUpdate('',true),{glm_api_key:''})
  assert.deepEqual(glmKeyUpdate(' synthetic-test-key '),{glm_api_key:'synthetic-test-key'})
  assert.deepEqual(glmKeyUpdate('replacement',true),{glm_api_key:'replacement'})
})

test('cloud consent is false by default and does not infer authorization from the selected mode',()=>{
  for(const mode of ['deepseek_cloud','glm_cloud','cloud']){
    const consent=createCloudConsent();consent.update(mode,'synthetic-case-A')
    assert.equal(consent.approved,false);assert.throws(()=>consent.payload(),/确认本案材料/)
    consent.approve(true);assert.deepEqual(consent.payload(),{cloud_consent:true,expected_processing_mode:mode})
    consent.approve(false);assert.throws(()=>consent.payload(),/确认本案材料/)
  }
})

test('DeepSeek cloud declares image/text transfer and cannot reuse consent from GLM',()=>{
  assert.equal(cloudProviderName('deepseek_cloud'),'DeepSeek')
  assert.equal(cloudMaterialDescription('deepseek_cloud'),'页面图像及必要文字')
  assert.equal(taskProcessingLabel({execution_profile:{processing_mode:'deepseek_cloud'}}),'视觉归档 · 云端')
  const consent=createCloudConsent();consent.update('glm_cloud','same-batch');consent.approve(true);consent.update('deepseek_cloud','same-batch')
  assert.equal(consent.approved,false);assert.throws(()=>consent.payload())
  consent.approve(true);assert.equal(consent.payload().expected_processing_mode,'deepseek_cloud')
})

test('settings payload never sends GET secrets/configured flags or clears untouched provider keys',()=>{
  const form={processing_mode:'deepseek_cloud',deepseek_model:'legacy-model',deepseek_key_configured:true,deepseek_api_key:'must-not-replay',mineru_api_token:'must-not-replay'}
  assert.deepEqual(processingSettingsPayload(form),{processing_mode:'deepseek_cloud',deepseek_model:'legacy-model'})
  assert.deepEqual(processingSettingsPayload(form,{deepseek_api_key:{value:'new-test-value'},mineru_api_token:{value:'',clear:true}}),{processing_mode:'deepseek_cloud',deepseek_model:'legacy-model',deepseek_api_key:'new-test-value',mineru_api_token:''})
  assert.deepEqual(secretKeyUpdate('deepseek_api_key',''),{})
  assert.throws(()=>secretKeyUpdate('unknown-secret','value'))
})

test('workstation cloud feature requires explicit administrator acknowledgement and respects deployment lock',()=>{
  assert.throws(()=>cloudPolicyUpdate(true,false,{allowed:false,locked:false}),/先确认/)
  assert.throws(()=>cloudPolicyUpdate(true,true,{locked:true}),/部署策略/)
  assert.throws(()=>cloudPolicyUpdate(true,true,null),/先读取/)
  assert.deepEqual(cloudPolicyUpdate(true,true,{allowed:false,locked:false}),{allowed:true,confirm_external_processing:true})
  assert.deepEqual(cloudPolicyUpdate(false,false,{allowed:true,locked:false}),{allowed:false,confirm_external_processing:false})
  const consent=createCloudConsent();consent.update('deepseek_cloud','case-A')
  // Enabling the workstation feature cannot grant per-case transmission consent.
  cloudPolicyUpdate(true,true,{allowed:false,locked:false})
  assert.equal(consent.approved,false)
})

test('new materials, another case and a different provider each require a fresh unchecked consent',()=>{
  const consent=createCloudConsent();consent.update('glm_cloud','case-A:files-1');consent.approve(true)
  consent.update('glm_cloud','case-A:files-1');assert.equal(consent.approved,true)
  for(const [mode,batch] of [['glm_cloud','case-A:files-2'],['glm_cloud','case-B:files-2'],['cloud','case-B:files-2']]){
    consent.update(mode,batch);assert.equal(consent.approved,false);assert.throws(()=>consent.payload())
    consent.approve(true)
  }
  consent.reset();assert.equal(consent.approved,false)
})

test('local mode explicitly declares local without granting cloud use; unavailable mode fails closed',()=>{
  const consent=createCloudConsent();consent.update('local','case-A');consent.approve(true)
  assert.equal(consent.approved,false);assert.deepEqual(consent.payload(),{cloud_consent:false,expected_processing_mode:'local'})
  consent.update('','case-A');assert.throws(()=>consent.payload(),/尚未确认处理方式/)
  assert.equal(processingLabel(''),'处理方式尚未确认')
})

test('switching away from cloud and back cannot restore a previous authorization',()=>{
  const consent=createCloudConsent();consent.update('glm_cloud','case-A');consent.approve(true)
  consent.update('local','case-A');consent.update('glm_cloud','case-A')
  assert.equal(consent.approved,false);assert.throws(()=>consent.payload())
})

test('consent batch uses material metadata without file bytes, secrets or extracted body',()=>{
  const a={id:'a',filename:'虚构A.pdf',file_size:10,doc_type:'default',body:'not metadata',api_key:'not metadata'}
  const b={id:'b',filename:'虚构B.pdf',file_size:20,doc_type:'evidence'}
  const key=materialConsentKey([a,b])
  assert.equal(key,materialConsentKey([b,a]));assert.ok(!key.includes('not metadata'))
  assert.notEqual(key,materialConsentKey([{...a,file_size:11},b]))
  assert.notEqual(key,materialConsentKey([{...a,doc_type:'judgment'},b]))
  assert.notEqual(key,materialConsentKey([a]))
})

test('task labels read frozen execution profile only, never current account settings',()=>{
  assert.match(taskProcessingLabel({execution_profile:{processing_mode:'glm_cloud'},processing_mode:'local'}),/智谱云端/)
  assert.equal(taskProcessingLabel({execution_profile:{processing_mode:'local'},processing_mode:'glm_cloud'}),'本地文字处理（旧版）')
  assert.equal(taskProcessingLabel({processing_mode:'glm_cloud'}),'历史任务未记录处理方式')
  assert.equal(resumeProcessingMode({execution_profile:null}),'local')
  assert.equal(resumeProcessingMode({execution_profile:{processing_mode:'glm_cloud'}}),'glm_cloud')
})

test('only an unchanged frozen cloud task with an exact source authorization may retry without a new checkbox',()=>{
  const task={source_changed:false,source_version:'source-A',execution_profile:{processing_mode:'glm_cloud',cloud_consent:true,authorized_source_version:'source-A'}}
  assert.equal(taskNeedsCloudConsent(task),false)
  assert.equal(taskNeedsCloudConsent({...task,source_changed:true}),true)
  assert.equal(taskNeedsCloudConsent({...task,source_version:'source-B'}),true)
  assert.equal(taskNeedsCloudConsent({...task,source_version:''}),true)
  assert.equal(taskNeedsCloudConsent({...task,execution_profile:{...task.execution_profile,cloud_consent:false}}),true)
  assert.equal(taskNeedsCloudConsent({...task,execution_profile:{processing_mode:'local'}}),false)
  assert.equal(taskNeedsCloudConsent({execution_profile:null}),false)
  assert.equal(isCloudProcessing('glm_cloud'),true)
})


test('local visual tasks use their frozen profile without any cloud consent',()=>{
  const consent=createCloudConsent();consent.update('ollama_local','batch');consent.approve(true)
  assert.equal(consent.approved,false)
  assert.deepEqual(consent.payload(),{cloud_consent:false,expected_processing_mode:'ollama_local'})
  assert.equal(taskProcessingLabel({execution_profile:{processing_mode:'ollama_local'}}),'视觉归档 · 本地')
  assert.equal(taskNeedsCloudConsent({execution_profile:{processing_mode:'ollama_local'},source_changed:true}),false)
})
