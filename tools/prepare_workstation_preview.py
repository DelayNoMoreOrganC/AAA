"""Isolated synthetic UI fixture. Never run against workstation-data."""
import asyncio
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.runtime-tmp' / 'ui-preview-data'
os.environ['V5_DATA_DIR'] = str(DATA)
os.environ['V5_PREVIEW_ONLY'] = 'true'
os.environ['V5_DATABASE_URL'] = 'sqlite+aiosqlite:///' + (DATA / 'preview.db').as_posix()
sys.path.insert(0, str(ROOT / 'web/backend'))
sys.path.insert(0, str(ROOT))
from app.database import init_db, AsyncSessionLocal, engine
from app.models import Org, User, Case, CaseFile, ArchiveTask, Role, TaskStatus
from app.security import hash_password
from app.services.analysis_snapshot import save_snapshot, task_work_dir
from archive_pipeline import ArchiveAnalysis
from pdf_doc_locator import DocumentUnit
from sqlalchemy import select
import fitz

async def main():
    await init_db()
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(User))).scalars().first():
            return
        org = Org(name='虚构演示律所（仅测试）')
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, username='preview', hashed_password=hash_password('PreviewOnly12345'), role=Role.admin, display_name='界面验收')
        db.add(user)
        await db.flush()
        case = Case(org_id=org.id, title='虚构样例 · 甲乙借款纠纷', case_type='civil', created_by=user.id)
        db.add(case)
        await db.flush()
        relative = Path(org.id) / 'cases' / case.id / 'synthetic.pdf'
        path = DATA / 'orgs' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = fitz.open()
        pdf.new_page().insert_text((60, 80), 'FICTIONAL TEST MATERIAL - NOT A REAL CASE', fontsize=16)
        pdf.new_page().insert_text((60, 80), 'FICTIONAL TEST JUDGMENT - PREVIEW ONLY', fontsize=16)
        pdf.save(path)
        pdf.close()
        db.add(CaseFile(case_id=case.id, filename='虚构演示材料.pdf', stored_name=relative.as_posix(), doc_type='default', file_size=path.stat().st_size))
        fields = {'委托人':'演示当事人甲', '当事人':'演示当事人甲', '对方当事人':'演示当事人乙', '案由':'借款合同纠纷（虚构）', '案件类别':'民事', '法院收案号':'（2026）演示民初0001号', '承办律师':'演示律师', '结案小结':'此内容为人工构造的界面测试夹具，未经过大模型分析，不得作为真实归档材料。'}
        missing = [{'seq':3,'name':'委托代理合同'}, {'seq':4,'name':'授权委托书'}]
        task = ArchiveTask(case_id=case.id, status=TaskStatus.awaiting_review, progress=60, stage='虚构样例 · 待核对', fields=fields, catalog_status=[{'seq':7,'found':True},{'seq':14,'found':True}] + [dict(item, found=False) for item in missing])
        db.add(task)
        await db.flush()
        analysis = ArchiveAnalysis(case_type='civil', original_pdf=str(path), source_paths=[str(path)], generated_templates={}, fields=fields, doc_spans=[DocumentUnit(doc_id=0,doc_type='evidence',start_page=0,end_page=0,source_path=str(path),catalog_seq=7),DocumentUnit(doc_id=1,doc_type='judgment',start_page=1,end_page=1,source_path=str(path),catalog_seq=14)], missing_items=missing, found_seqs={7,14})
        save_snapshot(task_work_dir(org.id,case.id,task.id), analysis, base_name='虚构演示')
        await db.commit()
    await engine.dispose()

asyncio.run(main())

