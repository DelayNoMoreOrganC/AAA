export function normalizeProposal(value,{stored=false}={}) {
  if(!value||!['id','field','before','after','reason','source_version','expires_at'].every(key=>typeof value[key]==='string')||!value.id||!value.field||!Number.isSafeInteger(value.revision)||value.revision<1)return null
  if(!stored&&(typeof value.proposal_token!=='string'||!value.proposal_token))return null
  const result=Object.fromEntries(['id','field','before','after','reason','revision','source_version','expires_at'].map(key=>[key,value[key]]))
  if(typeof value.proposal_token==='string'&&value.proposal_token)result.proposal_token=value.proposal_token
  if(stored){result.persisted=true;result.state=['pending','applying','applied','stale','expired'].includes(value.state)?value.state:'pending';if(typeof value.notice==='string')result.notice=value.notice}
  return result
}

export function proposalIsStale(proposal,revision,sourceVersion) {
  return proposal.revision!==revision||proposal.source_version!==sourceVersion||['stale','expired'].includes(proposal.state)||Date.parse(proposal.expires_at)<=Date.now()
}

export function createProposalApplication({request,beforeApply=async()=>'',beforeRecover=beforeApply,onChange=()=>{},onApplied=()=>{},onRecovered=()=>{},onUncertain=async()=>{}}) {
  let state={},busy=false,generation=0,controller=null
  const publish=()=>onChange({...state})
  return {
    async apply(taskId,proposal,{revision,sourceVersion,disabled=false}={}){
      const value=normalizeProposal(proposal,{stored:proposal?.persisted===true})
      if(!value||busy||state[value.id]?.applied||['applying','applied'].includes(value.state))return false
      const current=generation
      if(disabled||proposalIsStale(value,revision,sourceVersion)||state[value.id]?.stale){state[value.id]={error:disabled?'当前任务不可修改，请完成正在进行的操作后重试。':'草稿或材料已变化，请重新提出修改。',stale:!disabled};publish();return false}
      busy=true;state[value.id]={pending:true,error:'',applied:false};publish()
      let requested=false
      try{
        const blocked=await beforeApply(value.revision)
        if(current!==generation)return false
        if(blocked)throw new Error(blocked)
        controller=new AbortController()
        requested=true
        const data=await request(taskId,{...(value.persisted?{proposal_id:value.id}:{proposal_token:value.proposal_token}),expected_revision:value.revision},controller.signal)
        if(current!==generation)return false
        if(data?.applied!==true||String(data.task?.id)!==String(taskId)||data.task?.revision<=value.revision)throw new Error('未取得修改后的草稿，请刷新核对后重试。')
        state[value.id]={pending:false,applied:true,error:''};onApplied(data.task);return true
      }catch(error){
        if(current!==generation)return false
        const detail=error?.response?.data?.detail
        const stale=error?.response?.status===409
        state[value.id]={pending:true,applied:false,stale,error:(typeof detail==='string'?detail:error.message||'修改未能保存，请重试。')+(stale?' 请重新告诉助理需要修改的内容。':'')}
        // A failed transport or 5xx can follow a committed write/journal. Read
        // the persisted proposal before inviting another adoption; never replay.
        if(requested&&(!error?.response||error.response.status>=500)){
          publish()
          try{await onUncertain()}catch{/* The history surface presents its retry state. */}
        }
        return false
      }finally{if(current===generation){busy=false;controller=null;if(state[value.id])state[value.id].pending=false;publish()}}
    },
    async recover(taskId,proposal,{revision,disabled=false}={}){
      const value=normalizeProposal(proposal,{stored:true})
      if(!value||value.state!=='applying'||disabled||busy||!Number.isSafeInteger(revision))return false
      const current=generation;busy=true;state[value.id]={pending:true,error:''};publish()
      try{
        const blocked=await beforeRecover(revision);if(current!==generation)return false;if(blocked)throw new Error(blocked)
        controller=new AbortController()
        // This flag is essential: another tab may have restored the proposal
        // to pending already. A recovery click is never adoption authorization.
        await request(taskId,{proposal_id:value.id,expected_revision:revision,recover_only:true},controller.signal)
        if(current!==generation)return false
        state[value.id]={pending:false,error:'恢复状态已更新，请重新核对建议后决定是否采用。'};onRecovered();return true
      }catch(error){
        if(current!==generation)return false
        const detail=error?.response?.data?.detail
        state[value.id]={pending:false,error:typeof detail==='string'?detail:error.message||'尚未确认恢复结果，请重新读取记录。'}
        if(error?.response)onRecovered()
        return false
      }finally{if(current===generation){busy=false;controller=null;if(state[value.id])state[value.id].pending=false;publish()}}
    },
    reset(){generation++;controller?.abort();controller=null;busy=false;state={};publish()},
  }
}
