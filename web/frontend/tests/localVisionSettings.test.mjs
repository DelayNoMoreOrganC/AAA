import test from 'node:test'
import assert from 'node:assert/strict'
import {loadSfc,mount,content,settle,click,esm} from './vueHarness.mjs'

const loadLocal=(relative,imports)=>loadSfc(relative,imports,{hoistStatic:false})
const unavailable={preset:{download_gb:6.6},ready:false,engine_ready:false,installed:false,hardware:{ram_gb:16,available_ram_gb:7,gpus:[],gpu_verified:false},recommendation:'not_recommended',advice:'不建议批量本地归档',issues:['未安装 Ollama'],benchmark:null}
function button(root,text){if(root.type==='button'&&content(root)===text)return root;return root.children.map(n=>button(n,text)).find(Boolean)}

test('ordinary user can inspect workstation but cannot prepare or run expensive checks',async()=>{
  const requests=[],events=[]
  const component=await loadLocal('../src/components/LocalVisionSettings.vue',{'../api/client':esm({get:async url=>{requests.push(url);return {data:unavailable}},post:async()=>assert.fail('no automatic POST')}),'../stores/auth':{useAuthStore:()=>({isAdmin:false})}})
  const page=mount(component,{onReady:value=>events.push(value)})
  await settle()
  assert.match(content(page.root),/16 GB/);assert.match(content(page.root),/不建议批量本地归档/)
  assert.match(content(page.root),/尚未完成视觉试跑/)
  assert.equal(button(page.root,'准备引擎'),undefined);assert.equal(button(page.root,'试跑视觉识别'),undefined)
  assert.deepEqual(events,[false]);assert.deepEqual(requests,['/settings/local-vision'])
  page.app.unmount()
})

test('admin sees actual prerequisite state; no auto download or false readiness',async()=>{
  const component=await loadLocal('../src/components/LocalVisionSettings.vue',{'../api/client':esm({get:async()=>({data:unavailable}),post:async()=>assert.fail('no automatic POST')}),'../stores/auth':{useAuthStore:()=>({isAdmin:true})}})
  const page=mount(component)
  await settle()
  assert.equal(button(page.root,'准备引擎').props.disabled,true)
  assert.equal(button(page.root,'下载模型（约 6.6 GB）').props.disabled,true)
  assert.match(content(page.root),/均待真实整卷及断网验收/)
  page.app.unmount()
})

test('explicit synthetic trial updates readiness only from returned status',async()=>{
  let ran=false;const events=[],posts=[]
  const status=()=>({...unavailable,installed:true,engine_ready:true,ready:ran,benchmark:ran?{passed:true,seconds:2,loaded_vram_gb:7}:null})
  const component=await loadLocal('../src/components/LocalVisionSettings.vue',{'../api/client':esm({get:async()=>({data:status()}),post:async(url)=>{posts.push(url);ran=true;return {data:{passed:true}}}}),'../stores/auth':{useAuthStore:()=>({isAdmin:true})}})
  const page=mount(component,{onReady:v=>events.push(v)})
  await settle();assert.deepEqual(posts,[])
  click(button(page.root,'试跑视觉识别'));await settle()
  assert.deepEqual(posts,['/settings/local-vision/benchmark']);assert.deepEqual(events,[false,true])
  assert.match(content(page.root),/不代表整卷速度或识别准确率/)
  page.app.unmount()
})
