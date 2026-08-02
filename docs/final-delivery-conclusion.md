# MOMO Scholar 最终交付结论（保守版）

本文是独立的最终陈述与简历证据清单，不替代
[最终交付记录](final-delivery.md)、任何评测 manifest 或报告。下列结论只使用已经
冻结的 Retrieval、Citation generation 和 Stage 4 离线验收证据；Citation 质量
结论必须从文末两个互斥小节中选择一个回填。生成成功不等于 Citation 质量通过。

## Completion matrix

| 交付项 | 状态 | 可公开的结论 | Authority |
|---|---|---|---|
| Stage 4 bundled offline Web demo | **PASS** | 后端 `17 passed`、前端 `18 passed`；desktop 与 390 px narrow browser smoke 通过，console errors 为 `0` | `docs/final-delivery.md`（PR #76，merge commit `114cbe0`；验收基线 commit `c0b1beed41c7759dea168766783bc39237a76646`） |
| Retrieval 40-case authority | **PASS** | Hybrid Recall@8 `1.0`、Vector `1.0`、Keyword `.95`、Hybrid-Keyword `+.05`，bootstrap 95% CI `[0, .125]`，`0/40` failures | `C:\Users\86150\.codex\worktrees\90e3\MOMO-Scholar\evaluations\experiments\momo-scholar-retrieval-validation-40-e63b756-live\artifact-manifest.json`；SHA-256 `97ab76791b059ec78fea6f284b5c0d2f87be093a58b8978507853ca013fa3f55` |
| Citation generation authority | **PASS** | `20/20` generation success、`20` provider sends、`0` retries、`19,472` tokens、历史估算成本 CNY `0.054478` | `C:\Users\86150\.codex\worktrees\870c\MOMO-Scholar\evaluations\experiments\citation-task8-20case-49e342b-generation-authority\package-manifest.json`；SHA-256 `72683899d8db7eadd57c29e462b5c32e3e9e9bc1690361803038ca6df9a8a21d`；聚合输出 `citation-task8-20case-49e342b-live\pipeline-outputs.jsonl` SHA-256 `05ad82a7ad2dcb27900bb82877f07f09ed556a1092128cbeab7744f3275a0541` |

Stage 4 是 synthetic、offline 的产品演示验收，不是检索或 Citation 质量基准。
Citation 成本是已经发生的 generation 历史估算，不授权任何新调用。本次文档交付
没有调用 provider，也没有产生费用。

## Citation quality judgment：二选一最终回填

交付时必须仅保留下面 A 或 B 的一个结果小节，删除另一个。任何字段都不得用
generation success、Retrieval 指标或 demo 观察代填。

### A. 若 Citation quality authority 成功出现

> **待最终 authority 回填；当前不得作为已验证结论发布。**

| 必填字段 | 最终值 |
|---|---|
| Citation Coverage（分子/分母、点估计、CI） | `PENDING_FROM_VERIFIED_CITATION_AUTHORITY` |
| Citation Validity（分子/分母、点估计、CI） | `PENDING_FROM_VERIFIED_CITATION_AUTHORITY` |
| Unsupported Assertion Rate（分子/分母、点估计、CI） | `PENDING_FROM_VERIFIED_CITATION_AUTHORITY` |
| 方法标签与限制 | `PENDING_EXACT_METHOD_AND_LIMITATIONS` |
| Citation package 绝对路径与 manifest SHA-256 | `PENDING_VERIFIED_PATH_AND_HASH` |
| 离线 verifier 命令及 PASS 输出 | `PENDING_EXACT_COMMAND_AND_RESULT` |
| final 60-case manifest 绝对路径与 SHA-256 | `PENDING_VERIFIED_PATH_AND_HASH` |
| Retrieval/Citation compatibility 检查及 PASS 输出 | `PENDING_EXACT_COMMAND_AND_RESULT` |

来源要求：所有指标、分母、区间、失败数和方法标签必须逐字来自 sealed Citation
report/manifest；必须离线重算 manifest hash 并运行对应 verifier；只有 final 60-case
assembler 生成并验证兼容 manifest 后，才可写“verified 60-case”。若其中任一步不满足，
不得保留本小节，改用 B。

### B. 若 Citation quality authority 失败

**Citation quality：BLOCKED BY PROVIDER COMPATIBILITY。** Citation generation
authority 已完成，但质量判断未形成可验证 authority；Citation Coverage、Citation
Validity、Unsupported Assertion Rate、相应分母与置信区间均为 **unavailable**。
不得从生成成功率推断质量，也不得宣称“verified 60-case”。final 60-case package
未获验证，因为 verified Citation 20 quality authority 是其必要输入。

最终回填时应追加且只能追加失败 authority 的绝对路径、manifest SHA-256、离线
verifier/诊断结果和零/实际 provider 调用边界；不得把 reservation、预算上限或失败
attempt 表述为有效 judgment。

## 可直接用于简历的中文描述

- 构建可审计的混合检索评测链路，在 40-case 冻结基准上实现 Hybrid Recall@8
  `1.0`，相对 Keyword 提升 `0.05`（bootstrap 95% CI `[0, 0.125]`），并保持
  `0/40` failures。
- 完成 20-case Citation 生成 authority 的可恢复执行与封存：`20/20` 成功、`20`
  次发送、`0` 重试、共 `19,472` tokens，历史估算成本 CNY `0.054478`；输出与
  manifest 均以 SHA-256 固化。
- 交付 Stage 4 本地离线 Web demo，打通报告、论文分析、Evidence 与 allowlisted
  artifacts 浏览链路；后端 `17` 项、前端 `18` 项 focused tests 通过，desktop/390 px
  smoke 均无 console error。

这些描述故意不包含 Citation quality 分数、真实 Web provider E2E 或 verified 60-case
声明；只有 A 小节全部验证后，才能另行增加对应结果。

## 3–5 分钟最短演示讲解

1. **0:00–0:30，边界。** 打开 bundled offline demo，先说明它是 synthetic 本地
   产品验收，不是论文结论或质量 benchmark，浏览过程零 provider 调用。
2. **0:30–1:30，完整链路。** 展示 completed-with-degradation 状态、报告 checked
   view、论文分析与 Evidence；指出 quote、paper/chunk、score、source mode 和未知
   page/section 都按实际 provenance 呈现。
3. **1:30–2:20，可移植证据。** 展示八类 allowlisted artifacts 下载入口，解释
   manifest/hash 如何让产物可核查，并强调 Web registry 只做投影，不重写研究 authority。
4. **2:20–3:20，已验证指标。** 展示本页 completion matrix：Retrieval 40 的三路
   Recall@8 与 CI，以及 Citation generation 的成功数、发送数、token 与历史成本。
5. **3:20–4:00，诚实止损。** 展示最终选定的 Citation quality 小节。若没有 verified
   authority，就明确说 provider compatibility blocked、指标 unavailable、不能宣称
   verified 60-case；不现场重跑、不调用 provider。

## 能宣称 / 不能宣称

| 能宣称 | 不能宣称 |
|---|---|
| Stage 4 bundled offline demo 及已记录的 focused acceptance 为 PASS | Stage 4 demo 证明了真实 provider Web E2E 或研究质量 |
| Retrieval 40-case authority 的表列指标与 `0/40` failures | Hybrid 相对 Vector 有提升，或 CI 证明统计显著性 |
| Citation generation `20/20` 完成及其 sends/retries/tokens/历史成本 | generation success 等于 Citation Coverage/Validity 或低 Unsupported Assertion Rate |
| 已列 authority 的路径与 SHA-256 可用于溯源 | Citation quality 指标在没有 sealed、verified authority 时可用 |
| 仅在 A 的全部来源要求满足后声明 verified 60-case | 用 Retrieval 40 + generation 20 拼接成“verified 60-case” |

## 最短最终回填 checklist

- [ ] 根据最终状态只保留 Citation quality A 或 B；另一小节完全删除。
- [ ] 若选 A，逐项填入 metrics、分母、CI、方法、绝对路径、SHA-256 与 verifier PASS；
      若选 B，只补失败 authority/诊断来源，不添加质量数值。
- [ ] 离线重算新增 authority manifest/hash，并核对报告与 manifest 数字一致。
- [ ] 仅当 final assembler 的真实 60-case manifest 与 compatibility verifier 均 PASS，
      才加入“verified 60-case”；否则全文确认没有该宣称。
- [ ] 运行最小 Markdown 相对链接、64 位 SHA-256、占位符/互斥小节检查并 review diff；
      不运行 provider、Judge、Citation runner、Task9 assembler 或全仓测试。
