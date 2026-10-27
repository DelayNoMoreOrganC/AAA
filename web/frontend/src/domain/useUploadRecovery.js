import {ref,watch,onUnmounted} from 'vue'
import {createUploadRecovery} from './uploadRecovery.js'
export function useUploadRecovery({client,getScope,getCapabilities,onProgress=()=>{}}){
  const state=ref({loaded:false,loading:false,busy:false,error:'',notice:'',rows:[],items:[],matchMessages:[],pendingCount:0,canRetry:false,navigationDirty:false,blocked:true})
  const queue=createUploadRecovery({
    read:async(id,signal)=>(await client.get('/cases/'+encodeURIComponent(id)+'/upload-intents',{signal})).data,
    register:async(id,key,body,signal)=>(await client.put('/cases/'+encodeURIComponent(id)+'/upload-intents/'+encodeURIComponent(key),body,{signal})).data,
    cancel:async(id,key,signal)=>(await client.delete('/cases/'+encodeURIComponent(id)+'/upload-intents/'+encodeURIComponent(key),{signal})).data,
    upload:async(id,file,item,signal)=>{const body=new FormData();body.append('file',file,item.filename);body.append('doc_type',item.doc_type);return (await client.post('/cases/'+encodeURIComponent(id)+'/files',body,{headers:{'Idempotency-Key':item.request_id},signal})).data},
    getCapabilities,onProgress,onChange:value=>{state.value=value},
  })
  watch(()=>{const scope=getScope();return [scope.caseId,scope.accountScope]},()=>queue.reset(getScope()),{immediate:true})
  onUnmounted(()=>queue.dispose())
  return {state,queue}
}
