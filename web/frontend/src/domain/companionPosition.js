const margin=12
export function clampCompanion(point,viewport,size){
  const maxX=Math.max(margin,viewport.width-size.width-margin),maxY=Math.max(margin,viewport.height-size.height-margin)
  return {x:Math.min(maxX,Math.max(margin,point.x)),y:Math.min(maxY,Math.max(margin,point.y))}
}
export function restoreCompanion(saved,viewport,size){
  const valid=saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y)&&saved.x>=0&&saved.x<=1&&saved.y>=0&&saved.y<=1
  return clampCompanion({x:valid?saved.x*(viewport.width-size.width):viewport.width-size.width-22,y:valid?saved.y*(viewport.height-size.height):viewport.height-size.height-18},viewport,size)
}
export function saveCompanion(point,viewport,size){
  return {x:Math.max(0,Math.min(1,point.x/Math.max(1,viewport.width-size.width))),y:Math.max(0,Math.min(1,point.y/Math.max(1,viewport.height-size.height)))}
}
export function companionPanel(point,viewport,size){
  const width=Math.min(420,viewport.width-24),gap=8
  const left=Math.max(12,Math.min(point.x+size.width-width,viewport.width-width-12))
  const above=point.y-gap-12,below=viewport.height-point.y-size.height-gap-12
  return above>=below?{position:'fixed',left:left+'px',right:'auto',top:'auto',bottom:(viewport.height-point.y+gap)+'px',width:width+'px',maxHeight:Math.max(0,Math.min(600,above))+'px'}:{position:'fixed',left:left+'px',right:'auto',bottom:'auto',top:(point.y+size.height+gap)+'px',width:width+'px',maxHeight:Math.max(0,Math.min(600,below))+'px'}
}
