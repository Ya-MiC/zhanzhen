# 品牌：湛箴 · OctopusZhen 🐙（品牌备忘录 v2）

> 缘起：创始人选定章鱼为品牌符号（对标 DeepSeek 🐋 鲸鱼、Docker 🐳 的动物 IP 路线），
> 要求与「湛箴 Zhanzhen」谐音融合，且**必须继承 audit-os-mobile v0.3 现有图标的基因**
> （米白圆角底 + 红金三峰山形 + 底部审计对勾——创始人亲自选定的方案）。
> 本文档是定名依据 + 图标设计提示词，AI 生图/设计师可直接引用。

## 一、定名：OctopusZhen（缩写 OZ）

| 语言 | 写法 | 读法 | 用途 |
|---|---|---|---|
| 中文 | 湛箴 | zhàn zhēn | 正式产品名 |
| 英文 | **OctopusZhen** | ok-TO-pus-ZHEN | GitHub org / 包名 / 域名 |
| 缩写 | **OZ** | — | logo 主字、命令空间（`zz.*` 已呼应）|
| 拉丁典雅体 | **OCTOZHEN** | — | 印章式变体、徽标环字（类 Opus 的古雅感）|
| 阿拉伯语 | الأخطبوط جانجن | al-ukhtubūt Zhanjen | 跨境版界面备用 |

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
| README 头图 | `# 🐙 湛箴 OctopusZhen` |
| CLI banner | v0.2 加入 `octozhen` ASCII art |
| DSH 命令空间 | 保持 `zz.*`（OZ 双写呼应）|
| 移动端 | audit-os-mobile v0.4 换装新图标（红金基因不变，老用户无感知断层）|
