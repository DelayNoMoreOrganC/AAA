# 工作站局域网启用与客户端证书说明

此流程由律所部署管理员审查后执行，**所附专用脚本仅完成静态审查，尚未执行**。此前直接创建防火墙规则返回 `Access denied`，CA 信任安装在 Windows 确认前停止，均未完成。第二台电脑通过受信任 HTTPS 使用的端到端验收仍未通过。

## 服务端：只开放律所内网入口

先在工作站本机运行“启动工作站.cmd”，确认本机页面、账号和模型可用；模型未就绪时应先解决本机问题。启动器文字提示不替代页面就绪检查、HTTPS 实际监听检查或客户端证书验证。后端和模型应继续只监听回环地址。确认使用者接入的是律所可信网络，选取工作站真实的内网 IPv4 和网卡别名，不能选择 VPN、虚拟机交换机、公共 Wi-Fi 或未知接口。

在工作站 PowerShell 中只读查看，选择对应的 IP 和网卡；下列占位值必须替换：

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress, InterfaceAlias, InterfaceIndex
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory

# 在项目根目录执行。默认仅检查，不改变设置。
& '.\scripts\Enable-WorkstationLan.ps1' -LanAddress '<律所内网IP>' -InterfaceAlias '<网卡别名>'
```

脚本检查路径不能是链接/联接点、Caddy 二进制指纹、已准备配置中的内网地址、固定回环反向代理、实际监听进程、本机后端标识及公钥 CA 有效期。所选接口必须已经是 Private 或 Domain 网络；脚本不会擅自更改网络类别，也不会修改目录 ACL。

审核后，另开“以管理员身份运行”的 PowerShell；可先加 `-Apply -WhatIf` 查看计划。执行策略若阻止脚本，应按律所的签名与执行政策处理，不关闭系统安全设置。

```powershell
& '.\scripts\Enable-WorkstationLan.ps1' -LanAddress '<律所内网IP>' -InterfaceAlias '<网卡别名>' -Apply -WhatIf
& '.\scripts\Enable-WorkstationLan.ps1' -LanAddress '<律所内网IP>' -InterfaceAlias '<网卡别名>' -Apply
```

启用只创建本安装专用规则：Caddy 程序、TCP 8443、所选 IP/网卡、Private/Domain 配置文件、`LocalSubnet` 来源，并禁止边缘穿越。它不会开放 8765/11434、公网端口或路由器映射，不会启动/重启服务或修改其他防火墙规则。若本机还有其他管理员配置的广泛放行规则，应另行审查；本脚本不声称替代整个主机防火墙审计。[参数依据：Microsoft New-NetFirewallRule](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule)

遇到 `Access denied` 应停止并由有权限的管理员处理，不反复提权或改成 Public/Any。同名专用规则已存在时脚本不会覆盖；需要检查其范围再由管理员处理。关闭本脚本创建的入口时，可审查后执行：

```powershell
& '.\scripts\Enable-WorkstationLan.ps1' -Disable -Apply
```

此命令只禁用该安装专用防火墙规则；不删除其他规则，不撤销客户端证书信任。工作站搬到新路径、IP 变化、Caddy 升级或证书更新后，须重新核对配置、证书覆盖地址、二进制指纹和规则，不能直接复用旧结论。

## 客户端：仅接收公钥 CA，由使用者确认信任

启用脚本只将以下两份文件放入 `workstation-data/tls/client-public/`，供管理员以可信方式交付：

- `GD-workstation-CA.crt`：公钥根证书，不含私钥。
- `CA-fingerprints.txt`：证书文件 SHA-256、证书 DER SHA-256、证书存储标识与入口 URL。

**绝不分发 `root.key`、`server.key`、整个 `tls` 目录或含私钥的 PFX。** 管理员应通过另一个可信渠道向使用者确认 SHA-256；只把证书与同一来源的指纹文本同时收到，并不能单独证明来源可信。

在员工自己的 Windows 登录会话中检查收到的证书文件摘要：

```powershell
Get-FileHash -LiteralPath '<收到的目录>\GD-workstation-CA.crt' -Algorithm SHA256
```

确认其与管理员另行提供的 **File SHA256** 一致，并确认这是本律所工作站的 CA。信任根证书会使当前用户信任它所签发的证书，应由用户或律所管理策略明确批准。随后可使用证书界面导入到“当前用户 → 受信任的根证书颁发机构”，或执行：

```powershell
certutil.exe -user -addstore Root '<收到的目录>\GD-workstation-CA.crt'
```

Windows 可能要求用户确认；应由使用者核对后决定，脚本不会自动点击、静默绕过或替使用者接受。不选择“本地计算机”的全机信任，不使用忽略证书错误或跳过验证参数。[命令依据：Microsoft certutil](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/certutil)

打开 `https://<律所内网IP>:8443/`，地址须与管理员提供的入口一致。若仍有证书告警、地址不匹配或无法连接，停止登录和导入，由管理员检查，不能以“高级继续访问”代替验证。若不再使用，可在当前用户证书管理器中按记录的证书标识精确删除本 CA；不要按相似名称批量删除证书。

## 必须用第二台电脑完成的验收

1. 同一可信内网客户端打开 HTTPS 页面，无证书告警；验证普通用户仅能访问自己创建的案件，同机构其他普通用户和跨机构账号不能读取其材料、来源页、任务或下载；本机构管理员可管理本机构案件，跨机构管理仍被拒绝。
2. 使用虚构 PDF、图片和受支持的 Word 文件测试导入、实际分析、集中核对、PDF/Word/ZIP 下载；检查自动保存发生在工作站目录。
3. 确认员工电脑不能直接访问工作站 8765/11434；核对专用规则不适用于 Public 网络或外部地址。跨 VLAN/路由子网若不属于 `LocalSubnet`，当前脚本不会擅自扩大范围。
4. 记录工作站地址、网卡、规则名、证书指纹、客户端、测试时间和未通过项。只有这些步骤完成后，才能把局域网使用标为已验收。

本轮未执行以上客户端验收，不因本机 Caddy 响应或脚本语法检查通过而提前宣称局域网可用。
