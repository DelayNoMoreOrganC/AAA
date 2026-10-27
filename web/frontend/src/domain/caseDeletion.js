export const CASES_CHANGED_EVENT='gd:cases-changed'

export function caseDeletionBlocked(record,disabled=false) {
  if(!record?.id)return '案件信息尚未加载。'
  if(['pending','running'].includes(record.last_task_status))return '案件正在排队或处理中，完成后才能删除。'
  if(record.can_delete===false)return '当前账号没有删除此案件的权限。'
  return disabled?'当前操作尚未完成，请稍后删除。':''
}

export function caseDeletionError(error) {
  const detail=error?.response?.data?.detail
  if(typeof detail==='string'&&detail.trim())return detail
  const status=error?.response?.status
  return ({403:'当前账号没有删除此案件的权限。',404:'案件不存在，或当前账号无权删除。',409:'案件正在处理或状态已变化，请刷新后重试。'})[status]||'未能确认删除结果。请检查连接并刷新案件列表后重试。'
}

// The selected case is frozen when the confirmation opens. Only an explicit
// confirm can issue DELETE; polling, cancelling and retries never choose a new id.
export function createCaseDeletion({remove,onDeleted=()=>{},onChange=()=>{}}) {
  let state={opened:false,pending:false,error:'',selected:null},disposed=false
  const publish=()=>{if(!disposed)onChange({...state})}
  return {
    open(record,disabled=false){
      if(disposed||state.pending||state.opened||caseDeletionBlocked(record,disabled))return false
      state={opened:true,pending:false,error:'',selected:{id:String(record.id),title:String(record.title||'未命名案件')}}
      publish();return true
    },
    cancel(){
      if(disposed||state.pending)return false
      state={opened:false,pending:false,error:'',selected:null};publish();return true
    },
    async confirm(record,disabled=false){
      if(disposed||!state.opened||state.pending||!state.selected)return false
      const id=state.selected.id
      const blocked=String(record?.id)!==id?'案件已变化，请关闭弹窗后重新选择。':caseDeletionBlocked(record,disabled)
      if(blocked){state.error=blocked;publish();return false}
      state.pending=true;state.error='';publish()
      try{
        const response=await remove(id)
        if(![202,204].includes(response?.status))throw new Error('unexpected delete result')
        const result={caseId:id,caseTitle:state.selected.title,cleanupPending:response.status===202,message:response.status===202?(typeof response.data?.message==='string'?response.data.message:'案件已从列表删除，部分工作站文件仍待清理。'):'案件已删除'}
        state={opened:false,pending:false,error:'',selected:null};publish()
        if(!disposed)onDeleted(result)
        return true
      }catch(error){
        if(!disposed){state.pending=false;state.error=caseDeletionError(error);publish()}
        return false
      }
    },
    dispose(){disposed=true},
  }
}

// App-level, session-only recovery for cases whose database rows were deleted
// but whose isolated workstation files still need cleaning. No arbitrary id can
// be retried: it must first arrive in an actual 202 deletion result.
export function createCaseCleanupQueue({remove,onChange=()=>{},onCleaned=()=>{}}) {
  const entries=new Map();let version=0
  const publish=()=>onChange([...entries.values()].map(entry=>({...entry})))
  return {
    add(result){
      if(result?.cleanupPending!==true||typeof result.caseId!=='string'||!result.caseId)return false
      const previous=entries.get(result.caseId)
      const details={caseId:result.caseId,title:String(result.caseTitle||'已删除案件'),message:String(result.message||'部分工作站文件仍待清理。')}
      if(previous)Object.assign(previous,details)
      else entries.set(result.caseId,{...details,error:'',pending:false})
      publish();return true
    },
    async retry(caseId){
      const entry=entries.get(caseId),requestVersion=version
      if(!entry||entry.pending)return false
      entry.pending=true;entry.error='';publish()
      try{
        const response=await remove(caseId)
        if(requestVersion!==version)return false
        if(response?.status===204){entries.delete(caseId);publish();onCleaned(caseId);return true}
        if(response?.status!==202)throw new Error('unexpected cleanup result')
        entry.pending=false;entry.message=typeof response.data?.message==='string'?response.data.message:'文件仍未清理完成，请稍后重试。';publish();return false
      }catch(error){
        if(requestVersion===version){entry.pending=false;entry.error=caseDeletionError(error);publish()}
        return false
      }
    },
    reset(){version++;entries.clear();publish()},
  }
}
