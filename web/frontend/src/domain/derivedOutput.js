// Derived output metadata never enters editable fields, styles, or dirty snapshots.
export function derivedCellText(cell, output, currentOutputReady) {
  const count = output?.[cell.derived]
  return currentOutputReady && Number.isSafeInteger(count) && count > 0
    ? String(count) + (cell.suffix || '') : '生成后计算'
}
