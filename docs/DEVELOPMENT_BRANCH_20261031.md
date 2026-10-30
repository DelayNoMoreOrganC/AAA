# 跨电脑接续开发

分支：`dev/agent-prd-20261031`。主线 `main` 保留参赛版本；请在本分支或从它新建的个人分支修改。

```powershell
git clone --branch dev/agent-prd-20261031 --single-branch https://github.com/DelayNoMoreOrganC/AAA.git AAA-dev
cd AAA-dev
```

已有仓库且工作区干净时：

```powershell
git fetch origin
git switch --track origin/dev/agent-prd-20261031
```

若有未提交改动先保存，勿使用强制reset覆盖。分支已在本机存在则直接 `git switch dev/agent-prd-20261031`。

随后按README的全新环境步骤安装Python依赖、构建前端并启动。推荐Python3.12和Node20；文档渲染另需可用的办公转换组件。本快照没有预装依赖、模型权重、数据库和API密钥，不是复制即用的安装包。首次启动新建本机管理员并配置模型，不复用旧电脑数据库。不要对旧运行目录直接覆盖。

先读PRD v1.2、Handoff和20261031逐格规格。下一重点是20次预算内的核心取材、辅助证据按需阅读及完整填表，随后才是独立经验闭环。最新合批及字段修复为候选，未宣称真实整链/五类业务通过。

本次只做源码发布检查，不新增模型调用、不运行客户卷宗、不恢复原目标。源文件清单及哈希见SOURCE_SNAPSHOT.json；私有验收JSON/XML不随仓库上传。
