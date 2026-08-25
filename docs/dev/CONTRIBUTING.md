# 贡献指南（CONTRIBUTING）

> **上游依据**：《ENGINEERING_SPEC》工程规范、[VERSIONING.md](../../VERSIONING.md)、[ARCHITECTURE.md](../../ARCHITECTURE.md)、[docs/DOC_MAP.md](../DOC_MAP.md)、`.github/workflows/ci.yml`。
> **读者**：向本仓库提交代码/文档/测试的贡献者与维护者。
> **文档版本**：v0.1 · 更新日期：2026-08-25 · 状态：已有

---

## 1. 开发环境搭建

```bash
git clone https://github.com/Ya-MiC/zhanzhen.git
cd zhanzhen
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"                              # 含 pytest/httpx + web/excel/pdf extras

pytest -q                                            # 全量测试，预期 43 个全绿
python -m unittest discover -s tests -p "test_*.py"  # 零第三方依赖自检（见 §4）
zhanzhen demo out/                                   # 端到端冒烟
```

要求 Python ≥ 3.10（CI 跑 3.10 与 3.12 双矩阵）。用 uv 的等价流程见
[INSTALL.md](../user/INSTALL.md) 方式二。

目录速览（权威映射表在 ARCHITECTURE.md，此处只列贡献高频触点）：

| 路径 | 内容 | 改动约束 |
|------|------|----------|
| `zhanzhen/canonical.py` `events.py` `state_machine.py` `voucher.py` `journal.py` | 核心域 | **仅标准库**；改语义先立 ADR |
| `zhanzhen/rules.py` / `rules12.py` + `rules_builtin.yaml` | 规则引擎 | 参数改动须同步 `tests/test_rules.py` |
| `zhanzhen/service.py` `webapp.py` `store.py` | 编排/Web/存储 | 错误统一信封；迁移必写事件 |
| `web/index.html` | Vue3 单页 | 无构建链，直接改直接生效 |
| `docs/` | 文档 | 新增/重组须同步 DOC_MAP.md |

---

## 2. 分支约定

- `main`：随时可发布的绿线。只接受 PR 合入，不直接 push。
- 功能分支命名 `<类型>/<短横线摘要>`：`feature/ocr-paddle-adapter`、`fix/review-threshold-clamp`、
  `docs/user-guide`、`tests/rules12-edge-cases`。
- 分支自最新 `main` 切出，生命周期尽量一周内合掉；长期分支先拆里程碑。
- DSH 插件体系在 hermes 仓库的 dsh-plugins 分支维护（DOC_MAP §8），不要混进本仓库。

Commit 信息建议：祈使句首行 ≤ 50 字符 + 空行 + 动机/影响说明；涉及规范语义的引用上游条目
（如 `依 spec/voucher-state-machine-v1.md 第 3 行迁移表`）。仓库暂未强制 conventional commits，
但一旦引入会在此节更新并给出过渡期。

---

## 3. 代码与文档风格

- Python：标准库优先；类型注解齐全；模块 docstring 第一行写清「权威规范出处」
  （现有代码均如此，如 events.py 头部标注 specs/events-v1.md）。
- 不引入强制格式化工具前，保持与现有文件一致的朴素风格；PR diff 里不做无关重排。
- 中文注释/文档为主，代码标识符与错误码英文；文档写作约定（引用块标上游依据、命令可复制、
  交叉引用不复制内容）见 DOC_MAP.md §5 维护规范。

---

## 4. 测试要求（硬性）

CI 两道闸，本地必须都过：

```bash
pytest -q                                           # ① 全量功能测试
python -m unittest discover -s tests -p "test_*.py" # ② 核心域零依赖证明
```

规则：

1. **核心域零第三方依赖是铁律**：canonical / events / state_machine / voucher / journal /
   rules 及其测试只准 import 标准库与新核心模块。第②道闸在没有 pip 包的环境裸跑 tests，
   引入任何三方 import 会当场爆炸。需要新依赖 → 放进对应 extras 并走 ADR（§6）。
2. **新功能必须带测试**：修 bug 附复现测试（先红后绿）；新端点附 service 层或 httpx 层断言；
   规则参数变更同步更新 `tests/test_rules*.py` 并在 PR 说明行为影响面。
3. **测试要确定性**：不联网、不睡时钟、临时目录用 `tempfile.mkdtemp()` 自清理；OCR 一律用
   StubProvider，不依赖 pdfplumber 是否安装。
4. 分层写法与现有 43 个测试的逐项清单见 [TESTING.md](TESTING.md)——写之前先读，
   避免重复造夹具。

---

## 5. PR 流程

1. **Issue 先行**（除错字级小修）：描述动机、复现/验收标准、上游依据链接。
2. 切分支 → 实现 → 本地双闸全绿 → `git push` 到你的 fork 或本仓分支。
3. 开 PR，描述至少包含：

```markdown
### 做了什么 / 为什么
（关联 Issue #N；一句话动机 + 变更点列表）
### 上游依据
（specs 三件套 / 总纲的具体条目链接；无依据的设计变更先补 ADR）
### 测试证据
（粘贴两道闸关键输出：pytest 汇总行 + unittest discover 尾行）
### 影响面自查
- [ ] 未动 specs 契约 / 状态机迁移表 / 事件结构
- [ ] 未改配置默认值（改了则同步 CONFIG.md 与 CHANGELOG）
- [ ] 用户可见变更已记入 docs/user/CHANGELOG.md Unreleased 段
```

4. **Review 检查单**（维护者视角）：
   - [ ] 核心域无新增三方 import
   - [ ] 状态迁移全部走 `assert_transition` 且落事件
   - [ ] 错误走统一信封，无堆栈外泄
   - [ ] 文档/DOC_MAP 与实际行为一致
5. squash 合并入 `main`；合并后 CI 必须绿，红了立即修复或回滚，不允许 main 带病过夜。

常见直接打回的原因：跳过 Issue 的功能 PR、测试只加不断言、为「顺手优化」重排无关代码、
在核心域引入三方依赖、文档与实现口径不一致。

---

## 6. ADR 触发条件

架构决策记录放 `docs/dev/ADR/NNN_<标题>.md`（编号递增，模板：背景 / 决策 / 后果 /
替代方案 / 状态）。**出现下列任一情况必须先立 ADR 再动手**：

| # | 触发条件 | 示例 |
|---|----------|------|
| 1 | 变更 specs 三件套契约（VoucherJSON / 状态机 / 事件结构） | 给事件加必填字段 |
| 2 | 核心域新增运行时依赖 | journal 想引 pydantic |
| 3 | 更换存储引擎或持久化协议 | JSON 快照 → PostgreSQL/RLS |
| 4 | 认证、租户隔离模型变化 | 引入登录/RBAC/多租户 |
| 5 | OCR Provider 选型或降级链策略调整 | 接入 PaddleOCR adapter 正式版 |
| 6 | 规则语义级变化（非阈值参数微调） | 重定义 R-DUP-001 匹配键 |
| 7 | 对外接口兼容性破坏（REST 路径/错误码语义） | 移除 v1 端点 |
| 8 | 打包/发布形态决策 | Windows 绿色版、PyPI 发名 |

已有上游决策可直接引用 action-tree/docs/adr/（如 ADR-001 借贷双列），不必复制重写；
引用时注明「继承自」并在本仓 ADR 里只写增量后果。

---

## 7. Issue 分类建议

| 标签 | 用途 | 响应预期 |
|------|------|----------|
| `bug` | 行为与文档/spec 不符 | 附 trace_id 与最小复现 |
| `enhancement` | 新能力提案 | 先讨论再立项，避免无人认领的大而全 |
| `docs` | 文档错误/缺口 | 小修可直接 PR |
| `question` | 使用咨询 | 优先引导至 FAQ.md |
| `compliance` | 合规边界相关 | 维护者+法务双确认后才能动 |

## 8. 发布检查（维护者）

- [ ] VERSIONING.md 增补版本段；docs/user/CHANGELOG.md 从 Unreleased 定稿
- [ ] 版本号三处一致：pyproject.toml / VERSIONING.md / CHANGELOG
- [ ] `pytest -q` 与零依赖自检在 3.10 & 3.12 绿
- [ ] 打 tag 并在 Release 页粘贴 CHANGELOG 该版本段
- [ ] LIMITATIONS.md 与新能力对齐（删掉已解决的条目而不是留着吓人）

## 9. 行为守则

互相尊重、就事论事；审计与会计专业问题尊重执业者判断；AI 生成的贡献必须在 PR 描述中声明
并由人类复核者担责。许可证：提交即以 MIT 同条款授权（依据 ASSETS_AND_LICENSE.md §6，
暂不强制 CLA）。
