"""Versioned rule provenance. Historical templates are never legal approval."""
from __future__ import annotations

RULE_VERSION = "workstation-draft-2026-10-24.1"
RULE_SOURCES = [
    {"id": "foshan-2004-user-document", "title": "佛山市律师事务所业务档案立卷归档和管理办法（用户提供文本）",
     "issuer": "佛山市司法局", "document_number": "", "url": "https://www.gdlawyers.net/dynamic/details.html?id=3395",
     "local_reference": "docs/references/foshan-2004-rules.doc", "effective_date_in_document": "2004-09-20",
     "sha256": "13c4540f863d1b63ef6301c580a7ebdbe2c48ca6ad23bcbfd52a7c21cd2a01c3",
     "verification": "user_provided_text_official_2026_guide_references_title", "current_validity_verified": False,
     "scope": "原文已读取；官网2026-02-24实习考核指引引用同名办法，但未完成全文版本、现行效力及全部业务适用核验"},
    {"id": "firm-civil-annotations-20261026", "title": "民事案卷目录（行政填写批注）",
     "issuer": "用户提供的律所内部填写要求", "document_number": "", "url": "",
     "local_reference": "docs/references/civil-catalog-annotations.doc",
     "sha256": "5de144ba96daa497ade9d560ab7af818a0d77e5147819124660bb372f0910e50",
     "verification": "user_confirmed_internal_convention", "current_validity_verified": False,
     "scope": "目录项目不变，红字为填写提示；所函随证据材料，普通受理通知随第12项。摆放位置不证明授权、送达或开庭"},
    {"id": "gd-management-guide-2022-12", "title": "律师事务所人员 业务 收费 印章 办公场所管理工作指引（2022年12月版）",
     "issuer": "广东省律师协会编写；佛山市律师协会官网公开", "document_number": "",
     "url": "https://gdlawyers.net/Upload/20230330/4b18c865e77c73cd67b3747cc044624f.pdf",
     "publication_url": "https://www.gdlawyers.net/mobile/dynamic/details.html?id=6740&type=2",
     "publication_attachment_url": "https://www.gdlawyers.net/Upload/attachment/doc/20233615617.pdf",
     "edition_date": "2022-12", "publication_date": "2023-03-06",
     "source_locator": "编写说明；第二章第六节业务档案管理，印刷页89—99（PDF第48—53页）；立卷办法摘录印刷页94—98",
     "sha256": "d44d09115a29be26002d1c10fbbdbf46e71bdc581924ccd09a1ecd14138a8bd4",
     "verification": "association_public_text_and_scope_verified", "current_validity_verified": False,
     "scope": "编写说明定位为广东律所内部管理参考；2022版引用国家两办法及广东实施律师法办法，不能据此推定2026全部条款、电子归档或每案材料必备性已核验"},
    {"id": "mofcom-index-1991-management", "title": "律师业务档案管理办法（商务部全球法规网索引）",
     "issuer": "商务部网站；内容标注来源北大法宝", "document_number": "司律通字[1991]153号",
     "url": "https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=37551",
     "verification": "public_index_status_observed", "current_validity_verified": False,
     "reported_status": "现行有效", "status_observed_on": "2026-10-23",
     "scope": "网站索引状态线索，须与正式文本核对；对象为管理办法，不等于立卷归档办法及广东补充规则的现行性结论"},
    {"id": "national-1991-153", "title": "律师业务档案立卷归档办法",
     "issuer": "司法部、国家档案局", "document_number": "司律通字〔1991〕153号",
     "url": "https://www.yuncheng.gov.cn/doc/2021/04/08/120470.shtml",
     "official_mirror": "https://www.gzns.gov.cn/zfxxgkml/gzsnsqsfj/zfwj/qt/content/post_5369652.html",
     "source_locator": "附件4.2，第三、四、十二、十三、十四、十八条",
     "verification": "official_public_text_found", "current_validity_verified": False,
     "scope": "国家层面历史公开文本；尚未完成现行效力及本地适用核验"},
    {"id": "nansha-public-lawyer-guide", "title": "公职律师事务所规范化建设指引（2008年试行版，2017年公开）",
     "issuer": "广州市公职律师事务所；南沙区政府门户公开", "document_number": "",
     "url": "https://www.gzns.gov.cn/zfxxgkml/gzsnsqsfj/zfwj/qt/content/post_5369652.html",
     "verification": "official_public_text_found", "current_validity_verified": False,
     "scope": "广州市及各区县公职律师事务所范围；仅用附录定位国家历史办法，非广东所有律所统一强制依据"},
    {"id": "moj-2021-response", "title": "司法部2021年人大建议答复（律师业务档案管理）",
     "issuer": "司法部", "document_number": "",
     "url": "https://www.moj.gov.cn/pub/sfbgw/zwxxgk/fdzdgknr/fdzdgknrjyta/202111/t20211119_441954.html",
     "verification": "official_reference_link", "current_validity_verified": False,
     "scope": "相关官方答复参考；不能单凭该答复推定全部旧模板及地方细则现行有效"},
    {"id": "gd-historical-templates", "title": "项目历史模板及人工归档成果",
     "issuer": "项目内历史参考", "document_number": "",
     "url": "", "local_reference": "docs/归档生成标准.md",
     "verification": "internal_reference_only", "current_validity_verified": False,
     "scope": "主要来自民事金融借款历史成品，不代表广东全业务统一标准"},
]
STAGES = {
    "civil": ("first_instance", "appeal", "retrial", "execution"),
    "criminal": ("investigation", "prosecution", "first_instance", "appeal", "retrial"),
    "admin": ("first_instance", "appeal", "retrial", "execution"),
    "nonlit": ("engagement", "delivery", "closed"),
    "counsel": ("service_period", "renewal", "termination"),
    "arbitration": ("arbitration", "judicial_review", "execution"),
    "consultation": ("consultation", "drafting", "closed"),
}


def get_volume_policy(case_type: str, stage=None) -> dict:
    """Historical source text plus product policy; no automatic legal finding."""
    return {
        "source_id": "national-1991-153", "source_articles": ["立卷归档办法第三条", "第四条", "第十三条", "第十四条", "管理办法第七条"],
        "verification": "historical_text_located_current_applicability_unverified",
        "case_type": case_type, "stage": stage,
        "order": "year_then_document_date" if case_type == "consultation" else "catalog_then_source_order",
        "missing_document_date": "preserve_input_order_and_request_review" if case_type == "consultation" else None,
        "filing_year": "历史第四条：跨年度业务以办结年立卷；不得根据文件上传日期自动认定",
        "volume_unit": "历史第四条：常年顾问按单位整理" if case_type == "counsel" else "历史第四条：按一案一卷、一卷一号原则整理",
        "cross_stage": "保留审级与阶段信息；历史管理办法第七条说明同案形成数卷的关联保管，不据此擅自合并不同案件或强制分卷",
        "terminated_engagement": "历史第十四条：终止委托说明或原因记录置于业务文书之后；是否适用须有事实依据",
        "automatic_cross_case_merge": False,
        "formal_ready": False,
    }


def get_rule_readiness(case_type: str, stage=None) -> dict:
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    import archive_catalog as catalog
    import original_catalog

    supported = case_type in catalog.CASE_TYPE_LABELS
    template_ready = supported and case_type in original_catalog.SOURCES
    issues = ["广东该业务及阶段的现行归档规范尚未逐条核验，当前成果只能标注为草稿"]
    if not supported:
        issues.append("该业务尚无独立归档目录模板，不能自动套用其他业务目录")
    elif not template_ready:
        issues.append("该业务尚未取得可用的原式目录模板，暂不能生成整卷；不能套用民事目录或网页重画目录")
    known_stages = list(STAGES.get(case_type, ()))
    if stage and stage not in known_stages:
        issues.append("所选办理阶段不在当前规则配置内，需核对分卷方式")
    return {
        "formal_ready": False,
        "draft_supported": template_ready,
        "catalog_rules_available": supported,
        "template_ready": template_ready,
        "issues": issues,
        "version": RULE_VERSION,
        "case_type": case_type,
        "stage": stage,
        "known_stages": known_stages,
        "volume_policy": get_volume_policy(case_type, stage),
        "sources": [dict(item) for item in RULE_SOURCES],
        "reviewed_at": None,
        "reviewed_by": None,
    }


def get_catalog_rules(case_type: str, stage=None) -> list[dict]:
    """Separate software outputs from legal material obligations.

    An item being present in a historical catalog is insufficient evidence of
    legal necessity. Unknown requirements remain unknown, rather than being
    labelled optional or mandatory to make a checklist look complete.
    """
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    import archive_catalog as catalog

    if case_type not in catalog.CASE_TYPE_LABELS:
        return []
    result = []
    for item in catalog.get_catalog(case_type):
        requirement, scope, condition, applicable = "unknown", "legal_material", "", None
        if item.source == "system":
            requirement, scope, applicable = "required", "product_output", True
        elif item.seq == 15 and case_type in ("civil", "admin", "criminal", "arbitration"):
            requirement = "conditional"
            condition = "judicial_review_or_execution" if case_type == "arbitration" else "execution" if case_type in ("civil", "admin") else "appeal"
            applicable = (stage in ("judicial_review", "execution") if case_type == "arbitration" else stage == condition) if stage else None
        new_business = case_type in ("arbitration", "consultation") and scope == "legal_material"
        result.append({
            "seq": item.seq, "name": item.name, "requirement": requirement,
            "scope": scope, "condition": condition, "applicable": applicable,
            "verification": "unverified", "source_id": "national-1991-153" if new_business else "gd-historical-templates",
            "source_articles": ["第十二条第二项", "第十三条"] if case_type == "arbitration" and new_business else ["第十三条"] if new_business else [],
            "adaptation": "按仲裁业务调整目录名称；现行适用及逐项必备性待核验" if case_type == "arbitration" and new_business else "按年度、业务日期保留材料；缺日期提示人工核对" if new_business else "",
            "legal_requirement_verified": False,
            "note": "产品默认成果，非法律必备结论" if scope == "product_output" else "目录存在不等于该材料在每案必备",
        })
    return result


def _material_requirement(doc_types, stage):
    """Material applicability is independent of the slot it happens to occupy.

    Historical ordering is not evidence of a present-day legal obligation.
    No material becomes optional merely to reduce a checklist's size.
    """
    if set(doc_types) == {"execution"}:
        return "conditional", "本案涉及执行程序时核对；不以目录中有其他法院文书代替", None if not stage else stage == "execution"
    if set(doc_types) == {"appeal"}:
        return "conditional", "本案涉及上诉程序时核对", None if not stage else stage == "appeal"
    return "unknown", "是否须提供应结合本案委托方式、办理事项和适用规则核对", None


def material_completeness(analysis, stage=None, source_manifest=None):
    """Report source document presence without certifying execution/completeness.

    Only DocumentUnits of the expected kind with current in-case page anchors
    count as recognized. Catalog occupancy and generated system forms never do.
    No file contents are read; the immutable manifest supplies the source scope.
    """
    import math
    import os
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    import archive_catalog as catalog

    def path_key(value):
        return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""

    sources = {path_key(row.get("path")): row for row in source_manifest or [] if isinstance(row, dict) and path_key(row.get("path"))}
    uncertain_ids = {str(row.get("doc_id")) for row in getattr(analysis, "low_confidence_items", []) or [] if isinstance(row, dict)}
    units = list(getattr(analysis, "doc_spans", []) or [])

    def anchor(unit):
        source = sources.get(path_key(getattr(unit, "source_path", None)))
        start, end = getattr(unit, "start_page", None), getattr(unit, "end_page", None)
        if not (source and source.get("file_id") is not None and type(source.get("pages")) is int
                and type(start) is int and type(end) is int and 0 <= start <= end < source["pages"]):
            return None
        return {"file_id": source["file_id"], "filename": source.get("filename", "来源材料"),
                "page": start + 1, "page_start": start + 1, "page_end": end + 1,
                "catalog_seq": getattr(unit, "manual_catalog_seq", None) if getattr(unit, "manual_catalog_seq", None) is not None else getattr(unit, "catalog_seq", None),
                "doc_type": getattr(unit, "doc_type", "unknown")}

    def confident(unit):
        if str(getattr(unit, "doc_id", None)) in uncertain_ids:
            return False
        confidence = getattr(unit, "confidence", None)
        return (type(confidence) in (int, float) and math.isfinite(confidence) and confidence >= .8
                or getattr(unit, "manual_catalog_seq", None) is not None)

    checks = []
    if analysis.case_type not in catalog.CASE_TYPE_LABELS:
        return {"version": RULE_VERSION, "formal_ready": False, "checks": [], "unclassified_sources": [], "notice": "该业务尚无独立材料规则"}
    for item in catalog.get_catalog(analysis.case_type):
        if item.source == "system":
            # Product outputs are deliberately not converted to signed source documents.
            if item.templates and item.templates[0] != "档案卷宗":
                from source_form_policy import source_units_for_item
                source_forms=source_units_for_item(item,units)
                preserved=[anchor(u) for u in source_forms if anchor(u)]
                checks.append({"id": "execution:" + item.templates[0], "seq": item.seq, "name": item.name,
                    "check_kind": "execution_review", "requirement": "unknown", "applicable": None,
                    "status": "source_present_execution_unverified" if preserved else "unverified",
                    "material_found": bool(preserved), "sources": preserved, "related_sources": preserved,
                    "reason_codes": ["source_form_not_execution_evidence" if preserved else "generated_form_not_execution_evidence"],
                    "message": "已保留来源表单；不据表单存在认定已审批、签署或实际送达" if preserved else "系统填写表格不证明已审批、签署或送达；如本案需留存办理凭证，应另附原件核对",
                    "legal_requirement_verified": False, "source_id": "gd-historical-templates", "rule_version": RULE_VERSION})
                if item.templates[0]=='质量监督卡':
                    from source_form_policy import QUALITY_COMPONENTS
                    present={u.doc_type for u in source_forms if anchor(u)}
                    checks[-1]['components']={kind:{'source_present':kind in present,
                        'signed_or_delivered':None} for kind in QUALITY_COMPONENTS}
                    if present and len(present)<2:
                        checks[-1].update(status='source_partial_execution_unverified',material_found=False,
                            message='已保留提供的组件，另一组件按原模板补填；不据此认定已签署或告知')
            continue
        expected = list(item.doc_types or ())
        # Internal placement conventions never substitute for the primary document.
        expected = [kind for kind in expected if kind not in ("firm_letter", "acceptance_notice")]
        if "contract" in expected:
            expected = [kind for kind in expected if kind != "agency_notice"]
        if not expected and item.manual_key:
            expected = [catalog.MANUAL_KEY_DOC_TYPES.get(item.manual_key) or item.manual_key]
        requirement, condition, applicable = _material_requirement(expected, stage)
        matching = [unit for unit in units if getattr(unit, "doc_type", None) in expected]
        located = [anchor(unit) for unit in matching if confident(unit) and anchor(unit)]
        uncertain = [anchor(unit) for unit in matching if not confident(unit) and anchor(unit)]
        related = [anchor(unit) for unit in units if getattr(unit, "doc_type", None) == "agency_notice" and "contract" in expected and anchor(unit)]
        status = "recognized" if located else "unverified" if matching else "missing"
        codes = []
        if "contract" in expected and related:
            codes.append("agency_notice_not_contract")
        if matching and not located:
            codes.append("classification_or_source_unverified")
        if not matching:
            codes.append("expected_document_not_identified")
        if located:
            codes.append("document_type_not_execution_or_completeness_proof")
        message = ("已识别相应文书；未核验签署、生效、送达或全部附件是否齐备" if located else
                   "发现相似材料，但文书类别或来源页段尚未核实" if matching else "本次材料中尚未识别到该类文书")
        if related:
            message += "；委托代理通知书不能证明委托合同已提供或签署"
        if "evidence" in expected:
            message += "；归入证据目录或识别到证据清单不表示所有证据原件齐备"
        checks.append({"id": "material:" + "+".join(expected), "seq": item.seq,
            "name": "委托合同" if "contract" in expected else item.name,
            "check_kind": "source_material", "expected_doc_types": expected,
            "requirement": requirement, "condition": condition, "applicable": applicable,
            "status": status, "material_found": bool(located), "sources": located,
            "related_sources": related + uncertain, "reason_codes": codes, "message": message,
            "legal_requirement_verified": False, "source_id": "gd-historical-templates", "rule_version": RULE_VERSION})
    unknown = [anchor(unit) for unit in units if getattr(unit, "doc_type", None) in (None, "unknown", "other", "default") and anchor(unit)]
    # This report intentionally never turns machine classification into final acceptance.
    return {"version": RULE_VERSION, "formal_ready": False, "checks": checks,
            "unclassified_sources": unknown, "notice": "目录归类不等于材料齐备。材料适用性及现行要求待核验；草稿可导出，不能据此确认正式归档完成。"}


def catalog_material_status(analysis, stage=None, source_manifest=None):
    rules = {item["seq"]: item for item in get_catalog_rules(analysis.case_type, stage)}
    report = material_completeness(analysis, stage, source_manifest)
    missing = {row.get("seq"): row for row in getattr(analysis, "missing_items", []) or []}
    result = []
    # Retain the existing workflow row set: introducing every rule row here
    # would incorrectly demand new skip acknowledgments on historical tasks.
    for seq in sorted(set(getattr(analysis, "found_seqs", []) or []) | set(missing)):
        row = {**rules.get(seq, {}), "seq": seq, "found": seq in analysis.found_seqs,
               "material_checks": [check for check in report["checks"] if check["seq"] == seq]}
        if seq in missing:
            row["name"] = missing[seq].get("name", row.get("name", ""))
        row["material_status_version"] = report["version"]
        # Keep unknown units visible at their sorting location, without treating
        # a fallback evidence slot as a confirmed evidence document.
        row["unclassified_sources"] = [source for source in report["unclassified_sources"] if source.get("catalog_seq") == seq]
        result.append(row)
    if result:
        represented = {row["seq"] for row in result}
        # Material checks outside historical displayed rows remain visible in
        # the one consolidated report without creating new workflow skip rows.
        result[0]["additional_material_checks"] = [check for check in report["checks"] if check["seq"] not in represented]
        result[0]["unclassified_sources"].extend(source for source in report["unclassified_sources"] if source.get("catalog_seq") not in represented)
    return result


def unresolved_material_requirements(catalog_status):
    """Future verified material rules must guard independently of catalog.found."""
    return [check for row in catalog_status or [] for check in row.get("material_checks", []) + row.get("additional_material_checks", [])
            if check.get("legal_requirement_verified") is True
            and (check.get("requirement") == "required" or
                 check.get("requirement") == "conditional" and check.get("applicable") is True)
            and check.get("status") != "verified"]
