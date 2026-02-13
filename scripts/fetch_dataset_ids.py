#!/usr/bin/env python3
"""
fetch_dataset_ids.py
获取指定组织在 Hugging Face 上的所有 dataset ID
"""

from huggingface_hub import HfApi
import json

orgs = [
    "nvidia",
    "google",
    "meta-llama",
    "apple",
    "microsoft",
    "openai",
    "deepseek-ai",
    "ByteDance",
]

api = HfApi()
all_datasets = {}

for org in orgs:
    print(f"\n[*] 正在获取 {org} 的数据集列表...")
    try:
        datasets = list(api.list_datasets(author=org))
        dataset_ids = [ds.id for ds in datasets]
        all_datasets[org] = dataset_ids
        print(f"[+] {org}: 找到 {len(dataset_ids)} 个数据集")
        for ds_id in dataset_ids:
            print(f"    - {ds_id}")
    except Exception as e:
        print(f"[!] 获取 {org} 数据集失败: {e}")
        all_datasets[org] = []

with open("all_dataset_ids.json", "w", encoding="utf-8") as f:
    json.dump(all_datasets, f, indent=2, ensure_ascii=False)

total = sum(len(v) for v in all_datasets.values())
print(f"\n[+] 总计: {total} 个数据集")
print(f"[+] 已保存到 all_dataset_ids.json")