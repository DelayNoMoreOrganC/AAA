import test from 'node:test'
import assert from 'node:assert/strict'
import { assistantHistory, assistantError, createAssistantConversation } from '../src/domain/assistant.js'

test('assistant history sends only the last six successful text messages, bounded and without result or token metadata', () => {
  const messages=Array.from({length:8},(_,index)=>({role:index%2?'assistant':'user',content:String(index).repeat(1600),state:'sent',token:'private',items:[{text:'source'}]}))
  messages.push({role:'user',content:'failed question',state:'failed'},{role:'system',content:'untrusted system instruction'})
  const history=assistantHistory(messages)
  assert.equal(history.length,6)
  assert.equal(history[0].content,'2'.repeat(1500))
  assert.deepEqual(Object.keys(history[0]),['role','content'])
  assert.ok(!JSON.stringify(history).includes('private'))
})

test('a real successful response keeps evidence links and only existing read-only drawer actions', async () => {
  let state,payload
  const chat=createAssistantConversation({onChange:value=>state=value,request:async(id,body)=>{
    payload={id,body}
    return {tool:'explain_field',message:'案号来源如下',items:[{title:'起诉状 · 第 1 页',file_id:'file1',page:1,field:'案号'}],action:{type:'fields',label:'打开表格核对'}}
  }})
  chat.reset('task1')
  assert.equal(await chat.ask('案号从哪里来？'),true)
  assert.equal(payload.id,'task1')
  assert.deepEqual(payload.body,{message:'案号从哪里来？',history:[]})
  assert.equal(state.messages[1].items[0].file_id,'file1')
  assert.equal(state.messages[1].action.type,'fields')
  assert.equal(state.pending,false)
  chat.dispose()
})

test('409 and 503 preserve the question, add no fake assistant answer, and a retry does not duplicate failed turns', async () => {
  for(const status of [409,503]){
    let state,calls=0,lastPayload
    const chat=createAssistantConversation({onChange:value=>state=value,request:async(_,body)=>{
      calls++;lastPayload=body
      if(calls===1)throw {response:{status}}
      return {message:'已读取真实任务记录',items:[]}
    }})
    chat.reset('task1')
    assert.equal(await chat.ask('还缺什么？'),false)
    assert.equal(state.messages.length,1)
    assert.equal(state.messages[0].state,'failed')
    assert.match(state.error,status===409?/正在整理/:/模型尚未就绪/)
    assert.equal(await chat.ask('还缺什么？'),true)
    assert.deepEqual(lastPayload.history,[])
    assert.equal(state.messages.length,2)
    assert.equal(state.messages[0].state,'sent')
    chat.dispose()
  }
})

test('changing task aborts the request and discards its late reply rather than showing evidence from another case', async () => {
  let state,resolveOld,oldSignal,calls=0
  const chat=createAssistantConversation({onChange:value=>state=value,request:async(id,body,signal)=>{
    calls++
    if(id==='old'){oldSignal=signal;return new Promise(resolve=>resolveOld=resolve)}
    return {message:'新任务的真实结果',items:[]}
  }})
  chat.reset('old')
  const old=chat.ask('旧任务问题')
  assert.equal(await chat.ask('重复点击'),false)
  assert.equal(calls,1)
  chat.reset('new')
  assert.equal(oldSignal.aborted,true)
  assert.equal(state.messages.length,0)
  assert.equal(await chat.ask('新任务问题'),true)
  resolveOld({message:'旧任务结果',items:[{title:'旧材料'}]})
  assert.equal(await old,false)
  assert.equal(state.messages.length,2)
  assert.equal(state.messages[1].content,'新任务的真实结果')
  chat.dispose()
})

test('leaving the page aborts in-flight requests and does not publish late content', async () => {
  let resolve,signal,changes=0
  const chat=createAssistantConversation({onChange:()=>changes++,request:async(_,__,currentSignal)=>{
    signal=currentSignal;return new Promise(done=>resolve=done)
  }})
  chat.reset('task1')
  const pending=chat.ask('问题')
  chat.dispose()
  assert.equal(signal.aborted,true)
  const before=changes
  resolve({message:'不应显示的晚到结果'})
  assert.equal(await pending,false)
  assert.equal(changes,before)
})

test('oversized requests and empty results cannot become fabricated success', async () => {
  let state,calls=0
  const chat=createAssistantConversation({onChange:value=>state=value,request:async()=>{calls++;return {items:[]}}})
  chat.reset('task1')
  assert.equal(await chat.ask('问'.repeat(1501)),false)
  assert.equal(calls,0)
  assert.equal(await chat.ask('正常问题'),false)
  assert.equal(state.messages.filter(message=>message.role==='assistant').length,0)
  assert.equal(state.pending,false)
})

test('unexpected action and invalid source page cannot turn into a write or fabricated source link', async () => {
  let state
  const chat=createAssistantConversation({onChange:value=>state=value,request:async()=>({
    message:'只返回读取结果',items:[{title:'人工填写',file_id:'old-file',page:0}],action:{type:'save_fields',label:'自动保存'},
  })})
  chat.reset('task1')
  await chat.ask('来源')
  assert.equal(state.messages[1].action,null)
  assert.equal(state.messages[1].items[0].page,null)
  assert.equal(assistantError({response:{status:503,data:{detail:'工作站模型正在加载'}}}),'工作站模型正在加载')
})
