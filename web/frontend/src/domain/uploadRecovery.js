import {createRequestId} from './workflow.js'
import {hashUploadFile} from './fileDigest.js'

const statuses=new Set(['pending','completed','cancelled','unavailable'])
export function uploadDisplayName(file){return String(file.name||'').replace(/\\/g,'/').split('/').at(-1).replace(/[\x00-\x1f\x7f]/g,'').trim()}
const metadataEqual=(a,b)=>a.filename===b.filename&&a.file_size===b.file_size&&a.sha256===b.sha256&&a.doc_type===b.doc_type
function normalize(data){
  if(!data||!Array.isArray(data.items)||typeof data.writable!=='boolean')throw Error('未取得有效待上传清单')
  const ids=new Set()
  const items=data.items.map(item=>{if(!item||typeof item.request_id!=='string'||ids.has(item.request_id)||typeof item.filename!=='string'||!Number.isSafeInteger(item.file_size)||item.file_size<0||!(/^[0-9a-f]{64}$/.test(item.sha256))||typeof item.doc_type!=='string'||!statuses.has(item.status))throw Error('待上传清单无效');ids.add(item.request_id);return {...item}})
  return {...data,items}
}
const errorMessage=(error,fallback)=>typeof error?.response?.data?.detail==='string'?error.response.data.detail:error?.message||fallback

// File objects live only in memory. Persisted intents contain metadata only.
// A single generation binds every read/hash/register/upload to one user+case.
export function createUploadRecovery({read,register,upload,cancel,getCapabilities,hash=hashUploadFile,makeId=createRequestId,onChange=()=>{},onProgress=()=>{}}){
  let caseId='',generation=0,disposed=false,controller=null,loadingPromise=null
  let remote=[],local=new Map(),state={loaded:false,loading:false,busy:false,error:'',notice:'',writable:true,matchMessages:[]}
  const pending=()=>remote.filter(item=>item.status==='pending')
  function publish(){
    const rows=[...pending().map(item=>({...item,file:local.get(item.request_id)?.file||null,local:false,message:local.get(item.request_id)?.message||''})),...Array.from(local.values()).filter(item=>!remote.some(row=>row.request_id===item.request_id)).map(item=>({...item,local:true}))]
    onChange({...state,items:remote.map(item=>({...item})),rows,pendingCount:rows.length,canRetry:rows.some(item=>item.file),navigationDirty:state.busy||rows.some(item=>item.local),blocked:!state.loaded||!!state.error||state.loading||state.busy||rows.length>0})
  }
  function apply(data){const valid=normalize(data);remote=valid.items;state.loaded=true;state.writable=valid.writable;state.notice=valid.notice||'';for(const item of remote){if(item.status!=='pending')local.delete(item.request_id)};return valid}
  const current=epoch=>!disposed&&generation===epoch
  async function fetchList(epoch,signal){const data=await read(caseId,signal);if(!current(epoch))return false;apply(data);return true}
  async function reload(){if(disposed||!caseId||state.busy||state.loading)return false;const epoch=generation;state.loading=true;state.error='';controller=new AbortController();publish();loadingPromise=(async()=>{try{return await fetchList(epoch,controller.signal)}catch(error){if(current(epoch))state.error='未能恢复待上传清单，请先重新读取，暂不开始新的导入。';return false}finally{if(current(epoch)){state.loading=false;publish()}}})();try{return await loadingPromise}finally{if(current(epoch))loadingPromise=null}}
  function reset(scope){generation++;controller?.abort();caseId=String(scope?.caseId||'');remote=[];local=new Map();loadingPromise=null;state={loaded:false,loading:false,busy:false,error:'',notice:'',writable:true,matchMessages:[]};publish();if(caseId)reload()}
  function validate(file){const cap=getCapabilities(),name=uploadDisplayName(file),ext='.'+name.split('.').at(-1).toLowerCase();if(!name||name.length>250)return '文件名为空或过长，请重命名后重选';if(!cap.supported_extensions.includes(ext))return '此格式暂不支持，尚未登记到工作站';if(file.size===0)return '文件为空，尚未登记到工作站';if(file.size>cap.max_upload_mb*1024*1024)return '超过单份 '+cap.max_upload_mb+' MB 限制，尚未登记到工作站';return ''}
  async function prepare(item,signal){const message=validate(item.file);item.message=message;if(message)return false;if(!item.sha256)item.sha256=await hash(item.file,{signal});return true}
  async function execute(onlyIds=null){
    if(disposed||!caseId||state.busy)return false
    const epoch=generation
    if(loadingPromise)await loadingPromise
    if(!current(epoch)||state.busy)return false
    if(state.loaded&&!state.error&&!state.writable)await reload()
    if(!current(epoch)||state.busy)return false
    if(!state.loaded||state.error||!state.writable){publish();return false}
    state.busy=true;state.error='';controller=new AbortController();const signal=controller.signal;publish()
    try{
      const unregistered=Array.from(local.values()).filter(item=>!remote.some(row=>row.request_id===item.request_id))
      // Hash/validate all files before registration; complete the whole valid
      // batch's registration before transferring its first byte.
      const valid=[]
      for(const item of unregistered){onProgress(0,unregistered.length,'正在核对 '+item.filename);if(await prepare(item,signal))valid.push(item);if(!current(epoch))return false}
      for(const item of valid){const body={filename:item.filename,file_size:item.file_size,sha256:item.sha256,doc_type:item.doc_type};try{await register(caseId,item.request_id,body,signal)}catch(error){if(!current(epoch))return false;item.message='登记结果未确认，请重新读取后重试，原请求编号保留';try{await fetchList(epoch,signal)}catch{};state.error=errorMessage(error,'待上传清单登记未完成');return false};if(!current(epoch))return false;remote=remote.filter(row=>row.request_id!==item.request_id);remote.push({...body,request_id:item.request_id,status:'pending',file_id:null});publish()}
      // Read back before uploads: an interrupted previous attempt may already
      // have completed, or a different tab may have cancelled an intent.
      if(!(await fetchList(epoch,signal)))return false
      const ready=pending().filter(item=>local.has(item.request_id)&&(!onlyIds||onlyIds.has(item.request_id)));let done=0
      for(const item of ready){const bound=local.get(item.request_id);if(!bound?.file)continue
        try{await upload(caseId,bound.file,item,signal);if(!current(epoch))return false;local.delete(item.request_id);remote=remote.map(row=>row.request_id===item.request_id?{...row,status:'completed'}:row)}
        catch(error){if(!current(epoch))return false;bound.message=errorMessage(error,'导入失败，请重试');try{await fetchList(epoch,signal)}catch{state.error='上传结果尚未确认，请重新读取待上传清单后继续。';return false}}
        done++;onProgress(done,ready.length,item.filename);publish()
      }
      if(!(await fetchList(epoch,signal)))return false
      return pending().length===0&&local.size===0
    }catch(error){if(current(epoch))state.error=errorMessage(error,'文件核对或清单读取失败，未完成项仍保留');return false}
    finally{if(current(epoch)){state.busy=false;publish()}}
  }
  async function add(files){if(disposed||state.busy)return false;state.matchMessages=[];const selected=new Set();try{for(const file of files){const existing=Array.from(local.values()).find(item=>item.file===file);if(existing){selected.add(existing.request_id);continue};const request_id=makeId();selected.add(request_id);local.set(request_id,{request_id,file,filename:uploadDisplayName(file),file_size:file.size,doc_type:'default',status:'pending',message:''})}}catch(error){state.error=errorMessage(error,'无法生成安全请求编号');publish();return false}publish();return execute(selected)}
  async function recover(files){
    if(disposed||state.busy)return false;const epoch=generation;if(loadingPromise)await loadingPromise
    if(!current(epoch)||state.busy)return false
    if(!state.loaded||state.error||!state.writable)return false
    state.busy=true;state.matchMessages=[];controller=new AbortController();const signal=controller.signal;publish()
    try{if(!(await fetchList(epoch,signal)))return false
      const matches=new Map(),consumed=new Set()
      for(const file of new Set(files)){const invalid=validate(file);if(invalid){state.matchMessages.push(uploadDisplayName(file)+'：'+invalid);continue};const candidate={filename:uploadDisplayName(file),file_size:file.size,sha256:await hash(file,{signal}),doc_type:'default'};if(!current(epoch))return false
        const found=remote.filter(item=>metadataEqual(item,candidate)),available=found.filter(item=>!consumed.has(item.request_id)).sort((a,b)=>String(a.created_at||'').localeCompare(String(b.created_at||''))||a.request_id.localeCompare(b.request_id)),waiting=available.find(item=>item.status==='pending'),completed=available.find(item=>item.status==='completed')
        if(waiting){consumed.add(waiting.request_id);matches.set(waiting.request_id,{...waiting,file,message:''})}
        else if(completed){consumed.add(completed.request_id);state.matchMessages.push(candidate.filename+'：已导入 1 份，已跳过')}
        else if(found.some(item=>['pending','completed'].includes(item.status)))state.matchMessages.push(candidate.filename+'：选择的份数多于清单，超出的文件未作为新增材料上传')
        else if(found.length)state.matchMessages.push(candidate.filename+'：原待办已取消或原件已变更，不自动重新导入')
        else state.matchMessages.push(candidate.filename+'：与待上传清单不匹配，未作为新增材料上传')
      }
      for(const [id,item] of matches)local.set(id,item)
      return true
    }catch(error){if(current(epoch))state.error=errorMessage(error,'恢复核对失败，未开始上传');return false}
    finally{if(current(epoch)){state.busy=false;publish()}}
  }
  async function remove(id){if(disposed||state.busy)return false;const item=remote.find(row=>row.request_id===id);if(!item){local.delete(id);publish();return true};if(item.status!=='pending')return false;const epoch=generation;state.busy=true;controller=new AbortController();publish();try{await cancel(caseId,id,controller.signal);if(!current(epoch))return false;local.delete(id);remote=remote.map(row=>row.request_id===id?{...row,status:'cancelled'}:row);return true}catch(error){if(current(epoch))state.error=errorMessage(error,'取消结果未确认，请重新读取清单');return false}finally{if(current(epoch)){state.busy=false;publish()}}}
  function dispose(){disposed=true;generation++;controller?.abort()}
  return {reset,reload,add,recover,retry:execute,remove,dispose}
}
