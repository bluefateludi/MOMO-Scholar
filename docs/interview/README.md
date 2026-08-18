# TechScout 面试材料

> 事实基线：`750b17a7a2bf3217793c70e4fc065f1728288743`
>
> 本目录是面试表达，不是工程规范。工程事实与演进协议以 [`../production/`](../production/README.md) 为准。

## 诚实表达规则

- **已实现**：可以用“我实现了”，但要说清本地单进程、synthetic Fast Demo 等边界。
- **本轮实现中**：主实现正在其他提交中推进；本事实基线尚未包含，也尚未验证。只能说“正在实现/协议已设计”，不能说“已经上线”。
- **未实现**：主动说明，随后解释如果生产化会如何验证。
- 三个 STAR 是确定性故障注入/恢复验证，不是线上事故复盘。
- 不讨论真实模型效果，不引用 synthetic 指标作为产品质量或简历成果。

生产文档继续使用“本轮计划”描述目标合同；面试材料中的“本轮实现中”用于反映主实现分支正在推进。两者都不等于基线已实现或已验证。

## 内容

1. [90 秒项目介绍](90-second-introduction.md)
2. [可靠性 deep dive](reliability-deep-dive.md)
3. [三个 STAR 故障案例](star-failure-cases.md)
4. [常见后端追问与诚实边界](backend-faq-and-honest-boundaries.md)
