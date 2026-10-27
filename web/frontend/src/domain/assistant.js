import { normalizeProposal } from './assistantProposal.js'
import { createRequestId } from './workflow.js'
export const assistantToolLabels = {
  read_sources: '读取已有来源', search_sources: '检索已有材料',
  classify_materials: '查看材料分类', check_missing: '检查缺失材料',
  review_archive: '核对归档记录', explain_field: '查看字段依据',
  propose_field_change:'提出字段修改建议',
}

export function assistantHistory(messages) {
  return messages.filter(message => ['user', 'assistant'].includes(message.role)
    && message.state !== 'failed' && message.state !== 'pending')
    .slice(-6).map(message => ({ role: message.role, content: String(message.content || '').slice(0, 1500) }))
}

export function assistantError(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (error?.response?.status === 409) return '当前任务正在整理，待整理完成后再提问。'
  if (error?.response?.status === 503) return '工作站模型尚未就绪，请稍后重试或联系管理员。'
  return '提问未完成。请恢复连接后先读取本案对话和草稿状态，再决定是否重试。'
}

function normalizeAnswer(data,{stored=false}={}) {
  if (!data || typeof data.message !== 'string' || !data.message.trim()) throw new Error('Empty assistant response')
  const items = (Array.isArray(data.items) ? data.items : []).filter(item => item && typeof item.title === 'string')
    .map(item => ({
      title: item.title, text: typeof item.text === 'string' ? item.text : '',
      file_id: typeof item.file_id === 'string' ? item.file_id : null,
      page: Number.isInteger(Number(item.page)) && Number(item.page) > 0 ? Number(item.page) : null,
      field: typeof item.field === 'string' ? item.field : null,
    }))
  const action = ['sources', 'catalog', 'fields'].includes(data.action?.type)
    ? { type: data.action.type, label: typeof data.action.label === 'string' ? data.action.label : '打开核对' } : null
  return { content: data.message, tool: typeof data.tool === 'string' ? data.tool : '', items, action,proposal:data.tool==='propose_field_change'?normalizeProposal({...data.proposal,state:data.proposal_state,notice:data.proposal_notice},{stored:stored||!!data.request_id}):null }
}

export function normalizeAssistantHistory(data){
  if(!data||!Array.isArray(data.messages))throw new Error('没有取得有效的对话记录，请重试。')
  const seen=new Set()
  return data.messages.filter(item=>item&&['user','assistant'].includes(item.role)&&typeof item.content==='string'&&item.id!=null).map(item=>{
    const status=['pending','completed','failed','unknown'].includes(item.status)?item.status:'unknown'
    const answer=item.role==='assistant'?normalizeAnswer({...item,message:item.content},{stored:true}):{content:item.content,items:[],action:null,proposal:null}
    return {...answer,id:String(item.id),request_id:item.request_id,role:item.role,status,state:status==='completed'?'sent':status,revision:item.revision,source_version:item.source_version,created_at:item.created_at}
  }).filter(item=>{if(seen.has(item.id))return false;seen.add(item.id);return true})
}

// Persistent messages stay on the authorized workstation API, never in browser storage.
// Reset/exit aborts requests and rejects late results from another task.
export function createAssistantConversation({ request, readHistory, getContext=()=>({}), onChange = () => {} }) {
  let taskId = '', generation = 0, nextId = 0, controller = null, historyController=null, disposed = false
  const initial=()=>({messages:[],pending:false,error:'',historyLoading:false,historyReady:!readHistory,historyError:'',historyLimited:false,serverPending:false})
  let state = initial()
  const publish = () => onChange({ ...state, messages: [...state.messages] })

  function reset(id) {
    generation++
    controller?.abort()
    historyController?.abort()
    controller = null
    taskId = String(id || '')
    state = initial()
    publish()
    if(readHistory&&taskId)reload()
  }

  async function reload(){
    if(!readHistory||disposed||state.pending||state.historyLoading||!taskId)return false
    const current=generation;historyController=new AbortController();state.historyLoading=true;state.historyError='';publish()
    try{
      const data=await readHistory(taskId,historyController.signal)
      if(disposed||current!==generation)return false
      state.messages=normalizeAssistantHistory(data);state.historyReady=true;state.historyLimited=data.has_more===true;state.error=''
      state.serverPending=state.messages.some(message=>message.status==='pending')
      return true
    }catch(error){if(current!==generation||disposed)return false;state.historyReady=false;state.historyError='暂时无法恢复本案对话，输入仍保留。请重新连接后读取记录，避免重复发送。';return false}
    finally{if(current===generation&&!disposed){state.historyLoading=false;historyController=null;publish()}}
  }

  async function ask(value,{requestId:providedRequestId,draftVersion}={}) {
    const message = String(value || '').trim()
    if (disposed || state.pending || state.historyLoading || !state.historyReady || state.serverPending || !taskId || !message) return false
    if (message.length > 1500) {
      state.error = '每次提问请控制在 1500 字以内。'
      publish()
      return false
    }
    const history = assistantHistory(state.messages)
    const context=getContext()
    if(readHistory&&(!Number.isSafeInteger(context.revision)||typeof context.source_version!=='string')){state.error='当前草稿版本尚未读取完成，请稍后重试。';publish();return false}
    let requestId=null
    try{if(readHistory)requestId=providedRequestId||createRequestId()}catch(error){state.error=error.message;publish();return false}
    const current = generation
    controller = new AbortController()
    const last = state.messages.at(-1)
    const user = last?.role === 'user' && last.state === 'failed' && last.content === message
      ? { ...last, request_id:requestId,state: 'pending' } : { id:'local-'+(++nextId),request_id:requestId,role: 'user', content: message, state: 'pending' }
    if (user.id === last?.id) state.messages[state.messages.length - 1] = user
    else state.messages.push(user)
    state.pending = true
    state.error = ''
    publish()
    try {
      const answer = await request(taskId, readHistory?{message,request_id:requestId,expected_revision:context.revision,source_version:context.source_version,
        ...(Number.isSafeInteger(draftVersion)?{draft_version:draftVersion}:{})}:{message,history}, controller.signal)
      if (disposed || current !== generation) return false
      const result = normalizeAnswer(answer)
      user.state = 'sent'
      user.status='completed';if(answer.user_message_id!=null)user.id=String(answer.user_message_id)
      state.messages.push({id:answer.assistant_message_id!=null?String(answer.assistant_message_id):'local-'+(++nextId),request_id:answer.request_id||requestId,role:'assistant',state:'sent',status:'completed',...result})
      return true
    } catch (error) {
      if (disposed || current !== generation) return false
      user.state = 'failed'
      user.status='failed'
      state.error = assistantError(error)
      if(readHistory&&!error?.response){user.state='unknown';user.status='unknown';state.historyReady=false;state.historyError='回复状态尚未确认。请先读取本案对话记录，系统不会自动重发或重复调用模型。'}
      return false
    } finally {
      if (!disposed && current === generation) {
        state.pending = false
        controller = null
        publish()
      }
    }
  }

  function dispose() {
    disposed = true
    generation++
    controller?.abort()
    historyController?.abort()
    state = initial()
  }
  return { reset, ask, reload, dispose }
}
