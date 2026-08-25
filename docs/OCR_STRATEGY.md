# OCR 策略与三级降级链设计

> **文档版本**：v0.1  
> **更新日期**：2026-08-25  
> **状态**：草稿（待团队评审）

---

## 1. 设计目标

- **用户体验**：大多数手机用户「无感」完成 OCR（毫秒级，离线，免费）
- **覆盖率**：99%+ 设备可用，老旧/低配机型自动降级
- **数据主权**：**一切信息以用户本人纸质照片 OCR 结果为准**，系统仅给草稿，人工确认生效
- **商业分层**：系统级 OCR 与 PaddleLite 免费；服务端 OCR 为 **专业版** 功能

---

## 2. 三级降级链架构

```
用户拍摄纸质凭证 (jpg / png / pdf)
           │
           ▼
┌──────────────────────────────────────┐
│ ① 系统级 OCR（优先，免费、离线、毫秒级）│
│  - iOS Vision Framework (VNRecognizeTextRequest)  │
│  - Android ML Kit Text Recognition v2 (Google)    │
│  - 华为 HMS ML Kit 文字识别                    │
│  - 小米/OV/一加等厂商相机自带文字提取            │
└──────────────────────────────────────┘
           │ 识别失败 / 置信度 < 阈值 / 设备不支持
           ▼
┌──────────────────────────────────────┐
│ ② PaddleLite 端侧 PP-OCRv4（免费、离线）  │
│  - det + rec 模型共 ~10 MB              │
│  - ARM CPU 推理：中端机单张 1–3 秒      │
│  - 内存占用 < 200 MB                    │
│  - License：Apache-2.0                  │
└──────────────────────────────────────┘
           │ 模型过大 / 设备内存不足 / 推理超时
           ▼
┌──────────────────────────────────────┐
│ ③ 服务端 OCR（专业版功能）             │
│  - 图片上传到工作台服务器跑完整管线      │
│  - PaddleOCR 服务端完整模型（更高精度）   │
│  - 支持批量、高分辨率、复杂版面           │
│  - 需专业版订阅 / OCR 包计费             │
└──────────────────────────────────────┘
           │
           ▼
结构化字段提取 → 对照【分类模板库】自动判凭证类型
(增值税专票 / 普票 / 银行回单 / 费用票 → 对应科目模板 → 序时账草稿)
```

---

## 3. 各方案详细对比

| 维度 | ① 系统级 OCR | ② PaddleLite 端侧 | ③ 服务端 OCR |
|------|--------------|-------------------|--------------|
| **适用平台** | iOS 13+ / Android 7+ / 鸿蒙 | Android 5+ (ARM) / iOS (需编译) | 所有联网设备 |
| **中文支持** | ✅ 原生支持简繁体 | ✅ PP-OCRv4 中文模型 | ✅ 完整模型库 |
| **离线可用** | ✅ 完全离线 | ✅ 完全离线 | ❌ 需联网 |
| **模型大小** | 系统内置 (0 额外) | ~10 MB (det+rec) | 服务端无限制 |
| **推理速度** | < 200 ms | 1–3 秒 (中端机) | 500 ms–2 秒 + 网络 |
| **内存占用** | 系统管理 | < 200 MB | 服务端承担 |
| **License** | 系统 EULA | **Apache-2.0** | 商业服务条款 |
| **维护成本** | 无 | 需打包模型、适配架构 | 服务端运维 |
| **商业分层** | **免费版** | **免费版** | **专业版** |

---

## 4. iOS Vision Framework 详情

- **API**：`VNRecognizeTextRequest` (Vision 框架)
- **中文支持**：iOS 13+ 原生支持简体/繁体中文
- **识别模式**：`fast` (实时) / `accurate` (高精度，默认)
- **语言提示**：`recognitionLanguages = ["zh-Hans", "zh-Hant"]`
- **输出**：`VNRecognizedTextObservation` → `topCandidates(1).first?.string`
- **置信度**：`candidate.confidence` (0–1)
- **优势**：零依赖、系统级优化、电池友好、隐私优先（全设备端）
- **局限**：旧设备 (iOS <13) 不可用；复杂版面/手写体准确率受限

---

## 5. Android ML Kit Text Recognition v2 详情

- **库**：`com.google.mlkit:text-recognition-chinese` (v2)
- **分发**：Google Play Services 动态下载 (~10–15 MB 首次) 或打包静态库 (~30 MB)
- **中文支持**：简体/繁体/数字/符号
- **API**：`TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)`
- **输入**：`InputImage.fromBitmap(bitmap, rotationDegrees)`
- **输出**：`Text.TextBlock` → `Text.Line` → `Text.Element`
- **置信度**：无直接置信度，需自行启发式判断
- **优势**：Google 维护、模型自动更新、免费、离线可用
- **局限**：国内设备无 GMS 需打包静态库；华为设备建议优先 HMS

---

## 6. 华为 HMS ML Kit / 国产厂商方案

| 厂商 | Kit 名称 | 中文支持 | 备注 |
|------|----------|----------|------|
| **华为** | HMS ML Kit Text Recognition | ✅ 简繁体 | 需集成 HMS Core SDK，国内覆盖率高 |
| **小米** | MIUI 系统相机/相册文字提取 | ✅ | 通过 Intent 调用系统能力 |
| **OPPO/vivo** | 相机/相册/备忘录文字识别 | ✅ | ColorOS/FuntouchOS 系统级 |
| **荣耀** | MagicOS 文字识别 | ✅ | 同 HMS 体系 |

**策略**：运行时检测设备厂商 (`Build.BRAND`)，优先调用对应系统能力；无系统能力回退 ML Kit。

---

## 7. PaddleLite 移动端部署方案

- **模型**：PP-OCRv4 `ch_PP-OCRv4_det_infer` + `ch_PP-OCRv4_rec_infer`
- **转换**：Paddle Inference → PaddleLite (`paddle_lite_opt` 工具)
- **模型大小**：det ~3.5 MB + rec ~6.5 MB = **~10 MB 总计**
- **目标架构**：ARMv8 (arm64-v8a) / ARMv7 (armeabi-v7a)
- **推理引擎**：PaddleLite C++ API → JNI 桥接 Kotlin/Swift
- **预处理**：短边缩放到 960、归一化 (mean=0.5, std=0.5)
- **后处理**：DB 文本检测 + CTC 识别解码
- **性能参考**（骁龙 778G / 天玑 1080 级）：
  - 单张 A4 凭证：det 400–800 ms + rec 600–1200 ms = **1–2 秒**
  - 内存峰值：~150 MB
- **License**：**Apache-2.0**（模型与推理引擎均为 Apache-2.0）
- **打包策略**：
  - Android: `assets/models/` + `jniLibs/arm64-v8a/libpaddle_lite_jni.so`
  - iOS: `Frameworks/PaddleLite.framework` + 模型进主包

---

## 8. RapidOCR / ONNX Runtime Mobile 可行性评估

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| **RapidOCR (Python)** | 纯 Python、ONNX 统一、易部署 | 移动端需 Python 运行时，包体大 | ❌ 不适合原生 App |
| **RapidOCR-ONNX (C++)** | C++ 实现、ONNX Runtime Mobile | 需自行移植后处理、维护成本高 | ⚠️ 备选，非首选 |
| **ONNX Runtime Mobile + 自建模型** | 跨平台、模型通用 | 需导出 PP-OCR 为 ONNX、适配预后处理 | ⚠️ 远期考虑 |

**结论**：PaddleLite 是官方推荐移动端部署路径，生态最成熟，**作为主选端侧方案**；ONNX Runtime 作为长期技术储备。

---

## 9. License 汇总表

| 组件 | License | 商业影响 |
|------|---------|----------|
| iOS Vision Framework | Apple EULA | 免费随系统，无额外义务 |
| Android ML Kit (Google) | Apache-2.0 (库) + Google ToS | 免费，需遵守 Google Play Services 条款 |
| 华为 HMS ML Kit | 华为开发者协议 | 免费，需注册华为开发者账号 |
| **PaddleLite / PP-OCRv4 模型** | **Apache-2.0** | ✅ 可商用、可修改、可分发、无传染性 |
| pdfplumber / pypdf | MIT / BSD-3 | 无限制 |
| **湛箴核心代码** | **MIT** | 保持开源获客 |

> **关键点**：全链路 **无 GPL/AGPL/LGPL 传染性协议**，完全兼容「引擎 MIT + 商业模板闭源」双轨模式。

---

## 10. 实现接口规范（供客户端/服务端实现）

```typescript
// 统一 OCR 调用接口
interface OCRRequest {
  imageBase64: string;        // 图片 base64 (jpg/png) 或 PDF base64
  mimeType: 'image/jpeg' | 'image/png' | 'application/pdf';
  options?: {
    preferEngine?: 'system' | 'paddlelite' | 'server'; // 强制指定引擎（调试用）
    lang?: 'ch' | 'en' | 'auto';
    voucherTypeHint?: string; // 凭证类型提示，辅助后处理
  };
}

interface OCRResponse {
  engineUsed: 'ios-vision' | 'android-mlkit' | 'hms' | 'paddlelite' | 'server-paddleocr';
  voucherJson: VoucherJSON;   // 标准 VoucherJSON v1
  confidence: number;         // 0–1 总体置信度
  needsHumanReview: boolean;  // 是否需人工复核
  fallbackChain: string[];    // 实际走过的降级链，如 ["ios-vision"]
  processingTimeMs: number;
  errorCode?: string;         // 如 "no_text_layer_needs_ocr"
}
```

---

## 11. 落地检查清单

- [ ] Android: `build.gradle` 集成 ML Kit 中文库 + HMS 可选依赖
- [ ] iOS: Vision Framework 调用封装 `OCRService.swift`
- [ ] PaddleLite: 模型转换脚本 + Android/iOS JNI/桥接代码
- [ ] 降级链调度器：`OCRManager.tryRecognize(image) → OCRResponse`
- [ ] 置信度阈值配置：系统级 < 0.7 降级、PaddleLite < 0.6 降级
- [ ] 服务端 OCR Worker：`ocr_worker.py` 接入完整 PaddleOCR
- [ ] 专业版权限校验：服务端 OCR 需验证订阅状态
- [ ] 埋点上报：各引擎成功率、耗时、降级率 → 产品迭代依据

---

## 12. 相关文档

- `docs/PRODUCT_TIERS.md` — 免费/专业版功能切分（服务端 OCR 为专业版）
- `docs/MOBILE_WORKFLOW.md` — 手机拍照 → 工作台全流程
- `docs/ASSETS_AND_LICENSE.md` — 资产分层与协议（OCR 模型归属）
- `zhanzhen/ocr.py` — 现有 Provider 架构（TextLayerPDFProvider / StubProvider / PaddleOCRProvider 预留）