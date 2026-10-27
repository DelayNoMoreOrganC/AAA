import test from 'node:test'
import assert from 'node:assert/strict'
import { derivedCellText } from '../src/domain/derivedOutput.js'

const cell={derived:'volume_page_count',suffix:' 页'}
test('cover count uses only the current verified positive integer output, not a business field', () => {
  const metadata={volume_page_count:113,count_scope:'整卷 PDF 总页数，含封面、目录、系统表'}
  assert.equal(derivedCellText(cell,metadata,true),'113 页')
  assert.equal(derivedCellText(cell,metadata,false),'生成后计算')
  assert.equal(derivedCellText(cell,{fields:{volume_page_count:999}},true),'生成后计算')
  assert.deepEqual(metadata,{volume_page_count:113,count_scope:'整卷 PDF 总页数，含封面、目录、系统表'})
})
test('old output without metadata and malformed counts never show a fabricated page count', () => {
  for(const value of [undefined,null,0,-1,1.5,'12',true,NaN,Infinity]) {
    assert.equal(derivedCellText(cell,{volume_page_count:value},true),'生成后计算')
  }
  assert.equal(derivedCellText(cell,undefined,true),'生成后计算')
})
