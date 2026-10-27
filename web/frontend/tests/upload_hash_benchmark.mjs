// Synthetic Node-only component benchmark. No browser, source file or model IO.
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile} from 'node:fs/promises'
import {performance} from 'node:perf_hooks'
import {hashUploadFile} from '../src/domain/fileDigest.js'

const sourceUrl = new URL('../src/domain/fileDigest.js', import.meta.url)
const sourceDigest = async () => createHash('sha256').update(await readFile(sourceUrl)).digest('hex')
const sourceBefore = await sourceDigest()
const size = 100 * 1024 * 1024
const blockLimit = 1024 * 1024
const reference = createHash('sha256')
const before = process.memoryUsage()
let reads = 0, largestRead = 0, nextOffset = 0, observedRss = before.rss
const file = {size, slice(start, end) {
  assert.equal(start, nextOffset, 'Each source byte is read once, in order')
  assert.ok(end > start && end - start <= blockLimit && end <= size)
  nextOffset = end
  return {async arrayBuffer() {
    const bytes = new Uint8Array(end - start)
    for (let i = 0; i < bytes.length; i++) bytes[i] = (start + i) % 251
    reference.update(bytes)
    reads++
    largestRead = Math.max(largestRead, bytes.length)
    observedRss = Math.max(observedRss, process.memoryUsage().rss)
    return bytes.buffer
  }}
}}
const start = performance.now()
const digest = await hashUploadFile(file)
const elapsed = performance.now() - start
assert.equal(nextOffset, size)
assert.equal(digest, reference.digest('hex'))
assert.equal(await sourceDigest(), sourceBefore, 'Production source changed during benchmark')
const after = process.memoryUsage()
console.log(JSON.stringify({scope:'synthetic Node component; not browser or full archive throughput',
  node:process.version, synthetic_bytes:size, source_sha256:sourceBefore,
  sha256:digest, independently_matches_node_crypto:true, reads, largest_read_bytes:largestRead,
  elapsed_ms:Number(elapsed.toFixed(3)),
  duration_includes:'synthetic data creation, reference Node crypto and production digest',
  rss_before:before.rss,rss_after:after.rss,sampled_rss_max:Math.max(observedRss,after.rss),
  memory_limit:'RSS samples are not a measured process peak or browser memory usage',
  model_requests:0,real_files_read:0}, null, 2))
