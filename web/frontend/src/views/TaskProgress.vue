<template>
  <div v-loading="loading" class="task-workspace">
    <div class="task-heading"><div><router-link class="back-link" to="/cases">← 新归档</router-link><h1>{{ caseInfo?.title || '正在打开案件' }}</h1><p v-if="task">{{ taskProcessingLabel(task) }}</p></div><el-button data-testid="archive-tools" text @click="toolsOpen=true">管理档案</el-button></div>
    <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" class="page-alert"><el-button text @click="refresh">重新连接</el-button></el-alert>
    <el-alert v-if="historical" title="材料已更新，当前显示历史成果" type="warning" :closable="false" class="page-alert" />
    <template v-if="task">
      <ArchiveBrief :summary="summary" :activity="processing&&!finishing?visualProgress:null" />
      <section v-if="cloudConsentRequired && task.can_resume" ref="consentSection" class="resume-cloud-consent" data-testid="supplement-consent"><p v-if="task.source_changed" class="muted" role="status">补件已保存在工作站，请确认云端授权。</p><CloudProcessingConsent v-model="cloudApproved" :mode="resumeMode" :disabled="locked" /></section>
      <section v-if="task.status==='failed' || task.error || operationError" ref="errorSection" class="error-card" data-testid="archive-operation-error"><p class="error-message">{{ operationError || task.error }}</p><router-link v-if="auth.isAdmin && task.status==='failed'" to="/settings">检查工作站设置</router-link></section>
      <UploadRecoveryPanel ref="uploadPanel" :state="uploadState" :disabled="locked||processing" dismiss-test-id="task-dismiss-upload" retry-test-id="task-retry-uploads" @reload="uploadQueue.reload()" @remove="dismissUpload" @recover="recoverUploads" @retry="retryUploads" />
      <div v-if="task.has_archive" class="result-note" data-testid="archive-result"><span>{{ task.delivery_kind==='draft'||task.status!=='done'?'草稿 · 未正式归档':'已保存成果' }}</span><div class="result-actions"><el-button text @click="download('archive')">查看整卷 PDF</el-button><el-button v-if="confirmationAction.visible" data-testid="archive-confirm-action" plain :disabled="confirmationAction.disabled" :loading="assembling" @click="onAssemble">{{ confirmationAction.label }}</el-button></div><p v-if="hasUnsaved()" class="muted">有未保存的修改</p></div>
      <ArchiveActionBar :action="primaryAction" :busy="saving||assembling||draftGenerating||resuming||uploading" @action="performPrimaryAction" />
      <p v-if="uploading" data-testid="upload-in-progress" class="muted" role="status">{{ uploadingName }}</p>
      <SupplementSummary ref="supplementSummary" v-if="reviewable && !historical" :items="task.catalog_status||[]" :has-archive="task.has_archive===true" :issue-count="reviewSections.attention.filter(item=>item.kind==='issue'&&!item.resolved).length" :disabled="locked||processing" @upload="fileInput?.click()" @review="openDecisions" @source="showAssistantSource" />
      <section v-if="reviewable && !historical && pendingForms.length" class="form-followups" data-testid="pending-form-fields" aria-label="表格待补充"><span>表格待补充</span><el-button v-for="item in pendingForms" :key="item.field" :data-testid="'fill-'+item.field" text :disabled="locked||processing" @click="openPendingForm(item)">{{ item.label }} →</el-button></section>
      
      <ArchiveCompanion :key="taskId+':'+String(auth.user?.org_id||'')+':'+String(auth.user?.id||'')" :presentation="companionPresentation(task,{error:!!loadError||!!operationError,historical,consent:cloudConsentRequired,unresolved:reviewSections.attentionCount,materials:reviewSections.materialCount})" :suppressed="toolsOpen||decisionsOpen||catalogOpen||sourcesOpen||reviewOpen||classificationOpen" :actions="[{kind:'sources',label:'查看原文'},{kind:'catalog',label:'文书归属',disabled:!reviewable},{kind:'fields',label:'填写表格',disabled:!reviewable},{kind:'issues',label:'待核对',disabled:!reviewable}]" @action="kind=>kind==='issues'?openDecisions():openAssistantAction(kind)">
      <ArchiveAssistant v-if="canUseTaskAssistant(task)" :key="taskId" :task-id="taskId" :account-scope="String(auth.user?.org_id||'')+':'+String(auth.user?.id||'')" :draft-read-only="historical" @draft-dirty="value=>assistantDraftDirty=value" :mode="task.execution_profile?.processing_mode||'local'" :busy="processing" :revision="task.revision" :source-version="task.source_version" :write-disabled="locked||historical||processing" :recover-disabled="locked||processing" :before-apply="beforeAssistantProposal" :before-recover="beforeAssistantRecovery" @busy="value=>proposalSaving=value" @applied="applyAssistantProposal" @refresh="refresh" @source="showAssistantSource" @field="showEvidence" @action="openAssistantAction" />
      </ArchiveCompanion>
      
    </template>
    <el-drawer v-model="toolsOpen" title="管理档案" size="min(520px, 94vw)">
      <button class="review-link" @click="sourcesOpen=true"><span>原始材料<small>{{ caseInfo?.files?.length || 0 }} 份</small></span>→</button>
      <button class="review-link" :disabled="!reviewable" @click="catalogOpen=true"><span>归档目录</span>→</button>
      <button class="review-link" :disabled="!reviewable" @click="reviewOpen=true"><span>表格<small>{{ templateNames.length }} 份</small></span>→</button>
      <button class="review-link" data-testid="attention-review-entry" :disabled="!reviewable" @click="openDecisions"><span>疑点核对<small>{{ reviewSections.attentionCount }} 项</small></span>→</button>
      <section v-if="formDrafts.length" class="draft-summary"><p v-for="item in formDrafts" :key="item.field">{{ item.field }} · {{ item.label }}</p><el-button text @click="reviewOpen=true">查看表格</el-button></section>
      <div class="button-row"><el-button :disabled="locked||processing||historical" @click="fileInput?.click()">补充文件</el-button><el-button :disabled="locked||processing||historical" @click="folderInput?.click()">补充文件夹</el-button><el-button v-if="reviewable" :disabled="locked||historical||processing" @click="saveDraft()">保存当前修改</el-button></div><p class="muted">{{ lastSaveMessage }}</p>
      <el-button v-if="task?.has_archive && task.delivery_kind==='draft'" :disabled="locked||historical||processing||!task.can_assemble" :loading="draftGenerating" @click="generateDraft">更新草稿</el-button>
      <button v-if="materialChecklistCount(task)" class="review-link" data-testid="material-checklist-entry" @click="openMaterialChecklist"><span>材料清单<small>{{materialChecklistCount(task)}} 项待核验</small></span>→</button>
      <details class="small-details"><summary>正式归档确认</summary><p>{{ task?.has_archive?'档案草稿可随时下载。':'档案草稿生成后可下载。' }}正式确认前，仍需补齐必要材料并核对所有待处理事项。</p><p v-if="reviewSections.materialCount">另有 {{reviewSections.materialCount}} 项目录空位尚未记录适用性或缺失说明。<el-button data-testid="material-review-entry" text :disabled="!reviewable" @click="openMaterialDecisions">目录空位说明 · {{reviewSections.materialCount}} 项待记录</el-button></p><p v-if="!task?.formal_ready">广东规则或本案归档条件尚未完全核验，不能标记为正式归档完成。</p><el-button :disabled="locked||historical||processing||documentDraftDirty||unresolvedCount>0||!task?.can_assemble" :loading="assembling" @click="onAssemble">最终确认并生成</el-button></details>
      <details v-if="task?.has_archive" class="small-details"><summary>成果清单与保存位置</summary><p>{{ task.fields?._saved_to || '成果保存在工作站本案目录中' }}</p><p v-for="(artifact,index) in task.artifacts || []" :key="index">{{ artifact.relative_path||artifact.key||artifact.name||artifact.filename||artifact.label||artifact.kind }}</p><el-button text @click="download('zip')">下载已保存成果</el-button></details>
      <details class="small-details"><summary>规则与任务记录</summary><p>{{ task?.formal_ready?'本次规则检查通过':'广东规则及适用性待核验' }}</p><p v-for="(item,index) in task?.rule_readiness?.issues || []" :key="index">{{ item }}</p><p>任务 {{ task?.id }} · 修订 {{ task?.revision }}</p><p>{{ phaseDescription(task) }}</p><p v-if="agentFragments">已记录 {{ agentFragments.done }} / {{ agentFragments.total }} 个核对片段；片段数不等于页数。</p><p>创建于 {{ fmtDate(task?.created_at) }}</p><p v-if="task?.parent_task_id">基于任务 {{ task.parent_task_id }} 继续</p></details>
      <router-link class="management-link" :to="'/cases/'+caseId">案件材料与历史版本 →</router-link>
    </el-drawer>
    <el-drawer v-model="decisionsOpen" title="按需核对" size="min(650px, 94vw)" :destroy-on-close="false">
      <p class="muted">{{materialReview?'目录空位不等于本案必须补交。定稿前须核实适用性或记录缺失说明。':'确认后自动进入下一项；切换会保留输入。'}}</p><el-button v-if="reviewSections.materials.length" data-testid="toggle-review-section" text @click="toggleReviewSection">{{materialReview?'返回疑点核对':'查看目录空位（'+reviewSections.materialCount+'）'}}</el-button>
      <el-select v-if="decisionQueue.length" v-model="activeDecisionKey" :disabled="locked||processing" aria-label="选择核对事项" style="width:100%;margin-bottom:16px"><el-option v-for="item in decisionQueue" :key="item.key" :value="item.key" :label="(item.resolved?'已记录 · ':materialReview?'待核验 · ':'待核对 · ')+item.title" /></el-select>
      <DecisionFocus v-if="activeDecision" :item="activeDecision" :remaining="decisionQueue.filter(item=>!item.resolved).length" :breakdown="decisionBreakdown" :position="decisionPosition" :total="decisionQueue.length" :disabled="locked||processing" @previous="moveDecision(-1)" @next="moveDecision(1)">
        <div v-if="activeDecision.reasons.length>1" class="conflict-evidence" data-testid="decision-related-reasons"><strong>{{ activeDecision.members.length }} 项关联依据</strong><p v-for="reason in activeDecision.reasons" :key="reason.id">{{ reason.message }}<span v-if="issueDecisions[reason.id]?.action==='acknowledged'"> · {{ reason.kind==='field_conflict'?'已记录核对说明':'已核对' }}</span></p></div>
        <div v-if="activeOtherSources.length" class="button-row"><el-button v-for="source in activeOtherSources" :key="source.file_id+':'+source.page" text data-testid="decision-source" @click="showDecisionSource(source)">{{ source.filename }} · 第 {{ source.page }} 页</el-button></div>
        <template v-if="activeDecision.kind==='missing'">
          <div v-for="item in activeDecision.members" :key="item.seq"><p class="muted">{{ item.name }} · {{ materialRequirementLabel(item) }}。尚未在已导入材料中识别到此项。</p><el-button :disabled="locked||processing||historical" @click="fileInput?.click()">补充这项材料</el-button>
          <template v-if="!isRequiredMissing(item)"><el-select v-model="decisions[item.seq].action" :disabled="locked||processing||historical" style="width:100%;margin-top:16px" aria-label="本项材料处理方式"><el-option label="等待补充" value="pending" /><el-option label="本案不适用" value="not_applicable" /><el-option label="确实缺失，保留说明" value="skip" /></el-select><el-input v-if="decisions[item.seq].action!=='pending'" v-model="decisions[item.seq].reason" :disabled="locked||processing||historical" type="textarea" :rows="3" placeholder="填写本案依据或缺失原因" maxlength="500" style="margin-top:12px" /><el-button :disabled="locked||processing||historical" style="margin-top:12px" @click="saveDecision(false)">保存说明</el-button></template>
          <p v-else class="muted">已核验的必要材料需补齐后才可正式归档。草稿可先下载。</p></div>
        </template>
        <template v-else>
          <div class="button-row"><el-button v-if="activeDecision.source.detail?.field" text @click="showEvidence(activeDecision.source.detail.field)">查看字段依据</el-button><el-button v-if="activeDecision.members.some(item=>item.kind==='classification')" text data-testid="decision-classification" @click="showDocumentClassification(activeDecision.members.find(item=>item.kind==='classification'))">核对这段文书</el-button><el-button v-if="activeDecision.field||activeDecision.source.detail?.field||activeDecision.source.kind==='empty_fields'" data-testid="decision-edit-field" text @click="openDecisionField">打开对应字段</el-button></div><p v-if="fieldTargetError" class="error-message" role="alert">{{ fieldTargetError }}</p>
          <div v-if="activeDecision.source.detail && 'saved' in activeDecision.source.detail" class="conflict-evidence"><p>当前保留：{{ activeDecision.source.detail.saved || '空白' }}</p><p>补件识别：{{ activeDecision.source.detail.new || '空白' }}</p></div>
          <section v-if="activeCandidateChoices.length && !historical" class="field-candidates" data-testid="field-candidates" aria-label="选择字段内容"><p>材料记载不同，请选择本案适用的内容。</p><div v-for="choice in activeCandidateChoices" :key="choice.selected_value" class="conflict-evidence"><strong>{{ choice.selected_value }}</strong><div class="button-row"><el-button v-for="source in choice.sources" :key="source.file_id+':'+source.page" text @click="showDecisionSource(source)">{{ source.filename }} · 第 {{ source.page }} 页</el-button><el-button :disabled="locked||processing||fieldChoiceState.needsRefresh||fieldChoiceAccountChanged" :loading="fieldChoiceBusy" :data-testid="'choose-field-'+choice.selected_value" @click="acceptCurrentField(choice.selected_value)">采用 {{ choice.selected_value }}</el-button></div></div><p class="muted">选择后保留其他依据；更新草稿后下载。</p></section>
          <section v-if="activeFieldChoice && !historical" class="field-choice" data-testid="field-choice"><p>{{ activeFieldChoice.field }} · 当前内容</p><p class="field-current-value" data-testid="field-current-value">{{ activeFieldChoice.current_value }}</p><el-button data-testid="accept-current-field" :loading="fieldChoiceBusy" :disabled="locked||processing||fieldChoiceState.needsRefresh||fieldChoiceAccountChanged" @click="acceptCurrentField">{{ fieldChoiceState.retryable?'重试确认（原请求）':'确认使用此内容' }}</el-button><p class="muted">仅确认此字段；原有不同依据继续留存。成果需更新草稿后下载。</p></section>
          <p v-else-if="activeHasFieldConflict && activeDecision.members.filter(item=>item.kind==='field_conflict').every(item=>item.detail?.fact_resolved===true)" class="muted" data-testid="field-choice-resolved">已确认使用当前内容，原有依据仍保留。</p>
          <p v-else-if="activeHasFieldConflict && !activeCandidateChoices.length" class="muted">此字段仍需核定。可打开对应字段查看或修改；保存核对说明不会解决事实冲突。</p>
          <div v-if="activeHasFieldConflict && (fieldChoiceError||fieldChoiceAccountChanged)" class="error-message" role="alert" data-testid="field-choice-error"><p>{{ fieldChoiceError||'登录账号已变化，请刷新后重新核对当前字段。' }}</p><el-button v-if="fieldChoiceState.error||fieldChoiceAccountChanged" text data-testid="refresh-field-decision" :disabled="locked||processing" @click="refreshFieldChoice">刷新并重新核对</el-button></div>
          <p v-if="activeDecision.source.kind==='empty_fields'" class="muted">请先对照原件补充系统表中的案件信息，再保存核对说明。</p>
          <div class="button-row"><el-button v-if="!activePendingFieldConflict && !activeDecision.resolved && !activeDecision.members.some(item=>item.kind==='empty_fields')" data-testid="acknowledge-decision" :disabled="locked||processing||historical" @click="saveDecision(true)">{{ activeDecision.members.length>1?'已核对本组 '+activeDecision.members.length+' 项，无需修改':'已核对，无需修改' }}</el-button><el-button text @click="showDecisionEdit=!showDecisionEdit">{{ showDecisionEdit?'收起说明':'填写说明或修改' }}</el-button></div>
          <div v-show="showDecisionEdit"><el-input v-model="issueDecisions[activeDecision.source.id].reason" data-testid="issue-review-reason" :disabled="locked||processing||historical" placeholder="对照原文后的核对说明" type="textarea" :rows="3" maxlength="500" style="margin-top:16px" /><el-button :disabled="locked||processing||historical||!issueDecisions[activeDecision.source.id].reason.trim()" style="margin-top:12px" @click="saveDecision(false)">{{ activePendingFieldConflict?'保存说明（不解决字段冲突）':activeDecision.members.length>1?'保存本组核对说明':'保存这项核对' }}</el-button></div>
        </template>
      </DecisionFocus>
      <p v-else class="muted">{{materialReview?'本组没有待处理的目录缺项。':'当前没有待处理的识别疑问或必要补件。'}}可通过上方入口查看其他清单和已保存记录。</p>
      <details v-if="advisoryIssues.length" class="advisory-details"><summary>{{ advisoryIssues.length }} 条非阻断整理提示</summary><div v-for="issue in advisoryIssues" :key="issue.id" class="advisory-row"><strong>{{ issue.message }}</strong><el-button v-if="issue.detail?.field" text @click="showEvidence(issue.detail.field)">查看依据</el-button><el-button v-for="(source,index) in issue.detail?.pages||[]" :key="index" text @click="showDecisionSource(source)">{{ source.filename||'来源材料' }} · 第 {{ source.page }} 页</el-button></div></details>
    </el-drawer>
    <input ref="fileInput" data-testid="task-supplement-files" type="file" multiple :accept="capabilities.supported_extensions.join(',')" hidden @change="onFilesSelected" />
    <input ref="folderInput" type="file" multiple webkitdirectory hidden @change="onFilesSelected" />

    <el-dialog v-model="classificationOpen" title="核对材料分类" width="500px" :close-on-click-modal="!classifying" :show-close="!classifying">
      <p>{{ classificationFile?.filename }}</p><p class="muted">调整对整份文件生效，随后会重新整理目录。若这份文件含多种文书，请保留“综合文档 / 待识别”。</p>
      <el-select v-model="classificationType" :disabled="classifying" style="width:100%" placeholder="选择这份材料的文书类型"><el-option v-for="item in docTypes" :key="item.value" :value="item.value" :label="item.label" /></el-select>
      <template #footer><el-button :disabled="classifying" @click="classificationOpen=false">返回核对</el-button><el-button type="primary" :loading="classifying" :disabled="!classificationType || classificationType===classificationFile?.doc_type" @click="applyClassification">按此分类重新整理</el-button></template>
    </el-dialog>

    <el-drawer v-model="catalogOpen" @closed="classificationDecisionKey=null" title="归档目录" size="min(800px, 92vw)" @opened="revealPendingDocument"><p class="muted">这里显示材料归入的位置，不代表相应文书已齐备、签署或送达。缺件在主页面集中列出。</p><el-table :data="task?.catalog_status || []"><el-table-column prop="seq" label="序号" width="70" /><el-table-column prop="name" label="目录项" /><el-table-column label="目录归入情况" width="140"><template #default="{row}"><el-tag :type="row.found?'info':'warning'" effect="plain">{{ row.found?'已有材料归入':'暂空' }}</el-tag></template></el-table-column></el-table>
      <DocumentClassificationReview v-if="task" ref="documentReview" :key="taskId" :task-id="taskId" :revision="task.revision" :disabled="saving||templateSaving||assembling||draftGenerating||proposalSaving||fieldChoiceBusy||resuming||uploading||classifying||processing||historical" :unsaved="hasUnsavedReview()" :before-write="beforeDocumentClassification" @source="showAssistantSource" @saved="applyDocumentClassification" @busy="value=>documentSaving=value" @dirty="value=>documentDraftDirty=value" @save-review="saveDraft()" />
    </el-drawer>

    <el-drawer v-model="sourcesOpen" title="案件原文与字段依据" size="min(960px, 94vw)" @open="loadEvidence" @closed="clearSource">
      <section v-loading="evidenceLoading" class="evidence-panel"><h3 class="section-title">字段来自哪里</h3><el-select v-if="Object.keys(evidence).length" v-model="evidenceField" placeholder="选择字段，查看识别依据" filterable style="width:100%"><el-option v-if="evidenceField && !evidence[evidenceField]" :label="evidenceField" :value="evidenceField" /><el-option v-for="field in Object.keys(evidence)" :key="field" :label="field" :value="field" /></el-select><p v-else class="muted">{{ evidenceError || '本任务尚无可用的字段页码依据，可以在下方打开原件核验。' }}</p><p v-if="evidenceField && !evidenceLoading && !evidence[evidenceField]?.length" class="muted" data-testid="no-current-field-evidence">此字段尚无已采用的依据，请对照下方原页核对。</p><div v-for="(entry,index) in evidencePageCards(evidence[evidenceField])" :key="index" class="evidence-entry" data-testid="evidence-page-card"><template v-if="entry.method==='human'"><p>人工填写 · {{ fmtDate(entry.edited_at) }}</p><strong>{{ entry.value }}</strong><p class="muted">人工修改的值没有自动定位依据；下方旧摘录仅供历史参考。</p></template><template v-else><p>{{ entry.historical?'历史识别依据 · ':'' }}{{ entry.filename }}<span v-if="entry.page"> · 第 {{ entry.page }} 页</span></p><p v-if="entry.historical" class="muted">该摘录仅供历史参考，不能作为当前字段的有效依据。</p><blockquote v-for="(quote,quoteIndex) in entry.quotes" :key="quoteIndex">{{ quote }}</blockquote><el-button v-if="canLocateEvidence(entry)" size="small" @click="openEvidence(entry)">打开原文页</el-button></template></div></section>
      <h3 class="section-title">{{ historical?'当前案件的材料':'全部原件' }}</h3>
      <p class="muted">{{ historical?'以下是当前案件材料，可能包含历史成果未纳入的后续补件。':'原始材料按导入时的内容保留。' }}点击查看 PDF 或图片；其他格式可下载原件。</p>
      <div class="source-file-list"><button v-for="file in caseInfo?.files || []" :key="file.id" @click="openSource(file)"><el-icon><Document /></el-icon>{{ file.filename }}</button></div>
      <div ref="sourcePreview" data-testid="source-preview" v-loading="sourceLoading"><p v-if="sourceName" class="muted">{{ sourceName }}</p><iframe v-if="sourceUrl && sourceType==='pdf'" :src="sourceUrl" class="source-preview" title="案件原文预览"></iframe><img v-if="sourceUrl && sourceType==='image'" :src="sourceUrl" class="source-image" alt="案件原文" @load="revealSourcePreview" /></div>
      <p v-if="!caseInfo?.files?.length" class="muted">尚未读取到案件原文，请返回案件材料页重试。</p>
    </el-drawer>

    <el-drawer v-model="reviewOpen" title="系统表核对" size="min(1120px, 94vw)" :destroy-on-close="false" :close-on-click-modal="false" @closed="clearReviewTarget">
      <p class="muted">预览为原始模板填写后的 PDF。按需展开填写内容；切换表格保留未保存修改。</p>
      <el-alert v-if="historical" title="历史任务仅供查看，请到最新任务修改。" type="info" :closable="false" />
      <el-tabs v-model="previewTab"><el-tab-pane v-for="name in templateNames" :key="name" :label="name" :name="name"><div :inert="locked"><div v-if="originalFormSources(name).length" data-testid="original-source-form"><p>{{ originalFormMessage(name) }}</p><el-button v-for="source in originalFormSources(name)" :key="source.file_id+':'+source.page" text @click="showDecisionSource(source)">查看原表 · 第 {{ source.page }}—{{ source.page_end }} 页</el-button></div><template v-else><div v-if="name==='质量监督卡' && qualitySources().length" data-testid="original-quality-part"><p>已保留委托人须知，仅补填质量监督卡。</p><el-button v-for="source in qualitySources()" :key="source.file_id+':'+source.page" text @click="showDecisionSource(source)">查看原件 · 第 {{ source.page }}—{{ source.page_end }} 页</el-button></div><PreviewFieldEditor :key="name + editorVersion" :ref="el=>setEditorRef(name,el)" :task-id="taskId" :template-name="name" :focus-field="previewTab===name?reviewFocus:''" :revision="task?.revision" :source-version="task?.source_version" :read-only="historical||processing" :disabled="locked" :active="reviewOpen&&previewTab===name" @busy="value=>templateBusy[name]=value" @saved="applyTemplateFields" @source="showEvidence" /></template></div></el-tab-pane></el-tabs>
      <template #footer><span class="muted" style="margin-right:18px">{{ lastSaveMessage }}</span><el-button :disabled="saving" @click="reviewOpen=false;clearReviewTarget()">{{ returnDecisionKey?'返回当前核对项':'返回档案草稿' }}</el-button><el-button v-if="!historical" data-testid="save-template-fields" type="primary" :loading="saving" :disabled="locked" @click="saveDraft()">保存表格</el-button></template>
    </el-drawer>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { Document } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'

import PreviewFieldEditor from '../components/PreviewFieldEditor.vue'
import ArchiveAssistant from '../components/ArchiveAssistant.vue'
import ArchiveCompanion from '../components/ArchiveCompanion.vue'
import UploadRecoveryPanel from '../components/UploadRecoveryPanel.vue'
import {useUploadRecovery} from '../domain/useUploadRecovery.js'
import DocumentClassificationReview from '../components/DocumentClassificationReview.vue'
import CloudProcessingConsent from '../components/CloudProcessingConsent.vue'
import ArchiveBrief from '../components/ArchiveBrief.vue'
import ArchiveActionBar from '../components/ArchiveActionBar.vue'
import DecisionFocus from '../components/DecisionFocus.vue'
import SupplementSummary from '../components/SupplementSummary.vue'
import { buildDecisionQueue,selectDecision,stepDecision,decisionAfterSave,formDraftSummary,reviewQueueSections,pendingFormEntries,materialChecklistCount } from '../domain/decisionQueue.js'
import { currentFieldDecision,candidateFieldDecisions,hasFieldConflict,createFieldDecision } from '../domain/fieldDecision.js'

import { companionPresentation,archiveSummary,nextArchiveAction,archiveConfirmationAction,materialRequirementLabel,canUseTaskAssistant,parseVisualStageProgress } from '../domain/taskExperience.js'
import { taskProcessingLabel,materialConsentKey,resumeProcessingMode,taskNeedsCloudConsent } from '../domain/processingPrivacy.js'
import { useCloudConsent } from '../domain/useCloudConsent'
import { saveReviewEditors, unresolvedMissing, isRequiredMissing } from '../domain/review.js'
import { unresolvedIssues, isHistoricalTask, phaseDescription, reconcileDecisions, formatShanghaiTime, canLocateEvidence, parseAgentFragmentProgress, evidencePageCards } from '../domain/workflow.js'
const route=useRoute(),router=useRouter(),auth=useAuthStore(),caseId=String(route.params.id),taskId=String(route.params.taskId)
const task=ref<any>(null),caseInfo=ref<any>(null),loading=ref(true),loadError=ref(''),operationError=ref('')
const reviewOpen=ref(false),catalogOpen=ref(false),sourcesOpen=ref(false),previewTab=ref('立案审批表')
const reviewFocus=ref(''),fieldTargetError=ref(''),returnDecisionKey=ref<string|null>(null)
const repairingForm=ref(false)
const errorSection=ref<HTMLElement|null>(null),consentSection=ref<HTMLElement|null>(null)
const supplementSummary=ref<any>(null)
async function openMaterialChecklist(){toolsOpen.value=false;await nextTick();supplementSummary.value?.reveal()}
const toolsOpen=ref(false),decisionsOpen=ref(false),activeDecisionKey=ref<string|null>(null),showDecisionEdit=ref(false),proposalSaving=ref(false),draftGenerating=ref(false)
const fieldChoiceState=ref({busy:false,error:'',needsRefresh:false,retryable:false}),fieldChoicePreparing=ref(false),fieldChoiceRefreshing=ref(false),fieldChoiceLocalError=ref(''),fieldChoiceAccountChanged=ref(false)
const fieldChoice=createFieldDecision({request:async(body:any,signal:AbortSignal)=>{const {data}=await client.post('/tasks/'+taskId+'/field-decisions',body,{signal});if(String(data?.id)!==taskId)throw new Error('任务回执不匹配');return data},onChange:(value:any)=>{fieldChoiceState.value=value}})
const fieldChoiceScope=()=>String(auth.user?.org_id||'')+':'+String(auth.user?.id||'')
watch(fieldChoiceScope,()=>{fieldChoice.reset();fieldChoiceAccountChanged.value=true;fieldChoiceLocalError.value=''})
const fieldChoiceBusy=computed(()=>fieldChoiceState.value.busy||fieldChoicePreparing.value||fieldChoiceRefreshing.value)
const fieldChoiceError=computed(()=>fieldChoiceLocalError.value||fieldChoiceState.value.error)
const saving=ref(false),assembling=ref(false),resuming=ref(false),lastSaveMessage=ref(''),assistantDraftDirty=ref(false)
const editorRefs=ref<Record<string,any>>({}),decisions=ref<Record<string,{action:string,reason:string}>>({}),issueDecisions=ref<Record<string,{action:string,reason:string}>>({})
const savedDecisions=ref(''),templateNames=ref(['立案审批表','送达材料清单','档案卷宗','结案报告表','质量监督卡'])
const capabilities=ref<any>({supported_extensions:['.pdf'],max_upload_mb:100}),fileInput=ref<HTMLInputElement|null>(null),folderInput=ref<HTMLInputElement|null>(null)
const uploadProgress=ref(0),uploadingName=ref(''),uploadPanel=ref<any>(null)
const {state:uploadState,queue:uploadQueue}=useUploadRecovery({client,getScope:()=>({caseId,accountScope:String(auth.user?.org_id||'')+':'+String(auth.user?.id||'')}),getCapabilities:()=>capabilities.value,onProgress:(done:number,total:number,name:string)=>{uploadProgress.value=total?Math.round(done/total*100):0;uploadingName.value=done?'正在补充 '+done+' / '+total+' · '+name:name}})
const uploading=computed(()=>uploadState.value.busy),uploadErrors=computed(()=>uploadState.value.rows)
const sourcePreview=ref<HTMLElement|null>(null)
function revealSourcePreview(){if(sourcesOpen.value&&sourceUrl.value)sourcePreview.value?.scrollIntoView?.({behavior:'smooth',block:'start'})}
const sourceUrl=ref(''),sourceType=ref(''),sourceName=ref(''),sourceLoading=ref(false)
const evidence=ref<Record<string,any[]>>({}),evidenceField=ref(''),evidenceLoading=ref(false),evidenceError=ref('')
const classificationOpen=ref(false),classificationFile=ref<any>(null),classificationType=ref(''),classifying=ref(false),docTypes=ref<any[]>([])
const documentSaving=ref(false),documentDraftDirty=ref(false),templateBusy=ref<Record<string,boolean>>({})
const templateSaving=computed(()=>Object.values(templateBusy.value).some(Boolean))
const documentReview=ref<any>(null)
let pendingDocumentSource:any=null
const classificationDecisionKey=ref<string|null>(null)
const agentFragments=ref<{done:number,total:number}|null>(null),progressConnected=ref(false)
const visualProgress=ref<any>(null)
const resumeMode=computed(()=>resumeProcessingMode(task.value))
const cloudConsentRequired=computed(()=>taskNeedsCloudConsent(task.value))
const {approved:cloudApproved,reset:resetCloudConsent,payload:cloudConsentPayload}=useCloudConsent(()=>resumeMode.value,()=>taskId+':'+(task.value?.source_version||'')+materialConsentKey(caseInfo.value?.files))
let progressSocket:WebSocket|null=null,logsReceived=false,nextSocketAttempt=0,socketDelay=5000
let sourceRequest=0
let poll:ReturnType<typeof setInterval>|null=null,disposed=false,taskRequest:Promise<boolean>|null=null
const reviewable=computed(()=>['awaiting_review','done'].includes(task.value?.status))
const processing=computed(()=>['pending','running'].includes(task.value?.status))
const finishing=computed(()=>['rendering','assembling','verifying'].includes(task.value?.phase))
const locked=computed(()=>saving.value||assembling.value||resuming.value||uploading.value||classifying.value||documentSaving.value||templateSaving.value||proposalSaving.value||draftGenerating.value||fieldChoiceBusy.value)
const historical=computed(()=>isHistoricalTask(task.value,caseInfo.value?.last_task_id))
const missingItems=computed(()=>(task.value?.catalog_status||[]).filter((item:any)=>!item.found))
const unresolvedCount=computed(()=>unresolvedMissing(missingItems.value,decisions.value).length+unresolvedIssues(task.value?.issues,issueDecisions.value).length)
const confirmationAction=computed(()=>archiveConfirmationAction(task.value,{historical:historical.value,locked:locked.value,documentDraft:documentDraftDirty.value,unresolved:unresolvedCount.value,uploadBlocked:uploadState.value.blocked}))
const advisoryIssues=computed(()=>(task.value?.issues||[]).filter((issue:any)=>!issue.blocking))
const summary=computed(()=>archiveSummary(task.value,{unresolved:unresolvedCount.value,sourceCount:historical.value?null:caseInfo.value?.files?.length??null}))
const primaryAction=computed(()=>{const action=nextArchiveAction(task.value,{unresolved:unresolvedCount.value,hasUnsaved:hasUnsaved(),documentDraft:documentDraftDirty.value,locked:locked.value,uploadErrors:uploadErrors.value.length,historical:historical.value,latestTaskId:caseInfo.value?.last_task_id,cloudConsentRequired:cloudConsentRequired.value,cloudApproved:cloudApproved.value});return action.kind==='retry_uploads'&&!uploadState.value.canRetry?{...action,label:'重新选择待导入材料',hint:'刷新后需要重新选择原文件，只会补传未完成项'}:action})
const materialReview=ref(false)
const allDecisionQueue=computed(()=>buildDecisionQueue(task.value,decisions.value,issueDecisions.value))
const reviewSections=computed(()=>reviewQueueSections(allDecisionQueue.value))
const decisionQueue=computed(()=>materialReview.value?reviewSections.value.materials:reviewSections.value.attention)
const decisionBreakdown=computed(()=>{const pending=decisionQueue.value.filter(item=>!item.resolved);const issues=pending.filter(item=>item.kind==='issue').length,missing=pending.length-issues;return missing?[issues?issues+' 项识别疑问':'',missing+' 项材料待核'].filter(Boolean).join(' · '):''})
const activeDecision=computed(()=>decisionQueue.value.find((item:any)=>item.key===activeDecisionKey.value)||null)
const activeCandidateChoices=computed(()=>candidateFieldDecisions(task.value,activeDecision.value))
const activeOtherSources=computed(()=>{const covered=new Set(activeCandidateChoices.value.flatMap((choice:any)=>choice.sources.map((s:any)=>s.file_id+':'+s.page)));return (activeDecision.value?.sources||[]).filter((s:any)=>!covered.has(s.file_id+':'+s.page))})
const activeHasFieldConflict=computed(()=>hasFieldConflict(activeDecision.value))
const activePendingFieldConflict=computed(()=>hasFieldConflict(activeDecision.value,true))
const activeFieldChoice=computed(()=>currentFieldDecision(task.value,activeDecision.value))
const decisionPosition=computed(()=>decisionQueue.value.findIndex((item:any)=>item.key===activeDecisionKey.value)+1)
const formDrafts=computed(()=>formDraftSummary(task.value))
const pendingForms=computed(()=>pendingFormEntries(task.value))
async function openPendingForm(item:any){
  if(locked.value||processing.value||historical.value||!pendingForms.value.some(entry=>entry.field===item.field))return
  clearReviewTarget();previewTab.value=item.template;reviewFocus.value=item.field;reviewOpen.value=true
  await nextTick();editorRefs.value[item.template]?.revealField?.(item.field)
}
function decisionsSnapshot(){return JSON.stringify({missing:decisions.value,issues:issueDecisions.value})}
function hasUnsavedReview(){return (!!savedDecisions.value&&decisionsSnapshot()!==savedDecisions.value)||Object.values(editorRefs.value).some(editor=>editor.hasUnsavedChanges?.())}
function hasUnsaved(){return hasUnsavedReview()||documentDraftDirty.value}
function setEditorRef(name:string,editor:any){if(editor)editorRefs.value[name]=editor}
const fmtDate=formatShanghaiTime
async function performPrimaryAction(kind:string){
  if(primaryAction.value.disabled)return
  if(kind==='download')return download('zip')
  if(kind==='draft')return generateDraft()
  if(kind==='repair_form')return openFormCorrection()
  if(kind==='resume')return resume()
  if(kind==='retry_uploads')return retryUploads()
  if(kind==='supplement'){fileInput.value?.click();return}
  if(kind==='latest'&&caseInfo.value?.last_task_id)return goTask(caseInfo.value.last_task_id)
  if(kind==='catalog'){catalogOpen.value=true;return}
  if(kind==='consent'){consentSection.value?.scrollIntoView({behavior:'smooth',block:'center'});return}
  if(kind==='issues'){if(task.value?.status==='failed'||operationError.value)errorSection.value?.scrollIntoView({behavior:'smooth'});else openDecisions()}
}
async function loadTask(){
  if(disposed)return false
  if(taskRequest)return taskRequest
  taskRequest=fetchTask()
  try{return await taskRequest}finally{taskRequest=null}
}
async function fetchTask():Promise<boolean>{
  try{
    const {data}=await client.get('/tasks/'+taskId)
    if(disposed)return false
    applyTask(data)
    return true
  }catch(e:any){loadError.value=e.response?.data?.detail||'暂时无法连接工作站。页面中的编辑仍保留，正在尝试恢复。';return false}
  finally{loading.value=false}
}
function applyTask(data:any){
  // An older polling response cannot restore a revision invalidated by a classification save.
  if(task.value && data.revision<task.value.revision)return
  task.value=data;loadError.value='';connectProgress()
  const baseline=savedDecisions.value?JSON.parse(savedDecisions.value):{missing:{},issues:{}}
  const missing=reconcileDecisions((data.catalog_status||[]).filter((item:any)=>!item.found).map((item:any)=>item.seq),decisions.value,baseline.missing,data.fields?._review_decisions||{})
  const issues=reconcileDecisions((data.issues||[]).map((issue:any)=>issue.id),issueDecisions.value,baseline.issues,data.fields?._issue_decisions||{})
  decisions.value=missing.draft;issueDecisions.value=issues.draft
  savedDecisions.value=JSON.stringify({missing:missing.saved,issues:issues.saved})
  activeDecisionKey.value=selectDecision(decisionQueue.value,activeDecisionKey.value)
}
async function beforeDocumentClassification(revision:number):Promise<string>{
  // Flush disabled/inert bindings before checking drafts and allowing the request.
  await nextTick()
  if(taskRequest)await taskRequest
  if(disposed||saving.value||assembling.value||resuming.value||uploading.value||classifying.value||templateSaving.value||proposalSaving.value||draftGenerating.value||fieldChoiceBusy.value||processing.value||historical.value)return '当前任务不可修改，请完成正在进行的操作后重试。'
  if(hasUnsavedReview())return '当前表格或待处理事项尚未保存，请先保存核对草稿，再刷新文书清单后重试。'
  if(task.value?.revision!==revision)return '任务版本已变化，请刷新文书清单并核对后重试。'
  return ''
}
function applyDocumentClassification(data:any){const previous=decisionQueue.value;applyTask(data);if(classificationDecisionKey.value&&finishDecision(classificationDecisionKey.value,previous)){catalogOpen.value=false;decisionsOpen.value=true;classificationDecisionKey.value=null}lastSaveMessage.value='文书分类已保存，可更新草稿并下载';loadCase()}
function classificationDraftBlocksAction(){if(!documentDraftDirty.value)return false;operationError.value='归档目录中有未保存的文书分类，请先保存或取消该项调整。';catalogOpen.value=true;return true}
async function loadCase(){try{caseInfo.value=(await client.get('/cases/'+caseId)).data;return true}catch{return false}}
async function refresh(){return (await Promise.all([loadTask(),loadCase()])).every(Boolean)}
function closeProgress(){const socket=progressSocket;progressSocket=null;progressConnected.value=false;if(socket)socket.close()}
function connectProgress(){
  if(disposed||progressSocket||!auth.token||Date.now()<nextSocketAttempt||(logsReceived&&!processing.value))return
  const protocol=window.location.protocol==='https:'?'wss:':'ws:'
  // Credentials stay in the handshake subprotocol header, never in the URL.
  let socket:WebSocket
  try{socket=new WebSocket(protocol+'//'+window.location.host+'/api/ws/tasks/'+taskId,['gd-workstation','gd-token.'+auth.token])}
  catch{nextSocketAttempt=Date.now()+30000;return}
  progressSocket=socket
  socket.onopen=()=>{if(socket===progressSocket){progressConnected.value=true;socketDelay=5000}}
  socket.onmessage=event=>{
    if(socket!==progressSocket||disposed)return
    try{
      const message=JSON.parse(event.data)
      if(message.type==='log'){const counts=parseAgentFragmentProgress(message.text);if(counts)agentFragments.value=counts;const visual=parseVisualStageProgress(message.text);if(visual)visualProgress.value=visual}
      if(message.type==='progress'){logsReceived=true;if(!processing.value)closeProgress()}
      if(message.type==='done'||message.type==='error'){closeProgress();refresh()}
    }catch{/* An invalid event must not replace persisted task facts. */}
  }
  socket.onerror=()=>{progressConnected.value=false}
  socket.onclose=event=>{
    if(socket!==progressSocket)return
    progressSocket=null;progressConnected.value=false
    if(event.code===4403){agentFragments.value=null;logsReceived=true;return}
    nextSocketAttempt=Date.now()+socketDelay;socketDelay=Math.min(30000,socketDelay*2)
  }
}
async function saveDraft(quiet=false):Promise<boolean>{
  if(saving.value||documentSaving.value||templateSaving.value||proposalSaving.value||fieldChoiceBusy.value||processing.value||historical.value)return false
  const reviewKey=returnDecisionKey.value,previous=decisionQueue.value
  saving.value=true
  try{
    if(taskRequest)await taskRequest
    await saveReviewEditors(templateNames.value,editorRefs.value,reviewOpen.value?previewTab.value:'')
    if(decisionsSnapshot()!==savedDecisions.value){await client.patch('/tasks/'+taskId+'/fields',{fields:{_review_decisions:decisions.value,_issue_decisions:issueDecisions.value}});savedDecisions.value=decisionsSnapshot()}
    if(!(await loadTask()))throw new Error('内容已保存，但尚未取得最新任务状态。请恢复连接后再确认。')
    lastSaveMessage.value='已保存 · '+new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})
    operationError.value=''
    if(reviewKey&&returnDecisionKey.value===reviewKey){finishDecision(reviewKey,previous);reviewOpen.value=false;decisionsOpen.value=true;clearReviewTarget()}
    if(repairingForm.value){reviewOpen.value=false;clearReviewTarget()}
    if(!quiet)ElMessage.success('核对草稿已保存')
    return true
  }catch(e:any){operationError.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:e.message||'草稿保存失败，内容仍保留在页面。';ElMessage.error(operationError.value);return false}
  finally{saving.value=false}
}
function finishDecision(key:string|null,previous:any[]=[]) {
  const persisted=buildDecisionQueue(task.value,task.value?.fields?._review_decisions||{},task.value?.fields?._issue_decisions||{})
  const next=decisionAfterSave(persisted,key,previous)
  activeDecisionKey.value=next;showDecisionEdit.value=false;fieldTargetError.value='';fieldChoiceLocalError.value=''
  return next!==key
}
function openDecisions(){materialReview.value=false;activeDecisionKey.value=selectDecision(decisionQueue.value,activeDecisionKey.value,true);decisionsOpen.value=true}
function openMaterialDecisions(){materialReview.value=true;activeDecisionKey.value=selectDecision(decisionQueue.value,activeDecisionKey.value,true);decisionsOpen.value=true}
function toggleReviewSection(){if(materialReview.value)openDecisions();else openMaterialDecisions()}
function moveDecision(direction:number){activeDecisionKey.value=stepDecision(decisionQueue.value,activeDecisionKey.value,direction,true);showDecisionEdit.value=false;fieldTargetError.value='';fieldChoiceLocalError.value=''}
async function acceptCurrentField(candidateValue?:string){
  const isCandidate=typeof candidateValue==='string'
  if(locked.value||processing.value||historical.value||fieldChoiceAccountChanged.value||(!isCandidate&&!activeFieldChoice.value))return
  const selected=activeDecisionKey.value,previous=decisionQueue.value,scope=fieldChoiceScope()
  fieldChoicePreparing.value=true;fieldChoiceLocalError.value=''
  try{
    await nextTick()
    if(taskRequest)await taskRequest
    if(disposed||scope!==fieldChoiceScope()||processing.value||historical.value||activeDecisionKey.value!==selected)return
    if(hasUnsaved()){fieldChoiceLocalError.value='有未保存的表格、分类或核对说明，请先保存或取消这些修改，再确认此字段。';return}
    const candidate=isCandidate?activeCandidateChoices.value.find((row:any)=>row.selected_value===candidateValue):null
    const target=isCandidate?(candidate?Object.fromEntries(Object.entries(candidate).filter(([key])=>key!=='sources')):null):activeFieldChoice.value
    if(!target)return
    const data=await fieldChoice.accept(target)
    if(!data||disposed||scope!==fieldChoiceScope())return
    applyTask(data);editorRefs.value={};editorVersion.value++
    finishDecision(selected,previous)
    lastSaveMessage.value='已确认使用当前内容；更新档案草稿后可下载，正式归档仍需最后确认。'
    ElMessage.success(isCandidate?'已采用所选内容':'已确认使用当前内容')
  }finally{fieldChoicePreparing.value=false}
}
async function refreshFieldChoice(){
  if(locked.value||processing.value)return
  const scope=fieldChoiceScope();fieldChoiceRefreshing.value=true;fieldChoiceLocalError.value=''
  try{
    // Drain any old polling request before explicitly reading the current task.
    if(taskRequest)await taskRequest
    if(await refresh() && !disposed && scope===fieldChoiceScope()){fieldChoice.refreshed();fieldChoiceAccountChanged.value=false}
    else fieldChoiceLocalError.value='暂未取得工作站最新状态，当前内容仍保留，请恢复连接后重试。'
  }finally{fieldChoiceRefreshing.value=false}
}
function clearReviewTarget(){returnDecisionKey.value=null;reviewFocus.value='';repairingForm.value=false}
async function openFormCorrection(){
  if(locked.value||processing.value||historical.value)return
  clearReviewTarget();repairingForm.value=true
  const target=task.value?.recovery_target
  if(target&&templateNames.value.includes(target.template_name)){
    previewTab.value=target.template_name
    reviewFocus.value=typeof target.field==='string'?target.field:''
  }
  reviewOpen.value=true;await nextTick()
  if(reviewFocus.value)editorRefs.value[previewTab.value]?.revealField?.(reviewFocus.value)
}
function qualitySources(){return task.value?.fields?._original_form_components?.['质量监督卡'] || []}
function originalFormSources(name:string){
  return task.value?.fields?._original_forms?.[name] || (name==='立案审批表' ? task.value?.fields?._source_intake_approval || [] : name==='质量监督卡' ? qualitySources().filter((source:any)=>source.component==='quality_card') : [])
}
function originalFormMessage(name:string){
  if(name==='质量监督卡')return task.value?.fields?._original_forms?.[name]?.length ? '已保留质量监督卡和委托人须知原件，不重复补填。' : '已保留质量监督卡原件，委托人须知随成果补齐。'
  return '已保留原始'+name+'，不重复补填。'
}
async function openDecisionField(){
  const selected=activeDecision.value;if(!selected||locked.value)return
  fieldTargetError.value=''
  const field=selected.field||selected.source.detail?.field||''
  let target=selected.field_targets.find((item:any)=>!originalFormSources(item.template_name).length)
  if(!target&&field){
    try{for(const name of templateNames.value){if(originalFormSources(name).length)continue;const editor=editorRefs.value[name];const keys=editor?.fieldKeys?.();if(keys?.includes(field)){target={template_name:name,field};break}const {data}=await client.get('/tasks/'+taskId+'/preview-fields/'+encodeURIComponent(name));if(data.fields?.some((item:any)=>item.key===field)){target={template_name:name,field};break}}}
    catch{fieldTargetError.value='无法定位填写位置，输入仍保留。请稍后重试或从“查看和修改表格”打开原表。';return}
  }
  if(disposed||activeDecisionKey.value!==selected.key)return
  if(field&&!target){fieldTargetError.value='此字段没有直接对应的可编辑位置，请从“查看和修改表格”选择原表核对。';return}
  returnDecisionKey.value=selected.key;reviewFocus.value=target?.field||''
  if(target)previewTab.value=target.template_name
  reviewOpen.value=true;await nextTick();editorRefs.value[previewTab.value]?.revealField?.(reviewFocus.value)
}
async function saveDecision(noChange:boolean){
  if(locked.value||processing.value||historical.value||!activeDecision.value)return
  const selected=activeDecision.value,previous=decisionQueue.value
  if(selected.kind==='issue'){
    if(noChange&&(hasFieldConflict(selected,true)||selected.members.some((item:any)=>item.kind==='empty_fields')))return
    const reason=issueDecisions.value[selected.source.id].reason.trim()||(noChange?'已对照本组全部原文和提示核对，保持当前内容':'')
    if(!reason)return
    for(const item of selected.members)issueDecisions.value[item.id]={action:'acknowledged',reason:issueDecisions.value[item.id]?.reason.trim()||reason}
  }
  if(await saveDraft(true)){const advanced=finishDecision(selected.key,previous);ElMessage.success(advanced?(activeDecisionKey.value?'已保存，已进入下一项':'本轮核对已完成'):'说明已保存，本项仍待处理')}
}
async function beforeAssistantProposal(revision:number):Promise<string>{
  await nextTick()
  if(taskRequest)await taskRequest
  if(disposed||saving.value||assembling.value||draftGenerating.value||resuming.value||uploading.value||classifying.value||documentSaving.value||templateSaving.value||fieldChoiceBusy.value||processing.value||historical.value)return '当前任务不可修改，请完成正在进行的操作后重试。'
  if(hasUnsaved())return '有未保存的表格、分类或核对说明，请先保存或取消这些修改，再采用建议。'
  if(task.value?.revision!==revision)return '任务版本已变化，请重新询问归档助理。'
  return ''
}
async function beforeAssistantRecovery():Promise<string>{
  await nextTick()
  if(taskRequest)await taskRequest
  if(disposed||saving.value||assembling.value||draftGenerating.value||resuming.value||uploading.value||classifying.value||documentSaving.value||templateSaving.value||fieldChoiceBusy.value||processing.value)return '正在进行其他操作，请完成后再恢复采用状态。'
  if(hasUnsaved())return '有未保存的表格、分类或核对说明，请先保存或取消这些修改，再恢复采用状态。'
  // Recovery restores a recorded before-image; newer materials/history must
  // not trap an interrupted journal behind the normal adoption guard.
  return ''
}
function applyTemplateFields(data:any){const previous=decisionQueue.value;applyTask(data);lastSaveMessage.value='填写内容已保存，更新档案草稿后即可下载';if(returnDecisionKey.value&&!saving.value){finishDecision(returnDecisionKey.value,previous);reviewOpen.value=false;decisionsOpen.value=true;returnDecisionKey.value=null;reviewFocus.value=''}}
function applyAssistantProposal(data:any){applyTask(data);editorRefs.value={};editorVersion.value++;lastSaveMessage.value='建议已写入草稿，可更新档案后下载';loadCase()}
const editorVersion=ref(0)
async function generateDraft(){
  if(locked.value||processing.value||historical.value||classificationDraftBlocksAction())return
  draftGenerating.value=true;operationError.value=''
  try{
    if(!(await saveDraft(true)))return
    const {data}=await client.post('/tasks/'+taskId+'/draft',{expected_revision:task.value.revision})
    reviewOpen.value=false;toolsOpen.value=false;applyTask(data)
  }catch(e:any){operationError.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:'未能生成档案草稿，已保存内容仍然保留。';if(e.response?.status===409)await refresh()}
  finally{draftGenerating.value=false}
}
async function onAssemble(){
  if(unresolvedCount.value||locked.value||historical.value||processing.value||!task.value?.can_assemble||task.value?.source_changed||uploadState.value.blocked||classificationDraftBlocksAction())return
  assembling.value=true;operationError.value=''
  try{
    if(!(await saveDraft(true)))return
    if(unresolvedCount.value||!task.value?.can_assemble||task.value?.source_changed){operationError.value='任务中出现了新的待处理事项，请核对后再确认。';return}
    const revision=task.value.revision
    try{await ElMessageBox.confirm('请确认已核对本案原文、目录和系统表。'+(missingItems.value.length?'本次有 '+missingItems.value.length+' 项材料按你的说明不纳入。':'')+(!task.value.formal_ready?'广东规则仍待核验，本次生成体验归档成果。':''),'最后确认',{confirmButtonText:'确认并生成',cancelButtonText:'继续核对',type:'info'})}catch{return}
    await client.post('/tasks/'+taskId+'/assemble',{order_mode:task.value.order_mode||'catalog',skipped:missingItems.value.map((item:any)=>item.seq),confirmed_revision:revision,confirmation:true})
    reviewOpen.value=false;toolsOpen.value=false;await loadTask()
  }catch(e:any){operationError.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:'未能生成归档，已保存的草稿仍可继续核对。';if(e.response?.status===409){await refresh();operationError.value+=' 请核对最新状态后重新确认。'}}
  finally{assembling.value=false}
}
async function resume(){
  if(locked.value||classificationDraftBlocksAction())return
  if(uploadState.value.blocked){operationError.value='请先完成或移除待导入项，并确认待上传清单已读取。';return}
  if(hasUnsaved()&&!(await saveDraft(true)))return
  resuming.value=true;operationError.value=''
  try{if(!(await refresh()))throw new Error('未能核对最新材料和处理方式，请恢复连接后重试。');const consent=taskNeedsCloudConsent(task.value)?cloudConsentPayload():{cloud_consent:false,expected_processing_mode:resumeMode.value};const {data}=await client.post('/tasks/'+taskId+'/resume',consent);resetCloudConsent();if(String(data.id)!==taskId)goTask(data.id);else await refresh()}catch(e:any){operationError.value=e.response?.data?.detail||e.message||'暂时无法继续，已保存的进度仍保留。'}finally{resuming.value=false}
}
function onFilesSelected(event:Event){const input=event.target as HTMLInputElement;const files=Array.from(input.files||[]);input.value='';uploadAndContinue(files)}
async function dismissUpload(id:string){if(locked.value||processing.value)return;await uploadQueue.remove(id)}
async function recoverUploads(files:File[]){if(locked.value||processing.value)return;await uploadQueue.recover(files)}
async function retryUploads(){if(!uploadState.value.canRetry){uploadPanel.value?.selectFiles();return};await uploadAndContinue([],true)}
async function uploadAndContinue(files:File[],retry=false){
  if(locked.value||processing.value||(!retry&&!files.length)||classificationDraftBlocksAction())return
  if(hasUnsaved()&&!(await saveDraft(true)))return
  resetCloudConsent();operationError.value='';uploadProgress.value=0
  const complete=retry?await uploadQueue.retry():await uploadQueue.add(files)
  await refresh()
  if(complete&&!uploadState.value.blocked&&!taskNeedsCloudConsent(task.value))await resume()
}
function goTask(id:number){router.push('/cases/'+caseId+'/tasks/'+id)}
async function download(kind:string){try{const {data}=await client.get('/tasks/'+taskId+'/download/'+kind,{responseType:'blob'});const url=URL.createObjectURL(data);const a=document.createElement('a');a.href=url;a.download=(caseInfo.value?.title||'案件')+(historical.value?'_历史成果':'')+(task.value?.delivery_kind==='draft'||task.value?.status==='awaiting_review'?'_草稿':'')+(kind==='zip'?'_归档成果.zip':'_完整卷宗.pdf');a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}catch{ElMessage.error('成果下载失败，请稍后重试')}}
function clearSource(){sourceRequest++;if(sourceUrl.value)URL.revokeObjectURL(sourceUrl.value);sourceUrl.value='';sourceName.value='';sourceLoading.value=false}
async function openSource(file:any){clearSource();const request=sourceRequest;sourceLoading.value=true;try{const {data}=await client.get('/cases/'+caseId+'/files/'+file.id+'/original',{responseType:'blob'});if(request!==sourceRequest||disposed)return;const url=URL.createObjectURL(data);sourceName.value=file.filename;if(/\.pdf$/i.test(file.filename)){sourceType.value='pdf';sourceUrl.value=url}else if(/\.(jpe?g|png|bmp|tiff?|webp)$/i.test(file.filename)){sourceType.value='image';sourceUrl.value=url}else{const a=document.createElement('a');a.href=url;a.download=file.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}}catch{if(request===sourceRequest)ElMessage.error('无法读取原件，请稍后重试')}finally{if(request===sourceRequest)sourceLoading.value=false}}
async function loadEvidence(){evidenceLoading.value=true;evidenceError.value='';try{evidence.value=(await client.get('/tasks/'+taskId+'/evidence')).data.fields||{}}catch{evidenceError.value='字段依据暂时无法读取，仍可打开原件核验。'}finally{evidenceLoading.value=false}}
function showEvidence(field:string){evidenceField.value=field;sourcesOpen.value=true}
function showAssistantSource(entry:any){evidenceField.value=entry.field||'';sourcesOpen.value=true;openEvidence(entry)}
function showDecisionSource(entry:any){showAssistantSource({...entry,field:activeDecision.value?.field||activeDecision.value?.source.detail?.field||''})}
function openAssistantAction(type:string){if(type==='sources')sourcesOpen.value=true;else if(type==='catalog')catalogOpen.value=true;else if(type==='fields')reviewOpen.value=true}
function showClassificationSource(issue:any){showAssistantSource(issue.detail||{})}
function showDocumentClassification(issue:any){classificationDecisionKey.value=activeDecisionKey.value;pendingDocumentSource=issue.detail||{};catalogOpen.value=true;nextTick(revealPendingDocument)}
async function revealPendingDocument(){if(!documentReview.value||!pendingDocumentSource)return;const source=pendingDocumentSource;pendingDocumentSource=null;await documentReview.value.reveal(source)}
async function openClassification(issue:any){
  const file=caseInfo.value?.files?.find((item:any)=>item.id===issue.detail?.file_id)
  if(!file){ElMessage.warning('未找到这份原件，请刷新案件材料后重试');return}
  try{docTypes.value=(await client.get('/cases/meta/doc-types',{params:{case_type:caseInfo.value.case_type}})).data;classificationFile.value=file;classificationType.value=file.doc_type;classificationOpen.value=true}catch{ElMessage.error('暂时无法读取分类选项，请重试')}
}
async function applyClassification(){
  if(locked.value||!classificationFile.value||classificationType.value===classificationFile.value.doc_type||classificationDraftBlocksAction())return
  if(hasUnsaved()&&!(await saveDraft(true)))return
  classifying.value=true;operationError.value=''
  try{
    await client.patch('/cases/'+caseId+'/files/'+classificationFile.value.id,{doc_type:classificationType.value})
    classificationOpen.value=false
    resetCloudConsent();if(!(await refresh()))throw new Error('分类已保存，但尚未核对最新材料，请恢复连接后继续。')
    if(taskNeedsCloudConsent(task.value)){lastSaveMessage.value='整文件分类已保存，确认本次云端处理后继续。';return}
    const {data}=await client.post('/tasks/'+taskId+'/resume',{cloud_consent:false,expected_processing_mode:resumeMode.value})
    if(String(data.id)!==taskId)goTask(data.id);else await refresh()
  }catch(e:any){operationError.value=e.response?.data?.detail||'分类调整暂未完成，已保存的核对内容仍保留。';await refresh()}
  finally{classifying.value=false}
}
async function openEvidence(entry:any){clearSource();const request=sourceRequest;sourceLoading.value=true;try{const {data}=await client.get('/cases/'+caseId+'/files/'+entry.file_id+'/page/'+entry.page,{responseType:'blob'});if(request!==sourceRequest||disposed)return;sourceUrl.value=URL.createObjectURL(data);sourceType.value='image';sourceName.value=entry.filename+' · 第 '+entry.page+' 页'}catch{if(request===sourceRequest)ElMessage.error('原文页暂时无法读取，请打开完整原件核验')}finally{if(request===sourceRequest)sourceLoading.value=false}}
function beforeUnload(event:BeforeUnloadEvent){if(hasUnsaved()||assistantDraftDirty.value||uploadState.value.navigationDirty){event.preventDefault();event.returnValue=''}}
onBeforeRouteLeave(async()=>{if(!hasUnsaved()&&!assistantDraftDirty.value&&!uploadState.value.navigationDirty)return true;try{await ElMessageBox.confirm(uploading.value?'材料正在上传，离开会中断未完成的导入。':'尚有未登记的导入项、未同步的对话文字或未保存的核对内容，离开会丢失这些修改。','离开当前任务？',{confirmButtonText:'离开',cancelButtonText:'继续处理',type:'warning'});return true}catch{return false}})
onMounted(async()=>{await refresh();try{const {data}=await client.get('/tasks/'+taskId+'/templates');if(data.templates?.length){templateNames.value=data.templates;previewTab.value=data.templates[0]}}catch{}try{capabilities.value=(await client.get('/cases/meta/import-capabilities')).data}catch{}poll=setInterval(()=>{if(!locked.value)refresh()},5000);window.addEventListener('beforeunload',beforeUnload);if(route.query.review==='1')reviewOpen.value=true;if(route.query.focus==='decisions')openDecisions()})
onUnmounted(()=>{disposed=true;fieldChoice.reset();if(poll)clearInterval(poll);closeProgress();clearSource();window.removeEventListener('beforeunload',beforeUnload)})
</script>
<style scoped>
.result-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.result-actions .el-button+.el-button{margin-left:0}
.form-followups{display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;padding:12px 18px;margin:12px 0;background:#fff;border-radius:12px;font-size:12px;color:#6e6e73}.form-followups .el-button{margin:0;font-size:12px}
.page-alert{margin-bottom:20px}.conflict-evidence{font-size:12px;line-height:1.8;background:#f5f5f7;padding:12px;margin:16px 0;color:#6e6e73}.conflict-evidence p{margin:5px 0}.button-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:20px}.button-row .el-button{margin-left:0}.error-message{font-size:13px;line-height:1.9;color:#a17d60;overflow-wrap:anywhere}.review-link{display:flex;align-items:center;justify-content:space-between;width:100%;text-align:left;background:transparent;border:0;border-bottom:1px solid #e5e5ea;padding:18px 0;cursor:pointer;color:#424245;font-size:13px}.review-link small{display:block;margin-top:8px;color:#6e6e73;font-size:11px}.review-link:disabled{opacity:.45;cursor:default}.small-details{font-size:11px;line-height:1.9;margin-top:24px}.small-details summary{cursor:pointer}.source-file-list{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}.source-file-list button{background:#f5f5f7;border:1px solid #e5e5ea;border-radius:5px;padding:8px 12px;color:#424245;font-size:12px;cursor:pointer;display:flex;gap:6px;align-items:center;max-width:100%;overflow-wrap:anywhere}.source-preview{border:1px solid #e5e5ea;width:100%;height:68vh}.source-image{max-width:100%;max-height:68vh}.evidence-panel{padding-bottom:22px;border-bottom:1px solid #e5e5ea;margin-bottom:22px}.evidence-entry{padding:12px 0;color:#6e6e73;font-size:12px;line-height:1.8}.evidence-entry blockquote{margin:8px 0 12px;padding:10px 14px;background:#f5f5f7;border-left:2px solid #d2d2d7;white-space:pre-wrap}.evidence-entry p{margin:6px 0}.resume-cloud-consent{margin:20px 0}.advisory-details{margin:20px 0 12px;padding-top:15px;border-top:1px solid #e5e5ea;color:#6e6e73;font-size:12px;line-height:1.9}.advisory-details>summary{cursor:pointer}.advisory-row{padding:16px 0;border-bottom:1px solid #f5f5f7}.advisory-row>strong{font-weight:400;overflow-wrap:anywhere}.advisory-row .el-button{display:block;margin:4px 0;white-space:normal;text-align:left;height:auto;min-height:28px}.assistant-unavailable{padding:16px 0}
</style>
<style scoped>
.task-workspace{max-width:780px;padding-bottom:25px}.task-heading{display:flex;justify-content:space-between;gap:25px;align-items:center;padding-bottom:24px;border-bottom:1px solid #e5e5ea;margin-bottom:28px}.task-heading h1{font-size:16px;font-weight:500;line-height:1.8;color:#424245;margin:9px 0 4px;overflow-wrap:anywhere}.task-heading p{font-size:10px;color:#6e6e73;line-height:1.8;margin:0}.task-heading .back-link{font-size:11px}.task-heading>.el-button{flex:none}.task-workspace :deep(.archive-action-bar){position:static;box-shadow:none;margin:12px 0 24px;background:white;padding:18px 20px}.task-workspace :deep(.action-eyebrow){display:none}.task-workspace :deep(.archive-action-bar p){margin:0}.result-note{display:flex;align-items:center;flex-wrap:wrap;justify-content:space-between;gap:12px;font-size:11px;color:#6e6e73;margin:5px 0}.result-note p{width:100%;margin:0}.error-card{padding:12px 18px;margin:14px 0;border:1px solid #ecdcc9;border-radius:10px;background:#fffaf3}.error-card a{font-size:12px;color:#987d60}.draft-summary{display:flex;align-items:center;flex-wrap:wrap;gap:6px 16px;font-size:10px;color:#6e6e73;line-height:1.8;margin:12px 0}.draft-summary .el-button{font-size:10px}.management-link{display:block;margin:28px 0;font-size:12px;color:#6e6e73}.small-details{color:#6e6e73;overflow-wrap:anywhere}
.field-choice{margin:16px 0;padding:16px;border:1px solid #e5e5ea;border-radius:8px;font-size:13px;color:#424245}.field-current-value{white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;line-height:1.8}.field-choice .muted{margin-bottom:0;font-size:11px}
</style>






