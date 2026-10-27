// A synthetic CAS API for SFC tests. No browser storage, transport or model.
export function withAssistantDraftApi(client,{revision=7,sourceVersion='synthetic-v1',writable=true}={}) {
  const records=new Map()
  const key=path=>String(path).match(/\/tasks\/([^/]+)\//)?.[1]
  const initial=()=>({content:'',version:0,revision,source_version:sourceVersion,task_revision:revision,task_source_version:sourceVersion,writable,notice:'',updated_at:null,consumed_request_id:null})
  const getRecord=id=>records.get(id)||initial()
  return {...client,
    get:async(path,...args)=>path.endsWith('/assistant/draft')?{data:structuredClone(getRecord(key(path)))}:client.get(path,...args),
    put:async(path,body,...args)=>{
      if(!path.endsWith('/assistant/draft'))return client.put(path,body,...args)
      const id=key(path),old=getRecord(id)
      if(body.expected_version!==old.version||body.expected_revision!==old.task_revision||body.source_version!==old.task_source_version||!old.writable)throw {response:{status:409,data:{detail:'全虚构草稿版本冲突'}}}
      const saved={...old,content:body.content,version:old.version+1,revision:body.expected_revision,source_version:body.source_version,consumed_request_id:null}
      records.set(id,saved);return {data:structuredClone(saved)}
    },
    post:async(path,body,...args)=>{
      const response=await client.post(path,body,...args)
      // Default test handlers that throw represent pre-transaction rejection.
      // Dedicated atomic-consumption tests model the commit-before-error case.
      if(path.endsWith('/assistant')&&Number.isSafeInteger(body.draft_version)){
        const id=key(path),old=getRecord(id)
        if(old.version!==body.draft_version||old.content.trim()!==body.message.trim())throw {response:{status:409}}
        records.set(id,{...old,content:'',version:old.version+1,consumed_request_id:body.request_id})
      }
      return response
    },
  }
}
