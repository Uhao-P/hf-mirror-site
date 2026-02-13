#!/usr/bin/env python3
"""
retry_failed.py
重试下载失败的数据集（同样删除 local-dir，检查缓存大小）
"""

import json
import subprocess
import sys
import os
import shutil
import requests

NODE = "Adrastea" # Adrastea or Pear
DOWNLOAD_SCRIPT = "./scripts/hf_download.py"
CACHE_DIR = "./hf_cache"
LOCAL_DIR_ROOT = "./hf_datasets"
TOKEN = None
WECHAT_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=d8255c93-2896-4736-988e-ec0782aff888"
CACHE_SIZE_THRESHOLD = 10 * (1024 ** 4)
_threshold_notified = False


def get_dir_size(path):
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp) and not os.path.islink(fp):
                    total += os.path.getsize(fp)
    except Exception:
        pass
    return total


def format_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} EB"


def send_wechat_notification(message):
    payload = {"msgtype": "text", "text": {"content": message}}
    try:
        requests.post(WECHAT_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] 通知发送失败: {e}")


def check_cache_size_and_notify():
    global _threshold_notified
    if _threshold_notified:
        return
    size = get_dir_size(os.path.abspath(CACHE_DIR))
    if size >= CACHE_SIZE_THRESHOLD:
        send_wechat_notification(f"机器: {NODE}\n已下载超过10T\n当前大小: {format_size(size)}")
        _threshold_notified = True


def main():
    if not os.path.exists("./scripts/failed_datasets.json"):
        print("[+] 没有失败的数据集需要重试")
        return

    with open("./scripts/failed_datasets.json", "r") as f:
        failed = json.load(f)

    print(f"[*] 重试 {len(failed)} 个失败的数据集...")

    still_failed = []
    for dataset_id in failed:
        local_dir = os.path.join(LOCAL_DIR_ROOT, dataset_id.replace("/", os.sep))
        cmd = [
            sys.executable, DOWNLOAD_SCRIPT,
            dataset_id,
            "--repo-type", "dataset",
            "--cache-dir", CACHE_DIR,
            "--local-dir", local_dir,
        ]
        if TOKEN:
            cmd.extend(["--token", TOKEN])

        print(f"\n[*] 重试: {dataset_id}")
        try:
            result = subprocess.run(cmd, timeout=7200)
            if result.returncode == 0:
                print(f"[+] 成功: {dataset_id}")
                # 删除 local-dir
                if os.path.exists(local_dir):
                    shutil.rmtree(local_dir)
                    print(f"[+] 已删除本地目录: {local_dir}")
            else:
                still_failed.append(dataset_id)
                if os.path.exists(local_dir):
                    shutil.rmtree(local_dir)
        except Exception:
            still_failed.append(dataset_id)
            if os.path.exists(local_dir):
                shutil.rmtree(local_dir)

        check_cache_size_and_notify()

    if still_failed:
        with open("./scripts/failed_datasets.json", "w") as f:
            json.dump(still_failed, f, indent=2)
        print(f"\n[!] 仍有 {len(still_failed)} 个数据集失败")
    else:
        os.remove("./scripts/failed_datasets.json")
        print(f"\n[+] 所有数据集重试成功!")


if __name__ == "__main__":
    main()