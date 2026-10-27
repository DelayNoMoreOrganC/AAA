// Incremental SHA-256 keeps browser memory bounded and also works on LAN HTTP
// where crypto.subtle is unavailable. Nothing is sent to a model or stored here.
const K=new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2])
const rotate=(value,bits)=>(value>>>bits)|(value<<(32-bits))
export function createSha256(){
  const h=new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]),w=new Uint32Array(64),tail=new Uint8Array(64)
  let used=0,length=0,finished=false
  function block(bytes,offset){
    for(let i=0;i<16;i++){const j=offset+i*4;w[i]=(bytes[j]<<24)|(bytes[j+1]<<16)|(bytes[j+2]<<8)|bytes[j+3]}
    for(let i=16;i<64;i++){const x=w[i-15],y=w[i-2];w[i]=w[i-16]+(rotate(x,7)^rotate(x,18)^(x>>>3))+w[i-7]+(rotate(y,17)^rotate(y,19)^(y>>>10))}
    let [a,b,c,d,e,f,g,z]=h
    for(let i=0;i<64;i++){const t1=(z+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+K[i]+w[i])>>>0,t2=((rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c)))>>>0;z=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0}
    for(const [i,value] of [a,b,c,d,e,f,g,z].entries())h[i]+=value
  }
  return {
    update(bytes){if(finished)throw Error('摘要已完成');length+=bytes.length;let offset=0
      if(used){const count=Math.min(64-used,bytes.length);tail.set(bytes.subarray(0,count),used);used+=count;offset=count;if(used===64){block(tail,0);used=0}}
      for(;offset+64<=bytes.length;offset+=64)block(bytes,offset)
      if(offset<bytes.length){tail.set(bytes.subarray(offset),0);used=bytes.length-offset}
    },
    hex(){if(finished)throw Error('摘要已完成');finished=true;const end=new Uint8Array(used<56?64:128);end.set(tail.subarray(0,used));end[used]=128;const bits=length*8,view=new DataView(end.buffer);view.setUint32(end.length-8,Math.floor(bits/0x100000000));view.setUint32(end.length-4,bits>>>0);for(let offset=0;offset<end.length;offset+=64)block(end,offset);return Array.from(h,v=>v.toString(16).padStart(8,'0')).join('')},
  }
}
export async function hashUploadFile(file,{signal,chunkSize=1024*1024}={}){
  const hash=createSha256()
  for(let offset=0;offset<file.size;offset+=chunkSize){if(signal?.aborted)throw Error('已取消文件核对');const buffer=await file.slice(offset,Math.min(offset+chunkSize,file.size)).arrayBuffer();if(signal?.aborted)throw Error('已取消文件核对');hash.update(new Uint8Array(buffer))}
  if(signal?.aborted)throw Error('已取消文件核对');return hash.hex()
}
