# 配置参考（CONFIG）

> **上游依据**：`.env.example`、`zhanzhen/cli.py`、`zhanzhen/service.py`、`zhanzhen/webapp.py`、`zhanzhen/ai_assistant.py`、`Dockerfile` / `docker-compose.yml`。
> **读者**：部署与运维湛箴的用户；每个环境变量给出**作用 / 默认值 / 改动影响 / 安全提示**。
> **文档版本**：v0.1 · 更新日期：2026-08-25 · 状态：已有

---

## 1. 配置怎么生效

湛箴 v0.1.0 只读**环境变量**（前缀 `ZZ_`），没有配置文件解析层。三种注入方式：

```bash
# ① 命令行临时注入（bash）
ZZ_PORT=9000 zhanzhen serve

# ② PowerShell
$env:ZZ_PORT = "9000"; zhanzhen serve

# ③ .env 文件 —— 仅 docker compose 自动加载（compose 原生行为）
cp .env.example .env && docker compose up -d
```

优先级：**命令行参数 > 环境变量 > 内置默认值**。例如 `--port` 显式传参会覆盖 `ZZ_PORT`。

安全红线：`.env` 含密钥时**绝不提交 Git**（仓库 `.gitignore` 已排除；提交前自查
`git status`）。真实密钥只放环境变量或秘密管理器，依据 spec §12。

---

## 2. ZZ_* 变量总表

| 变量 | 默认值 | `.env.example` 示例 | 消费位置 |
|------|--------|---------------------|----------|
| `ZZ_DATA_DIR` | `.zzdata`（代码内置） | `./data` | `service.py`、`cli.py verify` |
| `ZZ_TENANT_ID` | `default` | `demo-tenant` | `webapp.py`、`cli.py verify` |
| `ZZ_REVIEW_THRESHOLD` | `0.80` | `0.80` | `service.py`（覆核质量门） |
| `ZZ_PORT` | `8710` | `8710` | `cli.py serve`、compose 端口映射 |
| `ZZ_AI_BASE_URL` | 空（=关闭） | 注释状态 | `ai_assistant.py` |
| `ZZ_AI_API_KEY` | 空（=关闭） | 注释状态 | `ai_assistant.py` |
| `ZZ_AI_MODEL` | 空（=关闭） | 注释状态 | `ai_assistant.py` |

> ⚠️ 默认值差异提醒：代码兜底默认是 `.zzdata`，而 `.env.example` 写的是 `./data`，
> Docker 镜像内是 `/data`。三个入口不一致是历史现状——**生产环境请始终显式设置
> `ZZ_DATA_DIR`**，不要依赖默认值。

---

## 3. 逐项详解

### 3.1 `ZZ_DATA_DIR` — 数据根目录

- **作用**：全部持久化数据的根。目录结构：

```
$ZZ_DATA_DIR/
├── objects-root/                     # 原始文件对象存储（按 SHA-256 寻址，服务端重算哈希）
└── tenants/<ZZ_TENANT_ID>/
    └── snapshot-<ZZ_TENANT_ID>.json  # 内存仓储快照：凭证/分录/发现/风格样本/事件链
```

- **备份/迁移** = 复制整个目录（停机后复制最稳）；换机器迁移同理。
- **删除** = 删库不可逆，见 [PRIVACY.md](PRIVACY.md) 的删除章节。
- **安全提示**：
  - 快照是**明文 JSON**，含交易金额、对手方等敏感信息——把目录权限收紧到仅运行账户可读
    （`chmod 700` / Windows 下限制用户列表）。
  - 不要把该目录放进任何会自动同步到公网网盘的位置。
  - 并发写入未加锁（LIMITATIONS.md #3）：同一数据目录**不要**起两个服务实例同时写。

### 3.2 `ZZ_TENANT_ID` — 租户标识

- **作用**：决定快照文件名与数据隔离路径；Web 层从配置取值、不信前端传参。
- **默认**：`default`；示例配置为 `demo-tenant`。
- **改动影响**：换 ID 即切到另一套空账套（旧快照仍在原目录下），可用于「一家企业一个 ID」的轻量隔离。
- **安全提示**：MVP 是单租户实现，**没有登录/RBAC**（LIMITATIONS.md #2）。多租户只是目录级隔离，
  别把它当访问控制用；绝不要把真实客户数据的服务暴露到公网。

### 3.3 `ZZ_REVIEW_THRESHOLD` — 覆核阈值

- **作用**：OCR 结果置信度低于该值 → 凭证进入 `NEEDS_REVIEW` 强制人工覆核；高于则可直通 `REVIEWED`
  分支（判定逻辑在 `service.py` 的 `needs_review_reasons(vj, threshold)`）。
- **类型/范围**：浮点数 `0 ~ 1`。
- **默认**：`0.80`（与 OCR Provider 内部置信度打分口径一致）。
- **调参建议**：
  - 调低（如 0.70）→ 更少人工覆核、更多低质数据直通——**不建议在真实审计场景调低**；
  - 调高（如 0.90）→ 更保守，更多凭证被拦进人工队列。
- **安全提示**：该值直接决定「机器自动过 vs 人看」的分界。审计证据链里这是质量门，改完请在
  底稿层面留痕说明理由；规则参数（`rules_builtin.yaml`）变更需同步测试，本阈值同理建议跑一遍
  `pytest tests/test_pipeline.py` 验证质量门行为未破坏。

### 3.4 `ZZ_PORT` — Web 监听端口

- **作用**：`zhanzhen serve` 的监听端口；Docker compose 里作为**宿主机映射端口**
  （映射格式 `${ZZ_PORT:-8710}:8710`，容器内部固定 8710）。
- **默认**：`8710`（刻意避开常用 8000/8080，见 `.env.example` 注释）。
- **覆盖方式**：命令行 `zhanzhen serve --port 9000` 优先于环境变量。
- **安全提示**：
  - 直装/源码方式默认绑 `127.0.0.1`，仅本机可用——保持这样；
  - Docker 方式绑定 `0.0.0.0`，等于对局域网开放且**没有任何登录**——务必放在防火墙/反代之后；
  - 对外提供时前置 Nginx/Caddy 做 TLS 与访问控制，湛箴自身不终止 TLS。

### 3.5 `ZZ_AI_BASE_URL` / `ZZ_AI_API_KEY` / `ZZ_AI_MODEL` — AI 助手三件套

- **作用**：开启可选 AI 助手（解释风险命中、给科目候选）。三者**全部非空才启用**，缺一即视为关闭，
  所有 AI 方法抛 `AIAssistantError`，绝不静默联网（`ai_assistant.py` 权威守则）。
- **端点要求**：OpenAI 兼容 `/chat/completions`。上游文档验证过的例子：
  NVIDIA 免费 `https://integrate.api.nvidia.com/v1`；OpenRouter；本地 vLLM 同理。
- **模型名示例**（来自 `.env.example`）：`nvidia/nemotron-3-super-120b-a12b-a12b` 形态按所选端点填写。
- **出网边界**：启用后发送的是**已确认结构化字段**（凭证类型/日期/金额/单号/对手方名称/风险摘要/
  证据哈希），不是原始文件全文；完整清单与承诺见 [PRIVACY.md](PRIVACY.md) §AI 边界。
- **留痕**：每次调用记录 prompt 版本、模型、响应哈希、schema 校验结果（model_runs 单机等价物）。
- **安全提示**：
  - API Key 只走环境变量，不入 Git、不写进报告；
  - Key 泄露立即在服务商侧吊销轮换；
  - LLM 输出强制过 schema 校验，失败即降级人工——但 schema 校验**不是零幻觉保证**（LIMITATIONS.md #6），
    科目候选永远只是草稿参考。

---

## 4. 非 env 类配置

| 配置点 | 位置 | 说明 |
|--------|------|------|
| 规则参数 | `rules_builtin.yaml` | 三条 MVP 规则阈值（金额容差 0.01 元、同日重复匹配字段、完整性必填字段）。文件头声明：修改参数=行为变更，须同步 `tests/test_rules.py` 并在 PR 说明 |
| CLI 参数 | `zhanzhen demo [outdir]` / `serve --host --port` / `verify` | 见 [INSTALL.md](INSTALL.md) §3 与 `zhanzhen --help` |
| Web 绑定地址 | `serve --host` | 默认 `127.0.0.1`；无鉴权情况下不建议改 `0.0.0.0` |
| 12 条规则语义 | `zhanzhen/rules12.py` | 从 audit-os engine.py 完整移植，重要性水平自动校准；当前版本无外部参数化入口 |

---

## 5. 三种典型场景的最小配置

```bash
# 场景 A：本机单人使用（pip 安装，零 AI）
export ZZ_DATA_DIR="$HOME/zhanzhen-data"
export ZZ_TENANT_ID="client-a"
zhanzhen serve

# 场景 B：Windows 单机 + 自定义端口
$env:ZZ_DATA_DIR = "D:\zz\data"; $env:ZZ_PORT = "9100"
zhanzhen serve

# 场景 C：Docker + AI 助手（.env 文件）
#   ZZ_DATA_DIR=/data            # 容器内固定，勿改
#   ZZ_PORT=8710                 # 宿主机暴露端口
#   ZZ_TENANT_ID=demo-tenant
#   ZZ_AI_BASE_URL=https://integrate.api.nvidia.com/v1
#   ZZ_AI_API_KEY=nvapi-xxxx     # 只存在于 .env，绝不入库
#   ZZ_AI_MODEL=nvidia/nemotron-3-super-120b-a12b
```

---

## 6. 相关文档

- 安装路径选择与故障排查：[INSTALL.md](INSTALL.md)
- 数据出网边界与删除方式：[PRIVACY.md](PRIVACY.md)
- 安全基线与加固清单：[../dev/SECURITY.md](../dev/SECURITY.md)
- 版本路线（哪些配置项计划中）：[../../VERSIONING.md](../../VERSIONING.md)
