export function lineCellValue(lines,index,remaining=false){return remaining?lines.slice(index).join('\n'):lines[index]||''}
export function updateLineCell(lines,index,value,remaining=false){const next=[...lines];while(next.length<=index)next.push('');if(remaining)next.splice(index,next.length-index,...String(value).split(/\r?\n/));else next[index]=value;return next.join('\n').replace(/\n+$/,'')}
