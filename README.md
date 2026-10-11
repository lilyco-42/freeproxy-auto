# freeproxy-auto

免费 V2Ray/Trojan/SS/Clash 节点自动聚合 + 测速订阅，纯 GitHub Actions 驱动，免费无限分钟（public repo）。

> 每 3 小时自动跑一次：拉取 **40+ 个 GitHub 免费节点源** → `subs-check`(mihomo) 真实协议连通性 + 下载测速 → 去重合并 → 生成 Clash / V2Ray 订阅回传本仓库。

## 🚀 使用方法（Clash Verge / mihomo）

把下面这条订阅链接加进 Clash Verge：

```
https://raw.githubusercontent.com/lilyco-42/freeproxy-auto/main/output/clash.yaml
```

- 含 `🔍 自动选择`（url-test 自动挑最快节点）与 `🎯 手动选择` 两个策略组
- 规则默认：`GEOIP,CN,DIRECT`（国内直连）+ 其余走自动选择
- 每 3 小时更新一次；节点挂了会自动从下一次产出去除

其他格式：

| 格式 | 链接 |
|---|---|
| Clash/Mihomo | `output/clash.yaml` |
| Base64 通用 | `output/v2ray.txt` |
| 节点状态报告 | `output/status.md` |

## 🔧 维护

- **增删节点源**：编辑 [`sources.txt`](sources.txt)（每行一个订阅 URL，`#` 注释），提交后自动重跑
- **手动触发一次**：Actions → Update Free Nodes → Run workflow
- **调整检测参数**：编辑 [`config/base.yaml`](config/base.yaml)（并发、超时、最低测速等）

## ⚠️ 免责声明与风险提示

1. **测试点在 GitHub（美国）出口**：测出的延迟与速度排名只代表"从 GitHub 出发"，不等于你在国内的体验；用于筛选存活节点足够，选最终节点请以实际体验为准。
2. **免费公共节点 = 蜜罐高发区**：**绝不要**在通过这些节点的连接里登录账号、输入密码或传输敏感数据。
3. 本项目仅做公开订阅的抓取与聚合，上游源随时可能失效，由此带来的任何风险由使用者自行承担。
4. 请遵守所在国家/地区的法律法规。

## 数据流

```
sources.txt ──> subs-check (mihomo 内核测活+测速) ──> artifacts/all.yaml
                                                        │
                                                        ▼
                                build-artifacts.py ──> output/clash.yaml / v2ray.txt / status.md
```