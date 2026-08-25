# 安装指南（INSTALL）

> **上游依据**：[README.md](../../README.md)「快速开始」、`pyproject.toml`（extras 定义）、`Dockerfile` / `docker-compose.yml`、`zhanzhen/cli.py`。
> **读者**：第一次把湛箴跑起来的会计师、审计助理与运维人员。
> **目标**：从零到「打开第一份可追溯 HTML 报告」不超过 10 分钟。
> **文档版本**：v0.1 · 更新日期：2026-08-25 · 状态：已有

---

## 0. 系统要求

| 项目 | 要求 | 说明 |
|------|------|------|
| Python | ≥ 3.10 | CI 矩阵在 3.10 与 3.12 上验证；3.9 及以下不支持 |
| 操作系统 | Windows 10+ / Linux / macOS | 核心域纯标准库实现，跨平台无差别 |
| pip | 随 Python 附带 | 建议升级到 23+：`python -m pip install -U pip` |
| Docker（可选） | Docker Engine 20+ 与 Compose v2 | 只有用方式三才需要 |
| 磁盘 | 核心 < 20 MB；装 `[ocr]` 另需 ~2 GB | PaddleOCR 模型较大，见 §2 |
| 网络 | 安装时需要；运行时不需要 | 运行期唯一出网场景见 [PRIVACY.md](PRIVACY.md) |

核心包的强制依赖只有 `pydantic>=2.5` 与 `PyYAML>=6.0`（见 `pyproject.toml`）；
Web 服务、Excel 导出、PDF 解析等能力按需通过 extras 安装，见 [§2 extras 说明](#2-extras-说明)。

---

## 1. 三种安装方式

### 方式一：pip 直装（推荐普通用户）

```bash
# 只装核心 + CLI（demo / verify 可用）
pip install git+https://github.com/Ya-MiC/zhanzhen.git

# 推荐：连 Web 工作台一起装（serve 需要）
pip install "zhanzhen[all] @ git+https://github.com/Ya-MiC/zhanzhen.git"
```

> ⚠️ 直接 `pip install git+...` **只安装核心依赖**。此时 `zhanzhen demo` 与
> `zhanzhen verify` 完全可用，但 `zhanzhen serve` 会提示
> 「需要安装 Web 依赖: pip install 'zhanzhen[web]'」。要一次装齐请用上面的
> `zhanzhen[all] @ git+...` 写法。

Windows 用户注意：命令中的引号必须用双引号（PowerShell 与 cmd 均适用）：

```powershell
pip install "zhanzhen[all] @ git+https://github.com/Ya-MiC/zhanzhen.git"
```

国内网络慢可追加镜像源参数：

```bash
pip install "zhanzhen[all] @ git+https://github.com/Ya-MiC/zhanzhen.git" \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

装完先跑一键演示验证：

```bash
zhanzhen demo ./zz-demo-out        # Windows 同样可用相对路径
```

预期输出六步（载入示例账套 → 覆核 → 分录 → 规则 → 导出 → 链校验 ✔），最后打印报告路径。
用浏览器打开 `./zz-demo-out/report.html` 即完成首次验证。

### 方式二：源码开发

```bash
git clone https://github.com/Ya-MiC/zhanzhen.git
cd zhanzhen

# 标准 venv 方式
python -m venv .venv
source .venv/bin/activate           # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

pytest -q                           # 43 个测试应全绿
python -m unittest discover -s tests -p "test_*.py"   # 核心域零第三方依赖自检（CI 同款）
zhanzhen demo out/
```

使用 uv 的等价流程（可选，更快）：

```bash
uv venv
uv pip install -e ".[dev]"
uv run pytest -q
```

源码方式适合：改代码、跑测试、看 `zhanzhen/` 内部实现。贡献流程见
[CONTRIBUTING.md](../dev/CONTRIBUTING.md)。

### 方式三：Docker / Docker Compose

```bash
git clone https://github.com/Ya-MiC/zhanzhen.git
cd zhanzhen
cp .env.example .env                # 至少保留 ZZ_DATA_DIR/ZZ_PORT 两行
docker compose up --build -d
docker compose logs -f              # 看到 "Uvicorn running on ..." 即成功
```

打开 `http://localhost:8710` 进入 Web 工作台。

要点说明（对应 `Dockerfile` / `docker-compose.yml` 的真实行为）：

- 数据卷：宿主机 `./data` ↔ 容器 `/data`（容器内 `ENV ZZ_DATA_DIR=/data`）。删除该目录=删库，操作前先备份。
- 端口映射规则是 `${ZZ_PORT:-8710}:8710`——**改 `.env` 里的 `ZZ_PORT` 只会改宿主机端口**，
  容器内部永远监听 8710。详见 [CONFIG.md](CONFIG.md) 的 ZZ_PORT 条目。
- 停止与清理：

```bash
docker compose down                 # 停止（数据保留）
docker compose down && rm -rf data  # 彻底删除（含全部凭证数据，慎用）
```

---

## 2. extras 说明

`pyproject.toml` 定义的可选依赖组，按需安装：

| extra | 包含 | 什么时候需要 | 备注 |
|-------|------|--------------|------|
| （无 extra） | pydantic、PyYAML | 只要 CLI demo / verify / 二次开发核心域 | 核心测试零外部依赖 |
| `web` | fastapi、uvicorn\[standard\]、python-multipart | `zhanzhen serve` / Docker 镜像 | Web 工作台必需 |
| `excel` | openpyxl | 序时账导出 XLSX | 不装则**自动降级 CSV**，不算故障（见 FAQ） |
| `pdf` | pdfplumber、pypdf | 上传 PDF 提取文本层 | 文字型 PDF 必备；扫描件另见 `[ocr]` |
| `ocr` | paddleocr、paddlepaddle | 图片/扫描件识别 | 体积约 2 GB；v0.1.0 探测位已留、adapter 在 Week3 提供（诚实声明见 LIMITATIONS.md #1） |
| `report` | jinja2、weasyprint、python-docx、docxtpl、matplotlib | 为 PDF/Word 模板导出预留 | v0.5-beta 计划项，当前版本装了也不影响现有 HTML 报告 |
| `all` | = web + excel + pdf | 普通用户一步到位 | **推荐**；不含体积大的 ocr |
| `dev` | pytest、httpx + all | 贡献者/开发者 | 含运行全部测试所需 |

组合示例：

```bash
pip install "zhanzhen[web,excel,pdf] @ git+https://github.com/Ya-MiC/zhanzhen.git"
```

---

## 3. 安装后验证清单

逐条执行，全部通过即安装成功：

1. **CLI 存在**

```bash
zhanzhen --help
# 应看到三个子命令：demo / serve / verify
```

2. **一键演示全链路**

```bash
zhanzhen demo ./zz-demo-out
```

预期最后两行形如：

```
== 6. 证据链校验 == ✔ 完整
打开报告查看: /绝对路径/zz-demo-out/report.html
```

注意：第 3 步打印的 `[跳过] …` 属于正常行为——示例账套故意含一张三角不平的坏凭证，
用于演示质量门拦截，不是安装问题（原理见 FAQ）。

3. **事件链独立校验**

```bash
cd ./zz-demo-out/data && zhanzhen verify    # 或设置 ZZ_DATA_DIR 后直接执行
# 预期：✔ N 条事件，链完整；退出码 0
```

`verify` 退出码约定：`0`=链完整，`1`=未找到快照，`2`=链损坏（对应 `cli.py` 实现）。

4. **Web 工作台**（仅当装了 `[web]`）

```bash
zhanzhen serve                      # 默认 http://127.0.0.1:8710
```

页面顶部五个页签：凭证箱 / 覆核 / 分录 / 风险 / 报告；右上角出现
「事件链: ✔ 完整」即后端正常。操作教学见 [USER_GUIDE.md](USER_GUIDE.md)。

---

## 4. 升级与卸载

```bash
# pip 方式升级到最新 main
pip install --upgrade "zhanzhen[all] @ git+https://github.com/Ya-MiC/zhanzhen.git"

# Docker 方式升级
git pull && docker compose up --build -d

# 卸载（数据不会被动删除，需自行决定）
pip uninstall zhanzhen
rm -rf .zzdata          # ← 你的全部凭证/分录/事件快照都在这里，删前确认不再需要
```

版本语义与发布节奏见根目录 [VERSIONING.md](../../VERSIONING.md)；每个版本的用户可见变更
记录在 [CHANGELOG.md](CHANGELOG.md)。

---

## 5. 故障排查（按症状索引）

| 症状 | 原因 | 处理 |
|------|------|------|
| `zhanzhen serve` 输出「需要安装 Web 依赖」 | 未装 `[web]` extra | `pip install "zhanzhen[web]"` |
| 浏览器打不开 8710 | 端口被占用或绑定了 127.0.0.1 远端访问 | `zhanzhen serve --port 9000` 换端口；远程访问务必走反代+鉴权（MVP 无登录） |
| `ModuleNotFoundError: No module named 'pdfplumber'` | 未装 `[pdf]` extra | `pip install "zhanzhen[pdf]"` |
| OCR 结果报 `no_text_layer_needs_ocr` | 扫描件/图片没有文本层，程序诚实拒绝而非编数据 | 换文字型 PDF，或关注 v0.2.0-alpha 的 PaddleOCR adapter（LIMITATIONS.md #1） |
| 装 `[ocr]` 后仍提示 adapter 将在 Week3 提供 | v0.1.0 只有探测位 | 属实且已在文档声明；先用 PDF 文本层 |
| 序时账导出得到 CSV 而非 XLSX | 未装 openpyxl 的自动降级 | `pip install "zhanzhen[excel]"`；CSV 本身可用 |
| `pip install` 超时/反复重试 | 网络/防火墙 | 加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`，或配置代理后重试 |
| PowerShell 提示「在此系统上禁止运行脚本」 | 执行策略限制 | 以管理员执行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 后再激活 venv |
| Docker 起不来：端口冲突 | 宿主 8710 已被占 | `.env` 中改 `ZZ_PORT=9000` 后 `docker compose up -d` |
| Docker 内写不进 `/data` | 宿主目录权限 | `sudo chown -R $(id -u):$(id -g) ./data` 或调整卷挂载 |
| `zhanzhen verify` 退出码 1 | 当前目录/环境变量下找不到快照 | 设置正确的 `ZZ_DATA_DIR` 与 `ZZ_TENANT_ID`（见 CONFIG.md） |
| `zhanzhen verify` 退出码 2 并列出错误 | 事件链校验失败，快照可能被手工改过 | **不要**继续作业；对照 FAQ「事件链损坏」一节处理 |

更多真实问题按分类检索 [FAQ.md](FAQ.md)；报错码统一信封 `{code, message, details, trace_id}`
的完整定义随 API 文档（docs/specs/API_CONTRACT_V1.md，待写）发布。

---

## 6. 下一步

- 第一次正式作业：跟着 [USER_GUIDE.md](USER_GUIDE.md) 从「上传」走到「导出」。
- 手机拍照采集：先读 [MOBILE_WORKFLOW.md](../MOBILE_WORKFLOW.md)，再用
  [MOBILE_WORKFLOW_CHECKLIST.md](../MOBILE_WORKFLOW_CHECKLIST.md) 逐项打勾。
- 配置项逐条解释（端口/租户/覆核阈值/AI 开关）：[CONFIG.md](CONFIG.md)。
