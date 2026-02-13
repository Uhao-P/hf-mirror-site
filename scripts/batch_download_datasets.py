#!/usr/bin/env python3
"""
batch_download_datasets.py
批量下载所有组织的数据集，调用 hf_download.py
- 下载完成后删除 --local-dir 文件夹，只保留 --cache-dir
- 当 ./hf_cache 超过 10TB 时发送企业微信通知
"""

import json
import subprocess
import sys
import os
import shutil
import time
import requests
from pathlib import Path

# ========== 配置区 ==========
DOWNLOAD_SCRIPT = "./scripts/download.py"
CACHE_DIR = "./hf_cache"
LOCAL_DIR_ROOT = "./hf_datasets"
TOKEN = None  # HF Token，如需私有数据集请填写
DATASET_IDS_FILE = "./scripts/all_dataset_ids.json"

# 企业微信 Webhook
NODE = "Adrastea" # Adrastea or Pear
WECHAT_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=d8255c93-2896-4736-988e-ec0782aff888"

# 缓存空间阈值：10TB = 10 * 1024^4 bytes
CACHE_SIZE_THRESHOLD = 10 * (1024 ** 4)

# 是否已发送过超阈值通知（运行期间只发一次）
_threshold_notified = False
# ============================


def get_dir_size(path):
    """递归计算目录大小（字节）"""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp) and not os.path.islink(fp):
                    total += os.path.getsize(fp)
    except Exception as e:
        print(f"[!] 计算目录大小出错: {e}")
    return total


def format_size(size_bytes):
    """将字节数格式化为可读字符串"""
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} EB"


def send_wechat_notification(message):
    """发送企业微信机器人通知"""
    payload = {
        "msgtype": "text",
        "text": {
            "content": message
        }
    }
    try:
        resp = requests.post(
            WECHAT_WEBHOOK_URL,
            json=payload,
            timeout=10
        )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("errcode") == 0:
                print(f"[+] 企业微信通知发送成功")
            else:
                print(f"[!] 企业微信通知发送失败: {result}")
        else:
            print(f"[!] 企业微信通知 HTTP 错误: {resp.status_code}")
    except Exception as e:
        print(f"[!] 发送企业微信通知出错: {e}")


def check_cache_size_and_notify():
    """检查缓存目录大小，超过阈值则发送通知"""
    global _threshold_notified
    if _threshold_notified:
        return

    cache_path = os.path.abspath(CACHE_DIR)
    if not os.path.exists(cache_path):
        return

    size = get_dir_size(cache_path)
    size_str = format_size(size)
    print(f"[*] 当前缓存大小: {size_str}")

    if size >= CACHE_SIZE_THRESHOLD:
        message = (
            f"节点: {NODE}"
            f"已下载超过10T\n"
            f"缓存目录: {cache_path}\n"
            f"当前大小: {size_str}"
        )
        send_wechat_notification(message)
        _threshold_notified = True
        print(f"[!] 缓存已超过 10TB，已发送通知")


def download_dataset(dataset_id, cache_dir, local_dir, token=None):
    """调用 hf_download.py 下载单个数据集"""
    cmd = [
        sys.executable, DOWNLOAD_SCRIPT,
        dataset_id,
        "--repo-type", "dataset",
        "--cache-dir", cache_dir,
        "--local-dir", local_dir,
    ]

    if token:
        cmd.extend(["--token", token])

    print(f"\n{'='*60}")
    print(f"[*] 开始下载数据集: {dataset_id}")
    print(f"[*] 本地目录: {local_dir}")
    print(f"{'='*60}")

    try:
        result = subprocess.run(cmd, timeout=7200)  # 2小时超时
        if result.returncode == 0:
            print(f"[+] 数据集 {dataset_id} 下载成功!")
            return True
        else:
            print(f"[!] 数据集 {dataset_id} 下载失败 (返回码: {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print(f"[!] 数据集 {dataset_id} 下载超时!")
        return False
    except Exception as e:
        print(f"[!] 数据集 {dataset_id} 下载出错: {e}")
        return False


def remove_local_dir(local_dir):
    """下载完成后删除 local-dir 文件夹，只保留 cache-dir"""
    if os.path.exists(local_dir):
        try:
            shutil.rmtree(local_dir)
            print(f"[+] 已删除本地目录: {local_dir}")

            # 清理空的父目录
            parent = os.path.dirname(local_dir)
            while parent and parent != os.path.abspath(LOCAL_DIR_ROOT):
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
                    print(f"[+] 已删除空父目录: {parent}")
                    parent = os.path.dirname(parent)
                else:
                    break
        except Exception as e:
            print(f"[!] 删除本地目录失败 {local_dir}: {e}")


def main():
    # 检查下载脚本是否存在
    if not os.path.exists(DOWNLOAD_SCRIPT):
        print(f"[!] 下载脚本不存在: {DOWNLOAD_SCRIPT}")
        sys.exit(1)

    # 检查数据集 ID 文件
    if not os.path.exists(DATASET_IDS_FILE):
        print(f"[!] 数据集 ID 文件不存在: {DATASET_IDS_FILE}")
        print(f"[*] 请先运行 fetch_dataset_ids.py 获取数据集列表")
        sys.exit(1)

    # 读取数据集列表
    with open(DATASET_IDS_FILE, "r", encoding="utf-8") as f:
        all_datasets = json.load(f)

    total = sum(len(v) for v in all_datasets.values())
    print(f"[*] 共需下载 {total} 个数据集")
    print(f"[*] 缓存目录: {os.path.abspath(CACHE_DIR)}")
    print(f"[*] 本地临时目录: {os.path.abspath(LOCAL_DIR_ROOT)}")
    print(f"[*] 缓存阈值: {format_size(CACHE_SIZE_THRESHOLD)}")

    # 加载已完成列表（支持断点续传）
    progress_file = "download_progress.json"
    completed = set()
    if os.path.exists(progress_file):
        with open(progress_file, "r") as f:
            completed = set(json.load(f))
        print(f"[*] 已完成 {len(completed)} 个数据集，跳过")

    success_count = 0
    fail_count = 0
    skip_count = 0
    failed_datasets = []

    current = 0
    for org, dataset_ids in all_datasets.items():
        print(f"\n{'#'*60}")
        print(f"# 组织: {org} ({len(dataset_ids)} 个数据集)")
        print(f"{'#'*60}")

        for dataset_id in dataset_ids:
            current += 1

            # 跳过已完成的
            if dataset_id in completed:
                skip_count += 1
                print(f"\n>>> 进度: {current}/{total} — 跳过已完成: {dataset_id}")
                continue

            print(f"\n>>> 进度: {current}/{total}")

            local_dir = os.path.join(
                LOCAL_DIR_ROOT,
                dataset_id.replace("/", os.sep)
            )

            # ---- 下载 ----
            ok = download_dataset(
                dataset_id=dataset_id,
                cache_dir=CACHE_DIR,
                local_dir=local_dir,
                token=TOKEN,
            )

            # ---- 下载完成后删除 local-dir ----
            if ok:
                success_count += 1
                remove_local_dir(local_dir)

                # 记录已完成
                completed.add(dataset_id)
                with open(progress_file, "w") as f:
                    json.dump(list(completed), f)
            else:
                fail_count += 1
                failed_datasets.append(dataset_id)
                # 即使失败也清理临时目录
                remove_local_dir(local_dir)

            # ---- 检查缓存大小并通知 ----
            check_cache_size_and_notify()

    # ---- 打印汇总 ----
    print(f"\n{'='*60}")
    print(f"下载完成!")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  跳过: {skip_count}")

    # 最终缓存大小
    if os.path.exists(CACHE_DIR):
        final_size = get_dir_size(os.path.abspath(CACHE_DIR))
        print(f"  缓存总大小: {format_size(final_size)}")

    if failed_datasets:
        print(f"\n失败的数据集:")
        for ds in failed_datasets:
            print(f"  - {ds}")

        with open("./scripts/failed_datasets.json", "w", encoding="utf-8") as f:
            json.dump(failed_datasets, f, indent=2)
        print(f"\n失败列表已保存到 failed_datasets.json")

    # 清理空的临时根目录
    if os.path.exists(LOCAL_DIR_ROOT) and not os.listdir(LOCAL_DIR_ROOT):
        os.rmdir(LOCAL_DIR_ROOT)
        print(f"[+] 已删除空的临时根目录: {LOCAL_DIR_ROOT}")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()