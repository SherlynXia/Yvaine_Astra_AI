# 训练流水线

## 数据来源
- `backend/data/feedback.jsonl` — 用户评分数据

## 触发条件
当 `rating=good` 的记录 > 200 条时，开始考虑微调。

## 路径
1. Level 2：从 feedback 筛选优质对话，作为 ICL 范例
2. Level 3：Unsloth QLoRA 微调
3. Level 4：合并 → GGUF → `ollama create yvaine-v1`