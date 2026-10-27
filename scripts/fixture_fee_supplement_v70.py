"""Hash-locked fictional initial volume and fee supplement; no AI accuracy claim."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'artifacts/fee-supplement-v70'


def build():
    import fitz
    BASE.mkdir(exist_ok=False)
    text = ('律师费结算单\n委托人：虚构甲银行\n案号：(2026)粤0999民初6401号\n'
            '应收业务费：5000元\n已收业务费：2000元\n尚欠业务费：3000元\n应退业务费：0元\n'
            '完全虚构验收材料，无实际收付款。')
    source = BASE / '虚构补充律师费结算单.pdf'
    with fitz.open() as doc:
        p = doc.new_page()
        assert p.insert_textbox(fitz.Rect(52, 52, 543, 760), text, fontname='china-s', fontsize=14) >= 0
        doc.save(source)
    (BASE / 'registry.json').write_text(json.dumps(dict(
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(), pages=1)), encoding='utf8')


def analyze(paths, case_type, data, supplied=None):
    import fitz
    from fixture_execution_sources_v65 import analyze as original
    from fixture_execution_v64 import TRIAL
    from fact_evidence import validate_fact
    from source_fact_recall import recall_cached_source_facts
    import archive_pipeline as ap
    from archive_catalog import get_catalog
    from pdf_doc_locator import DocumentUnit
    if case_type != 'civil' or len(paths) != 1 or not Path(paths[0]).resolve().is_relative_to(data):
        raise ValueError('Only one fixed fictional input per analysis')
    digest = hashlib.sha256(Path(paths[0]).read_bytes()).hexdigest()
    initial = json.loads((ROOT / 'artifacts/civil-execution-v64/registry.json').read_text())['sha256']
    if digest == initial:
        a = original(paths, case_type, data)
        with fitz.open(paths[0]) as pdf:
            quote = pdf[12].get_text(sort=True)
        assert validate_fact('案号', TRIAL, quote, quote)
        a.fields['_provenance']['案号'] = [dict(method='visual_agent_local_evidence', value=TRIAL,
            quote=quote, source_path=paths[0], page=13)]
        a.fields = ap.normalize_fields(a.fields, case_type='civil', strict_evidence=True)
        return a
    expected = json.loads((BASE / 'registry.json').read_text())['sha256']
    contract_registry = ROOT / 'artifacts/intake-supplement-v71/registry.json'
    contract_hash = json.loads(contract_registry.read_text(encoding='utf8'))['sha256'] if contract_registry.is_file() else None
    if digest not in (expected, contract_hash) or supplied is None:
        raise ValueError('Unregistered input or missing immutable parent context')
    with fitz.open(paths[0]) as pdf:
        assert len(pdf) == 1
        cache = {(paths[0], 1): pdf[0].get_text(sort=True)}
    fields, refs, conflicts, reviews = {}, {}, [], []
    kind, title, seq = ('contract', '委托代理合同', 3) if digest == contract_hash else ('invoice', '律师费结算单', 2)
    units = [DocumentUnit(0, kind, 0, 0, title, source_path=paths[0], catalog_seq=seq)]
    stats = recall_cached_source_facts(fields, refs, conflicts, page_cache=cache,
        allowed_sources=set(cache), fact_review=reviews, local_recall_context=supplied, document_units=units)
    fields.update(_provenance=refs, _field_conflicts=conflicts, _fact_review=reviews, _source_fact_recall=stats,
                  _fixture_scope='Fixed fictional pages; real incremental recall; no model/OCR accuracy claim')
    catalog = get_catalog('civil')
    found = ap.compute_found_seqs(catalog, units, {}) | {r.seq for r in catalog if r.source == 'system'}
    return ap.ArchiveAnalysis('civil', paths[0], fields, {}, units, found,
                             ap.compute_missing_items('civil', catalog, found), source_paths=paths)


if __name__ == '__main__':
    build()
