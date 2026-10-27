// Independent actual SFC template probe in the Vue memory renderer, not a browser.
import test from 'node:test'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,content,settle} from './vueHarness.mjs'

test('server-reported unavailable completed source is visible after refresh without making it a cancellable pending upload',async()=>{
  const Component=await loadSfc('../src/components/UploadRecoveryPanel.vue')
  const state={loaded:true,loading:false,busy:false,error:'',notice:'',writable:true,
    rows:[],matchMessages:[],canRetry:false,pendingCount:0,
    items:[{request_id:'synthetic-unavailable',filename:'虚构已导入但已变更.pdf',status:'unavailable'}]}
  const h=mount(Component,{state,dismissTestId:'independent-cancel',retryTestId:'independent-retry'})
  try{
    await settle()
    assert.ok(find(h.root,'upload-recovery'),'unavailable is an actionable recovery state, not an empty successful list')
    assert.ok(content(h.root).includes('虚构已导入但已变更.pdf'))
    assert.ok(/缺失|改变|变更|不可用/.test(content(h.root)),'show a clear integrity notice')
    assert.equal(find(h.root,'independent-cancel'),undefined,'completed receipt is not a cancellable pending item')
  }finally{h.app.unmount()}
})


test('active import does not show recovery controls; stopped import retains the exact failure and pending file',async()=>{
  const Component=await loadSfc('../src/components/UploadRecoveryPanel.vue')
  const state=Vue.reactive({loaded:true,loading:false,busy:true,error:'',items:[],matchMessages:[],canRetry:true,
    rows:[{request_id:'pending',filename:'虚构待传.docx',file:{},message:'转换失败'}]})
  const h=mount(Component,{state,retryTestId:'retry-after-stop'})
  try {
    await settle()
    assert.ok(!find(h.root,'upload-recovery'),'recovery panel must stay hidden during an active upload')
    assert.ok(!find(h.root,'retry-after-stop'),'retry control must stay hidden while uploading')
    state.busy=false;await settle()
    assert.ok(find(h.root,'upload-recovery'))
    assert.ok(content(h.root).includes('虚构待传.docx：转换失败'))
    assert.ok(find(h.root,'retry-after-stop'))
    assert.equal(state.rows.length,1)
  }finally{h.app.unmount()}
})
