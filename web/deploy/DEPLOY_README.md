# 案件归档系统 V6 部署说明

> 本文保留 V6 历史部署参考。当前工作站分支请优先使用项目根目录启动入口，并按 [工作站开发版 0.1](../../docs/WORKSTATION_V0.1.md) 完成部署与初始化。

## 一、本机或局域网部署（macOS / Linux，优先）

要求：Python 3.12、Node.js 20+、Google Chrome 或 Chromium，并能访问已配置的 OCR 与 LLM 服务。预览模式不要求安装 Microsoft Word。

```bash
cd web/frontend
npm ci
npm run build

cd ../backend
python3 -m venv ../.venv
../.venv/bin/pip install -r requirements.txt
../.venv/bin/python run.py
```

本机访问：<http://127.0.0.1:8000>

局域网访问：在 `web/.env` 中配置：

```dotenv
V5_HOST=0.0.0.0
V5_PORT=8000
V5_PREVIEW_ONLY=true
V5_CHROMIUM_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
V5_SECRET_KEY=replace-with-a-long-random-secret
```

重启服务后，其他设备通过 `http://服务器局域网IP:8000` 访问。还需确保系统防火墙允许对应端口入站。

Linux 生产环境建议使用 systemd 管理单个 uvicorn worker，并通过 nginx/Caddy 提供 HTTPS、请求体大小限制和 WebSocket 代理。

## 二、Windows DOCX 模式

要求：Windows 10/11 或 Windows Server、Python 3.12、Microsoft Word，以及可访问 OCR/LLM API 的网络。

1. 在开发机运行 `web\deploy\pack_for_windows.bat`，得到 `%TEMP%\v6_deploy.zip`。
2. 解压到例如 `D:\ArchiveV6\`。
3. 首次运行 `install.bat`，以后运行 `start_server.bat`。
4. 在 `app\web\.env` 设置 `V5_PREVIEW_ONLY=false`。
5. 需要开机启动时，安装 NSSM 后以管理员身份运行 `install_service.bat`。

环境变量使用 `V5_` 前缀是为了兼容既有配置，并非版本号。

### Windows 防火墙

以管理员身份运行 PowerShell：

```powershell
New-NetFirewallRule -DisplayName "V6-Archive" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

## 三、账号初始化

没有内置管理员或律师账号，也没有固定初始密码。首次初始化须在工作站本机完成：

1. 使用项目根目录的工作站启动入口，打开其提供的一次性 `/setup` 链接。
2. 填写律所名称，自行设置管理员账号及至少 12 位密码；初始化成功后一次性令牌失效。
3. 登录后按 [工作站说明](../../docs/WORKSTATION_V0.1.md) 配置本地识别服务。律所名称会用于系统表。

## 四、数据与备份

```text
web/data/
├── archive.db     SQLite 数据库
└── orgs/          上传文件、任务快照和输出结果
```

停服后备份整个 `web/data/`。恢复时保持相同目录结构和文件权限。

## 五、常见问题

**局域网设备无法访问**

确认 `V5_HOST=0.0.0.0`、服务已重启、访问的是服务器局域网 IP，并检查操作系统防火墙与路由器的客户端隔离设置。

**macOS / Linux 没有 DOCX 下载**

这是预览模式的设计行为。系统表在浏览器中编辑，并由 Chrome/Chromium 直接生成 PDF；DOCX/Word COM 流程仍需要 Windows。

**提示未找到 PDF 生成器**

安装 Chrome/Chromium，或在 `web/.env` 中用 `V5_CHROMIUM_PATH` 指定浏览器可执行文件的绝对路径，然后重启服务。

**Windows 模板填充失败**

确认 Microsoft Word 已安装，运行服务的 Windows 用户能正常打开 Word，并保持后端单 worker。

**OCR 或字段提取失败**

使用当前登录账号打开“我的 API 配置”，检查该账号自己的 Token、Key、模型地址与外网连通性。

**端口占用**

修改 `web/.env` 中的 `V5_PORT` 后重启，并同步修改防火墙与反向代理配置。
