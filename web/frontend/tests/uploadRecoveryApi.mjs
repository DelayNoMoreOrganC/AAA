// Synthetic intent storage for existing real-SFC tests; no HTTP or disk bytes.
import {loadSfc,esm,find,settle} from './vueHarness.mjs'
import * as integration from '../src/domain/useUploadRecovery.js'
const Panel=await loadSfc('../src/components/UploadRecoveryPanel.vue')
export const uploadImports={'../domain/useUploadRecovery.js':integration,'../components/UploadRecoveryPanel.vue':esm(Panel)}
// Bound waits to the actual upload state rather than assuming a fixed number
// of promises; hashing, full-batch registration and receipt reads add stages.
export async function settleUploads(root){for(let attempt=0;attempt<100;attempt++){await settle();await new Promise(resolve=>setImmediate(resolve));if(!find(root,'upload-in-progress')){await settle();return}}throw Error('synthetic upload did not settle')}
export function withUploadIntentsApi(client){
  const all=new Map(),id=path=>String(path).match(/^\/cases\/([^/]+)/)?.[1],key=path=>String(path).split('/').at(-1)
  const rows=caseId=>{if(!all.has(caseId))all.set(caseId,new Map());return all.get(caseId)}
  return {...client,
    get:async(path,...args)=>path.endsWith('/upload-intents')?{data:{items:Array.from(rows(id(path)).values()).map(item=>({...item})),writable:true,notice:''}}:client.get(path,...args),
    put:async(path,body,...args)=>{
      if(!path.includes('/upload-intents/'))return client.put(path,body,...args)
      const map=rows(id(path)),old=map.get(key(path));if(old&&['filename','file_size','sha256','doc_type'].some(name=>old[name]!==body[name]))throw {response:{status:409}}
      const saved=old||{...body,request_id:key(path),status:'pending',file_id:null};map.set(key(path),saved);return {data:{...saved}}
    },
    delete:async(path,...args)=>{if(!path.includes('/upload-intents/'))return client.delete(path,...args);const item=rows(id(path)).get(key(path));if(item.status==='completed')throw {response:{status:409}};item.status='cancelled';return {data:{...item}}},
    post:async(path,body,config)=>{const response=await client.post(path,body,config);if(path.endsWith('/files')){const item=rows(id(path)).get(config?.headers?.['Idempotency-Key']);if(item){item.status='completed';item.file_id='synthetic-'+item.request_id}};return response},
  }
}
