"""Bounded document context across visual batches; hints never decide grouping."""
from evidence_index import is_index


class ClassificationContext:
    def __init__(self):
        self.document = None
        self.evidence_index = None

    def accept(self, rows):
        for row in rows:
            if not row["document_start"]:
                continue
            self.document = dict(row)
            if row["doc_type"] == "evidence" and is_index(row.get("title", "")):
                self.evidence_index = dict(row)
            elif row["doc_type"] not in ("evidence", "unknown"):
                self.evidence_index = None

    def reference_ids(self, previous, batch):
        # Previous page + current document start + evidence index: <=3 pages.
        result = []
        for row in (previous, self.document, self.evidence_index):
            if row and row["page_id"] not in batch and row["page_id"] not in result:
                result.append(row["page_id"])
        return result

    def describe(self):
        def hint(row):
            return {k: row[k] for k in ("page_id", "doc_type", "title", "document_role", "procedure_stage") if k in row} if row else None
        return {"当前文书首页候选": hint(self.document), "证据清单候选": hint(self.evidence_index),
                "性质": "前批识别候选，仅供比较；不是确认事实，不得覆盖当前页的明确新文书证据。"}
