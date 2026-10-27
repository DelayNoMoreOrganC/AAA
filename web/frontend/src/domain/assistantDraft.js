// Unsent text lives on the authorized workstation, never in browser storage.
export function normalizeAssistantDraft(value) {
  if (!value || typeof value.content !== 'string' || value.content.length > 1500
      || !Number.isSafeInteger(value.version) || value.version < 0
      || !Number.isSafeInteger(value.revision) || typeof value.source_version !== 'string'
      || !Number.isSafeInteger(value.task_revision) || typeof value.task_source_version !== 'string'
      || typeof value.writable !== 'boolean') throw new Error('未取得有效的工作站草稿，输入尚未同步。')
  return {content:value.content,version:value.version,revision:value.revision,source_version:value.source_version,
    task_revision:value.task_revision,task_source_version:value.task_source_version,
    updated_at:value.updated_at||null,writable:value.writable,notice:typeof value.notice==='string'?value.notice:'',
    consumed_request_id:typeof value.consumed_request_id==='string'?value.consumed_request_id:null}
}

const sameContext=(a,b)=>a?.revision===b?.revision&&a?.source_version===b?.source_version
export function createAssistantDraft({read,write,getContext=()=>({}),onChange=()=>{},delay=500}) {
  let taskId='',generation=0,editSerial=0,disposed=false,timer=null,controller=null,loadController=null
  let base=null,editingContext=null,pendingWrite=null,pendingConsumption=null,savePromise=null,loadPromise=null
  const initial=()=>({content:'',loaded:false,loading:false,saving:false,writable:true,notice:'',error:'',
    conflict:false,remote:null,contextChanged:false,unknown:false,sending:false,dirty:false,version:0})
  let state=initial()
  const context=()=>{
    const supplied=getContext()
    return {revision:supplied.revision??base?.task_revision,source_version:supplied.source_version??base?.task_source_version}
  }
  const readOnly=()=>getContext().readOnly===true||!state.writable
  // Reading an empty tombstone from an older context is not an instruction to
  // rebase it. A non-empty draft still requires explicit context continuation.
  const needsWrite=()=>!!base&&(state.content!==base.content||(!!state.content&&!sameContext(editingContext,base)))
  function publish(){
    state.contextChanged=!!state.content&&!!editingContext&&!sameContext(editingContext,context())
    state.dirty=state.saving||state.sending||!!pendingConsumption||state.conflict||!!pendingWrite||(!base?!!state.content:needsWrite())
    state.version=base?.version||0
    onChange({...state,remote:state.remote?{...state.remote}:null})
  }
  function cancelTimer(){if(timer!==null)clearTimeout(timer);timer=null}
  function schedule(){
    cancelTimer()
    if(!disposed&&state.loaded&&!readOnly()&&!state.sending&&!pendingConsumption&&!state.conflict&&!state.contextChanged&&!state.error&&needsWrite())
      timer=setTimeout(()=>{timer=null;flush()},delay)
  }
  function reset(id){
    generation++;cancelTimer();controller?.abort();loadController?.abort()
    taskId=String(id||'');base=null;editingContext=null;pendingWrite=null;pendingConsumption=null;savePromise=null;loadPromise=null;editSerial=0
    state=initial();publish()
    if(taskId)reload()
  }
  async function reload(){
    if(disposed||!taskId||state.loading||state.saving)return false
    if(pendingConsumption)return finishSend(pendingConsumption)
    const current=generation,serial=editSerial,wasLoaded=state.loaded,hadLocalEdits=state.dirty
    state.loading=true;state.error='';loadController=new AbortController();publish()
    const operation=(async()=>{
      try{
        const remote=normalizeAssistantDraft(await read(taskId,loadController.signal))
        if(disposed||current!==generation)return false
        state.loaded=true;state.writable=remote.writable;state.notice=remote.notice
        if(pendingWrite){
          // A read alone never overwrites uncertain local input. Explicit retry
          // reuses the exact CAS request; the server can acknowledge one lost ACK.
          state.remote=remote
          state.error='上次同步结果尚未确认，请重试同步；不会自动覆盖工作站中的新草稿。'
        }else if(state.conflict||(editSerial!==serial||hadLocalEdits)&&state.content!==remote.content){
          state.conflict=true;state.remote=remote
          state.error='本机输入与工作站草稿不同，请选择保留哪一份。'
        }else{
          base=remote
          if(!wasLoaded&&!hadLocalEdits&&editSerial===serial)state.content=remote.content
          else if(!hadLocalEdits&&editSerial===serial)state.content=remote.content
          editingContext=state.content?{revision:remote.revision,source_version:remote.source_version}:context()
          state.remote=null;state.error=''
        }
        return true
      }catch(error){
        if(disposed||current!==generation)return false
        state.error='未能读取工作站草稿。当前输入仅在本页，尚未同步；请重新连接后读取草稿。'
        return false
      }finally{
        if(current===generation&&!disposed){state.loading=false;loadController=null;publish();schedule()}
      }
    })()
    loadPromise=operation
    try{return await operation}finally{if(current===generation)loadPromise=null}
  }
  function edit(value){
    if(disposed||readOnly())return false
    if(state.loading&&!state.loaded&&!state.content&&!state.error)return false
    const content=String(value??'')
    if(content.length>1500)return false
    if(!content||!editingContext||(!state.content&&!base?.content&&!pendingWrite&&!pendingConsumption))editingContext=context()
    // Count every edit, including changing back to an earlier string, so a
    // completed model request can never consume newly typed text by equality.
    editSerial++;state.content=content
    if(!state.conflict&&!pendingWrite&&state.loaded)state.error=''
    publish();schedule();return true
  }
  function updateContext(){cancelTimer();publish();schedule()}
  function continueCurrentContext(){
    if(disposed||readOnly()||!state.loaded||state.conflict)return false
    editingContext=context();state.error='';publish();schedule();return true
  }
  function chooseLocal(){
    if(!state.conflict||!state.remote||readOnly())return false
    base=state.remote;state.remote=null;state.conflict=false;pendingWrite=null;state.unknown=false;state.error=''
    publish();schedule();return true
  }
  function useRemote(){
    if(!state.conflict||!state.remote)return false
    base=state.remote;state.content=base.content;editingContext=state.content?{revision:base.revision,source_version:base.source_version}:context()
    editSerial++;pendingWrite=null;state.unknown=false;state.remote=null;state.conflict=false;state.error=''
    publish();return true
  }
  async function performWrite(body){
    const current=generation
    state.saving=true;state.error='';controller=new AbortController();publish()
    try{
      const saved=normalizeAssistantDraft(await write(taskId,body,controller.signal))
      if(disposed||current!==generation)return false
      if(saved.version!==body.expected_version+1||saved.content!==body.content
          ||saved.revision!==body.expected_revision||saved.source_version!==body.source_version)
        throw new Error('同步回执不匹配')
      base=saved;pendingWrite=null;state.unknown=false;state.writable=saved.writable;state.notice=saved.notice
      return true
    }catch(error){
      if(disposed||current!==generation)return false
      if(error?.response?.status===409){
        pendingWrite=null;state.unknown=false;state.conflict=true;state.remote=null
        state.error='工作站草稿或案件版本已有变化。本机输入已保留，请读取工作站版本后选择。'
        try{
          const remote=normalizeAssistantDraft(await read(taskId,controller.signal))
          if(disposed||current!==generation)return false
          state.remote=remote;state.writable=remote.writable;state.notice=remote.notice
        }catch{/* Keep both conflict and local text; explicit read can recover. */}
      }else{
        // Retain the exact CAS body for the server's one-version lost-ACK
        // acknowledgement; never force a new version over another tab.
        pendingWrite={body:{...body}};state.unknown=true
        state.error=typeof error?.response?.data?.detail==='string'?error.response.data.detail:'草稿同步尚未确认，输入仍保留在本页。请重试同步。'
      }
      return false
    }finally{
      if(current===generation&&!disposed){state.saving=false;controller=null;publish()}
    }
  }
  async function flush(){
    cancelTimer()
    const current=generation
    if(loadPromise)await loadPromise
    if(savePromise)await savePromise
    if(disposed||current!==generation||!taskId||!state.loaded||readOnly()||state.sending||pendingConsumption||state.conflict||state.contextChanged)return false
    if(!pendingWrite&&!needsWrite())return true
    const request=pendingWrite||{body:{content:state.content,expected_version:base.version,
      expected_revision:context().revision,source_version:context().source_version}}
    savePromise=performWrite(request.body)
    let saved=false
    try{saved=await savePromise}finally{if(current===generation){savePromise=null;publish();schedule()}}
    return saved&&!state.dirty&&!state.conflict&&!state.contextChanged
  }
  function snapshot(){
    if(!state.loaded||state.dirty||readOnly()||state.conflict||state.contextChanged||!base||!state.content.trim())return null
    return {content:state.content,version:base.version,revision:base.revision,source_version:base.source_version,editSerial,generation}
  }
  function beginSend(sent,requestId){
    cancelTimer()
    if(!sent||disposed||sent.generation!==generation||sent.editSerial!==editSerial||state.content!==sent.content
        ||base?.version!==sent.version||state.saving||state.sending||pendingConsumption||readOnly()||state.conflict||state.contextChanged)return null
    pendingConsumption={...sent,requestId};state.sending=true;publish();return pendingConsumption
  }
  async function finishSend(sent){
    if(!sent||disposed||sent.generation!==generation||pendingConsumption?.requestId!==sent.requestId||state.loading)return false
    const current=generation
    state.loading=true;state.error='';loadController=new AbortController();publish()
    try{
      const remote=normalizeAssistantDraft(await read(taskId,loadController.signal))
      if(disposed||current!==generation)return false
      state.writable=remote.writable;state.notice=remote.notice
      const consumed=remote.consumed_request_id===sent.requestId&&remote.version===sent.version+1
        &&remote.content===''&&sameContext(remote,sent)
      const untouched=remote.version===sent.version&&remote.content===sent.content&&sameContext(remote,sent)
      pendingConsumption=null;state.unknown=false
      if(consumed||untouched){
        base=remote
        if(consumed&&editSerial===sent.editSerial&&state.content===sent.content){state.content='';editSerial++;editingContext=context()}
        return true
      }
      state.conflict=true;state.remote=remote
      state.error='发送期间工作站草稿已有其他修改。本机文字已保留，请选择要继续的草稿。'
      return false
    }catch{
      if(disposed||current!==generation)return false
      state.unknown=true;state.error='未能确认发送后的草稿状态，当前文字仍保留。请重新读取工作站草稿，暂不再次发送。'
      return false
    }finally{
      if(current===generation&&!disposed){state.loading=false;state.sending=false;loadController=null;publish();schedule()}
    }
  }
  function dispose(){disposed=true;generation++;cancelTimer();controller?.abort();loadController?.abort()}
  return {reset,reload,edit,updateContext,continueCurrentContext,chooseLocal,useRemote,flush,snapshot,beginSend,finishSend,dispose}
}
