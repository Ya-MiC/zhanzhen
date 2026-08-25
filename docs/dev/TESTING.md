# 测试策略与清单（TESTING）

> **上游依据**：`tests/` 全部 8 个文件（43 个测试，逐一点名见 §4）、`.github/workflows/ci.yml`、ENGINEERING_SPEC §11 验收语义、[LIMITATIONS.md](../../LIMITATIONS.md) #10（金标数据集）、[VERSIONING.md](../../VERSIONING.md)（评估里程碑）。
> **读者**：为本仓库写测试、跑测试、做 OCR/规则效果评估的贡献者与 QA。
> **文档版本**：v0.1 · 更新日期：2026-08-25 · 状态：已有

---

## 1. 测试分层策略

```
L3  端到端管线   test_pipeline.py     —— demo 账套全流程 + 哈希链完整性
L2  规则引擎     test_rules.py        —— 三条 MVP 规则语义
                 test_rules12.py      —— 12 条完整规则 + 材料性校准
L1  服务编排     test_journal.py 等   —— AuditService 编排下的域行为
L0  核心域单元   test_canonical.py    —— 纯函数、零依赖
                 test_events.py
                 test_state_machine.py
LX  横切         test_capture.py      —— 手机采集包入库/风格样本往返
```

| 层 | 对象 | 依赖 | 失败意味着 |
|----|------|------|------------|
| L0 | canonical/events/state_machine/voucher 纯函数 | 仅标准库 | 契约坏了，一切上层结论不可信 |
| L1 | 域对象在服务编排中的约束 | 仅标准库 + StubProvider | 业务不变量失守（平衡/不可变） |
| L2 | 规则判定与参数 | 标准 + PyYAML | 误报/漏报，审计质量直接受损 |
| L3 | ingest→OCR→review→journal→rules→export 全链 | tmp 目录 + Stub | 用户可感知流程断裂 |
| LX | 跨模块契约（采集包、风格样本） | tmp 目录 | 对外接口漂移 |

**金字塔取向**：当前 43 个测试里 L0+L1+L2 占绝大多数，L3 只有 4 个但覆盖最贵路径——
这是刻意的：核心语义便宜且必须穷尽，端到端贵而精。

**尚未覆盖、诚实在案**：

- Web 层（webapp.py）无独立 API 测试；httpx 已在 dev extras 里预留，
  计划用 FastAPI TestClient 补端点级断言（错误信封、状态码 400/409/404）。
- 无覆盖率门槛建制（不跑 coverage 报告）；以「核心域逐函数有测试」为纪律替代。
- 并发写入场景未测（存储层本身未加锁，LIMITATIONS.md #3）。

---

## 2. 两道 CI 闸门

```bash
pytest -q                                           # ① 功能全量
python -m unittest discover -s tests -p "test_*.py" # ② 核心零依赖证明
```

- ①在装好 `[dev]` 的环境验证全部行为；
- ②在**同一份 tests 源码**上裸跑（CI 步骤名 stdlib-only guarantee）：若有人往核心域或其
  测试里 import 了三方包，这一步当场失败。这是「核心域零依赖」承诺的机械化执行，
  也是 CONTRIBUTING.md §4 的依据。
- 本地开发请两条都跑；只绿 ① 不算过。

---

## 3. 写测试的约定

- unittest 风格（现有全部如此），pytest 只作 runner；新测试放对应主题文件，勿另起炉灶。
- OCR 相关一律 `provider_name="stub"`：StubProvider 按 `键=值` 行确定性解析
  （date=/incl=/excl=/tax=/counterparty=/docno=），永不联网。
- 数据落 `tempfile.mkdtemp()` 的临时目录，测试自清理，互不串扰。
- 断言业务语义而非实现细节：断「确认后 entries 状态为 reversed 且红字平衡」，
  而非断某内部 dict 的键顺序。
- 哈希链类断言先 `verify_chain()` 再看错误列表内容。

---

## 4. 现有 43 个测试逐项清单

> 用途：改代码前定位必须保持绿色的行为锚点；评审时核对影响面。
> 数量口径：`def test_*` 计数，与 CI 绿线一致（canonical 6 / capture 2 / events 4 /
> journal 7 / pipeline 4 / rules 5 / rules12 10 / state_machine 5 = **43**）。

### tests/test_canonical.py（6）— Canonical JSON 是全链唯一哈希底座

| 测试 | 锚定的行为 |
|------|------------|
| test_key_order_is_byte_sorted_recursive | 嵌套 dict 键名按字节序递归排序 |
| test_no_whitespace | 序列化无任何空白字节 |
| test_hash_stable_across_insertion_order | 插入顺序不同 → 哈希相同 |
| test_float_int_distinct | `1.0` 与 `1` 哈希必须不同 |
| test_nan_rejected | NaN 直接拒绝（审计数字不允许「不是数」） |
| test_unicode_not_escaped | 中文原样输出，不做 \\u 转义 |

### tests/test_events.py（4）— append-only 与防篡改

| 测试 | 锚定的行为 |
|------|------------|
| test_append_builds_chain | 追加即成链：sequence 递增 + previous_event_hash 正确 |
| test_tamper_detection | 改历史事件任意字段 → verify_chain 报错 |
| test_sequence_gap_detected | 同聚合序号出现空洞 → 校验失败 |
| test_unknown_aggregate_rejected | 未登记聚合类型的事件被拒 |

### tests/test_state_machine.py（5）— 12 态迁移表

| 测试 | 锚定的行为 |
|------|------------|
| test_happy_path_full_lifecycle | 全生命周期合法走通 |
| test_review_branches | OCR 完成 → NEEDS_REVIEW/REVIEWED 双分支均合法 |
| test_illegal_shortcuts_blocked | 跨级抄近道抛 InvalidTransition |
| test_confirmed_cannot_go_back_to_draft | 已确认分录禁止回退（只能冲销） |
| test_all_states_have_entries | 12 态都在迁移表内登记，无孤儿态 |

### tests/test_journal.py（7）— 分录硬约束

| 测试 | 锚定的行为 |
|------|------------|
| test_unbalanced_rejected_at_construction | 构造期即拒绝借贷不平 |
| test_line_debit_credit_both_set_rejected | 单行同时有借贷被拒 |
| test_negative_rejected | 负数金额被拒（负向走红字冲销语义） |
| test_lines_hash_stable_and_sensitive | lines_hash 稳定且对行内容敏感（锁行依据） |
| test_vat_invoice_suggestion_balances | 增值税发票科目模板建议天然平衡 |
| test_unknown_type_returns_none_not_guess | 未知凭证类型返回 None，绝不瞎猜科目 |
| test_missing_amount_returns_none | 缺金额不出建议 |

### tests/test_rules.py（5）— 三条 MVP 规则

| 测试 | 锚定的行为 |
|------|------------|
| test_balanced_triangle_passes | 含税=未税+税额 → R-AMT-001 沉默 |
| test_unbalanced_triangle_hits | 三角不平 → R-AMT-001 high |
| test_same_date_cp_amount_flags_second | 同日同对手方同金额第二张 → R-DUP-001 |
| test_different_dates_no_hit | 不同日不误报重复 |
| test_missing_fields_flagged | 缺必填字段 → R-CMP-001 high |

### tests/test_rules12.py（10）— 完整规则引擎（audit-os 移植）

| 测试 | 锚定的行为 |
|------|------------|
| test_materiality_auto_calibration | 重要性水平自动校准存在且合理 |
| test_materiality_scales_with_revenue | 重要性随营收规模缩放 |
| test_r001_period_end_spike | R-001 期末突击收入命中 |
| test_r002_large_amount | R-002 大额支出命中 |
| test_r003_direction_violations | R-003 方向异常命中 |
| test_r006_counterparty_offset | R-006 关联方对挂命中 |
| test_r011_repeat_transactions | R-011 重复交易命中 |
| test_r012_roundtrip | R-012 短期资金往返命中 |
| test_rule_isolation_on_bad_data | 单条规则遇坏数据隔离报错，不拖垮其余规则 |
| test_severity_ladder | severity 分级输出正确 |

### tests/test_pipeline.py（4）— 端到端

| 测试 | 锚定的行为 |
|------|------------|
| test_e2e_demo_book_produces_expected_findings | demo 六张账套：006 必进覆核、002/004 重复命中、导出双格式落盘、全程链完整 |
| test_cannot_confirm_before_review | 未覆核不得做账（InvalidTransition） |
| test_empty_file_rejected | 空文件拒绝入库 |
| test_reverse_creates_balanced_red_letter | 红字冲销生成平衡反向分录并关联原件 |

### tests/test_capture.py（2）— 横切契约

| 测试 | 锚定的行为 |
|------|------------|
| test_capture_pack_ingest_recomputes_hash | 采集包入库由服务端重算 SHA-256（不信客户端） |
| test_style_sample_roundtrip | 报告风格样本存取往返一致 |

---

## 5. 金标评估方法（OCR/规则效果验收）

> 背景：单测证明的是「逻辑正确」；金标评估证明的是「识别与判断的质量达标」。
> spec 要求每类凭证 ≥30 张去敏真实样本，而数据集目前为空（LIMITATIONS.md #10，
> 只能由人提供）。v0.2.0-alpha 计划落地 90 张框架 + 字段级评估脚本（VERSIONING.md）。

**数据集要求**

- 三类起步：数电发票 / 银行回单 / 费用票，每类 ≥30 张，全部去敏（金额可保真、
  名称税号打码需同步改金标字段）；
- 每张样本配人工录入的 VoucherJSON 金标（ground truth），与预测同 schema 才可比；
- 划分固定 train/eval，eval 集冻结，防止调参泄漏。

**指标定义**

| 指标 | 口径 |
|------|------|
| 字段准确率 | 逐字段比对 `transaction.date / amount_incl_tax / tax_amount / amount_excl_tax / document_no / counterparty.name`，金额按 0.01 元容差判对 |
| needs_human_review 召回率 | 金标标注「难样本」中被系统正确拦进 NEEDS_REVIEW 的比例（漏拦=机器自信地错，代价最高） |
| 规则误报率 | eval 账套中人工判定「误报」的 finding / 全部 finding |
| 规则召回 | 人造已知异常（重复对、三角不平）被命中的比例 |
| 处理时长 | 单张端到端 ms（OCR+规则），对应 v1.0 M0 出口门槛之一 |

**验收挂钩**（VERSIONING.md 路线）：v0.2.0-alpha 出脚本与框架；v1.0.0 以 50–100 张
真实去敏凭证的「字段准确率 / 误报率 / 处理时长」三达标作为 M0 出口条件。
评估结果写进 Release 说明，不入库原始样本（隐私红线见 PRIVACY.md）。

---

## 6. 快速命令速查

```bash
pytest -q                                   # 全量
pytest tests/test_rules12.py -q             # 单文件
python -m unittest discover -s tests -p "test_*.py" -v   # 零依赖自检（CI 同款）
zhanzhen demo out/                          # 冒烟：测试之外的最后一道人眼检查
```
