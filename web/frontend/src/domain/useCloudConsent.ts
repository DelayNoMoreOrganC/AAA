import { computed, ref, watch } from 'vue'
import { createCloudConsent } from './processingPrivacy.js'

export function useCloudConsent(mode:()=>string,batch:()=>string){
  const consent=createCloudConsent(),checked=ref(false)
  function sync(){consent.update(mode(),batch());checked.value=consent.approved}
  watch([mode,batch],sync,{immediate:true,flush:'sync'})
  const approved=computed({get:()=>checked.value,set:(value:boolean)=>{sync();consent.approve(value);checked.value=consent.approved}})
  function reset(){consent.reset();checked.value=false}
  function payload(){sync();return consent.payload()}
  return {approved,reset,payload}
}
