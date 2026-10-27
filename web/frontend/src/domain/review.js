/** Save only loaded, changed editors; any failure stops the entire operation. */
export async function saveReviewEditors(names, editors, activeName = '') {
  let saved = 0
  for (const name of names) {
    const editor = editors[name]
    if (!editor) continue
    if (!editor.isLoaded?.()) {
      if (name === activeName) throw new Error(name + '尚未加载完成，保存和生成已停止')
      continue
    }
    if (!editor.hasUnsavedChanges?.()) continue
    const save = editor.saveChanges || editor.saveDocx
    let success = false
    try { success = !!save && await save.call(editor) === true } catch { success = false }
    if (!success) throw new Error(name + '保存失败，内容已保留，尚未生成归档')
    if (editor.hasUnsavedChanges?.()) throw new Error(name + '保存期间发生了新修改，请再次保存后生成')
    saved++
  }
  return saved
}
export function unresolvedMissing(items, decisions) {
  return items.filter(item => {
    if (isRequiredMissing(item)) return true
    const decision = decisions[item.seq]
    return !decision || !['skip', 'not_applicable'].includes(decision.action) || !String(decision.reason || '').trim()
  })
}

export function isRequiredMissing(item) {
  return item?.found !== true && item?.legal_requirement_verified === true && item?.requirement === 'required'
}

