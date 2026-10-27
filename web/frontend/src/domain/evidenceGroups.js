// Presentation groups only: never change page spans, classification or facts.
export function evidenceGroups(documents = []) {
  const groups = []
  const indexTitle = /^(?:证据(?:材料)?(?:目录|清单))(?:[（(][^()（）]{0,50}[)）])?$/u
  for (const document of documents) {
    const title = String(document.title || '').replace(/\s/g, '')
    const isIndex = document.doc_type === 'evidence' && indexTitle.test(title)
    const previous = groups.at(-1)
    const tail = previous?.documents.at(-1)
    const append = !isIndex && previous?.bundle && document.doc_type === 'evidence'
      && document.file_id && document.file_id === tail.file_id
      && Number.isInteger(document.page_start) && Number.isInteger(tail.page_end)
      && document.page_start === tail.page_end + 1
      && document.catalog_seq === tail.catalog_seq
    if (append) previous.documents.push(document)
    else groups.push({ key: document.unit_key, bundle: isIndex, documents: [document] })
  }
  return groups.map(group => ({ ...group, bundle: group.bundle && group.documents.length > 1,
    pending: group.documents.filter(d => d.classification_origin !== 'human' && d.match_tier === 'pending').length,
    page_start: group.documents[0].page_start, page_end: group.documents.at(-1).page_end }))
}
