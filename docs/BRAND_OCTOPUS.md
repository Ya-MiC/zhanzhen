# 品牌：湛箴 · OctopusZhen 🐙（品牌备忘录 v2）

> 缘起：创始人选定章鱼为品牌符号（对标 DeepSeek 🐋 鲸鱼、Docker 🐳 的动物 IP 路线），
> 要求与「湛箴 Zhanzhen」谐音融合，且**必须继承 audit-os-mobile v0.3 现有图标的基因**
> （米白圆角底 + 红金三峰山形 + 底部审计对勾——创始人亲自选定的方案）。
> 本文档是定名依据 + 图标设计提示词，AI 生图/设计师可直接引用。

## 一、命名口径 v3（创始人定稿）：正名只有一个——湛箴

> **创始人明确**：产品名字就叫「湛箴」，不需要英文别名。
> 🐙 章鱼 emoji 只是我们的可爱符号，不是名字的一部分。

| 层级 | 写法 | 用途 |
|---|---|---|
| **正名** | **湛箴**（Zhanzhen 拼音仅作技术转写，如包名 `pip install zhanzhen`） | 一切对外场合、UI、文档、商标 |
| 可爱符号 | 🐙 | README 装饰、聊天、社区互动；不进正式名称 |
| **内部代号** | OZ（仅限团队黑话/代码命名空间 `zz.*`） | 不对外宣传、不注册、不进 UI 正式文案 |

历史备注：曾短暂考虑过 OctopusZhen/OCTOZHEN 等英文名，2026-08-24 由创始人否决，
本表取代旧版定名。商标检索只需查「湛箴」。

**谐音逻辑**：Octo**Z**hen 尾音正落在「箴 Zhen」——章鱼(Octopus)+箴(Zhen) 天然连读；
「湛」= 清澈深蓝 = 深海章鱼配色。「箴」= 规谏之言 = 审计的「规」与「证」。
**章鱼八爪 = 八类数据源触达**（账/票/银/税/合同/物流/跨境/AI），每条触腕都在抓证据——
与总纲「Evidence Graph 证据链护城河」同构：**八爪抓证据，一脑管风险。**

## 二、图标基因（继承自 v0.3 现有图标）

现有 audit-os-mobile/dist/icon-512.png 的构成（必须继承）：

| 元素 | 现有方案 | 新章鱼版转译 |
|---|---|---|
| 底色 | 米白 #F5F2EA 圆角方形（黑边框内衬） | 保持米白底+圆角+黑细框 |
| 主形 | **三峰山形**：中央金色 #C9A063 高峰，两侧砖红 #B03A2E 矮峰 | **章鱼头部圆顶 = 中央金峰**；左右两条触腕上扬 = 红色双峰轮廓 |
| 点睛 | 底部黑色对勾（审计语义） | 对勾保留：一条触腕末端自然收笔成勾 |
| 风格 | 极简几何、扁平、无渐变 | 同风格：几何化章鱼，触腕线条如山脊锐利 |

**一句话给设计师**：把三峰山「软化成一只章鱼」——中央峰变头颅，两侧峰变扬起的触腕，
底部对勾不变，红金配色不变，米白底不变。远看仍是三峰山，近看是章鱼。

## 三、生图提示词（Image Prompt）

主提示词（Midjourney/SDXL/DALL·E 通用）：

```
Minimalist flat geometric logo, an octopus whose rounded head forms a tall
central peak and two raised tentacles form two symmetric side peaks (mountain
silhouette hidden in the octopus shape), colors: warm gold #C9A063 for head,
brick red #B03A2E for side tentacles, cream white #F5F2EA background, rounded
square badge with thin dark outline, one bottom tentacle curls into a check
mark, audit-tech style, no text, no gradient, centered, app icon
--v 6 --style raw --no photo, realistic, texture
```

中文要点：
1. 章鱼头颅圆顶 = 原中央金峰（金色 #C9A063）
2. 左右对称两条上扬触腕 = 原两侧红峰（砖红 #B03A2E）
3. 其余触腕收敛为底部弧线，其中一条末端收成**对勾**（黑色 #2B2B2B，继承审计勾）
4. 米白 #F5F2EA 圆角方形底 + 细黑框（同现有）
5. 禁忌：不要写实、不要恐怖触手、不要渐变紫蓝、不要文字

### 负面提示词
```
photo, 3d render, gradient, purple, blue ocean, scary, text, watermark, complex details
```

## 四、应用规范

| 场景 | 用法 |
|---|---|
| README 标题 | `# 🐙 湛箴`（emoji 是符号装饰，名字只有湛箴） |
| CLI banner | v0.2 加入「湛箴」ASCII art |
| 内部代号 | OZ / 命令空间 `zz.*`（仅代码层，不出现在用户界面） |
| 移动端 | audit-os-mobile v0.4 换装新图标（红金基因不变，老用户无感知断层） |


## 五、商标与抄袭风险自查（2026-08-24）

> 本节为工程侧自查笔记，不构成法律意见；正式商业化前请咨询商标代理/律师。

### 结论先行
**代码层面无抄袭风险**：全部原创或移植自自有仓库（audit-os，MIT）；第三方依赖均为宽松协议并已在 ACKNOWLEDGEMENTS.md 致谢；图标提示词源自自家 v0.3 图标基因（本文档第二节即独立创作的书面证据）。

### 品牌风险点（按冲突度排序）

| 风险对象 | 领域 | 冲突度 | 应对 |
|---|---|---|---|
| Octopus Deploy | DevOps 部署软件（澳洲），章鱼logo | 高 | 行业不同（尼斯分类不同类别）+视觉差异大（对方紫蓝写实章鱼 vs 本品红金几何山形章鱼）；保持构图差异即可共存，切勿模仿其造型 |
| 香港八達通 Octopus | 支付交通卡 | 中 | 大中华区「章鱼+金融」联想强；本品使用全称 OctopusZhen 而非裸 Octopus，且行业为审计 SaaS |
| 裸用两字母 "OZ" | 全球大量在先注册（O.Z.轮胎/HBO剧集等） | 低-中 | **OZ 仅作内部昵称与命令空间（zz.*），不作为独立商标申请**；正式标识用 OCTOPUSZHEN + 湛箴 组合 |
| Oz（绿野仙踪） | 影视娱乐 | 极低 | 华纳主要在娱乐类维权，与审计软件类别无关 |

### 待办（商业化前）
- [ ] 中国商标网检索第 9/35/42 类：「OZ」「OCTOPUSZHEN」「湛箴」
- [ ] 无冲突则提交注册申请（官费约 300 元/类/标）
- [ ] AI 生成的图标发布前做反向相似度检查（防生成物意外撞脸现有 logo）
