import test from 'node:test'
import assert from 'node:assert/strict'
import { createSessionRecovery } from '../src/domain/sessionRecovery.js'

const unauthorized = (token='old', url='/tasks/1') => ({response:{status:401},config:{url,headers:{Authorization:'Bearer '+token}}})
function context(refresh) {
  const state={token:'old',refreshToken:'refresh-old'}, calls=[]
  let expired=0
  const recover=createSessionRecovery({getSession:()=>({...state}),refresh,
    save:tokens=>Object.assign(state,{token:tokens.access_token,refreshToken:tokens.refresh_token}),
    expire:()=>{expired++;state.token='';state.refreshToken=''},
    retry:async config=>{calls.push(config);return 'saved'},
  })
  return {state,calls,recover,get expired(){return expired}}
}

test('concurrent expiry shares one refresh and retries both edits with new access token',async()=>{
  let release, count=0
  const c=context(()=>{count++;return new Promise(resolve=>{release=resolve})})
  const a=c.recover(unauthorized()), b=c.recover(unauthorized())
  assert.equal(count,1)
  release({access_token:'new',refresh_token:'refresh-new'})
  assert.deepEqual(await Promise.all([a,b]),['saved','saved'])
  assert.equal(c.calls.length,2)
  assert.ok(c.calls.every(config=>config.headers.Authorization==='Bearer new'&&config.__sessionRetried))
  assert.equal(c.expired,0)
})

test('network failure preserves login and allows a later retry',async()=>{
  let attempt=0
  const c=context(async()=>{if(!attempt++)throw new Error('offline');return {access_token:'new',refresh_token:'refresh-new'}})
  await assert.rejects(c.recover(unauthorized()),/offline/)
  assert.equal(c.state.token,'old');assert.equal(c.expired,0);assert.equal(c.calls.length,0)
  assert.equal(await c.recover(unauthorized()),'saved')
})

test('only refresh authorization rejection ends the session once',async()=>{
  for(const status of [401,403,500]) {
    const failure={response:{status}}
    const c=context(async()=>{throw failure})
    await assert.rejects(Promise.all([c.recover(unauthorized()),c.recover(unauthorized())]))
    assert.equal(c.expired,status===500?0:1)
  }
})

test('late 401 from old token reuses already renewed token without another refresh',async()=>{
  const c=context(()=>{throw new Error('unexpected refresh')})
  c.state.token='new'
  assert.equal(await c.recover(unauthorized()),'saved')
  assert.equal(c.calls[0].headers.Authorization,'Bearer new')
})

test('login failures and second 401 never recurse or erase unrelated session',async()=>{
  const c=context(()=>{throw new Error('unexpected refresh')})
  const login=unauthorized('old','/auth/login')
  await assert.rejects(c.recover(login))
  const retried=unauthorized();retried.config.__sessionRetried=true
  await assert.rejects(c.recover(retried))
  assert.equal(c.calls.length,0);assert.equal(c.expired,0)
})

test('in-flight refresh cannot restore a logged-out or newly signed-in account',async()=>{
  let release
  const c=context(()=>new Promise(resolve=>{release=resolve}))
  const result=c.recover(unauthorized())
  Object.assign(c.state,{token:'other-account',refreshToken:'other-refresh'})
  release({access_token:'old-account-new',refresh_token:'old-account-refresh'})
  await assert.rejects(result,/登录状态已改变/)
  assert.equal(c.state.token,'other-account');assert.equal(c.calls.length,0)
})
