<template>
  <div class="feedback-page">
    <h3>使用问题反馈</h3>
    <el-card class="feedback-card">
      <div class="feedback-heading">
        <el-icon class="feedback-icon"><Message /></el-icon>
        <div>
          <h2>遇到问题，请通过邮箱联系我们</h2>
          <p>我们会根据你提供的信息排查使用、识别、表格编辑和归档生成问题。</p>
        </div>
      </div>

      <div class="email-panel">
        <span class="email-label">反馈邮箱</span>
        <el-link
          class="email-link"
          href="mailto:juno_chiko@qq.com?subject=%E6%A1%88%E4%BB%B6%E5%BD%92%E6%A1%A3V6%E4%BD%BF%E7%94%A8%E9%97%AE%E9%A2%98%E5%8F%8D%E9%A6%88"
          type="primary"
          :underline="false"
        >juno_chiko@qq.com</el-link>
      </div>

      <el-divider />
      <h4>建议在邮件中说明</h4>
      <ul class="feedback-list">
        <li>发生问题的案件名称和任务编号；</li>
        <li>问题出现前的操作步骤；</li>
        <li>页面提示或错误信息，以及必要的截图；</li>
        <li>希望系统实现的正确效果。</li>
      </ul>
      <el-alert
        title="请勿在反馈邮件中发送 LLM API Key、OCR Token、登录密码等敏感信息。"
        type="warning"
        :closable="false"
        show-icon
      />
    </el-card>
  </div>
</template>

<style scoped>
.feedback-page h3 { margin-top: 0; }

.feedback-card { max-width: 720px; }

.feedback-heading {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.feedback-heading h2 {
  margin: 0 0 8px;
  color: #1d2129;
  font-size: 20px;
}

.feedback-heading p {
  margin: 0;
  color: #606266;
  line-height: 1.7;
}

.feedback-icon {
  flex: none;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #ecf5ff;
  color: #409eff;
  font-size: 24px;
}

.email-panel {
  display: flex;
  margin: 24px 0 4px;
  padding: 18px 20px;
  align-items: center;
  gap: 18px;
  border: 1px solid #d9ecff;
  border-radius: 8px;
  background: #f5faff;
}

.email-label { color: #606266; }
.email-link { font-size: 18px; font-weight: 600; }

.feedback-list {
  margin: 0 0 20px;
  padding-left: 22px;
  color: #4e5969;
  line-height: 2;
}

@media (max-width: 640px) {
  .feedback-heading { flex-direction: column; }
  .email-panel { align-items: flex-start; flex-direction: column; gap: 6px; }
}
</style>
