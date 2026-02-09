#!/usr/bin/env python3
"""
Download models/datasets from Hugging Face with LFS-compatible caching.

Cache format matches lfs_cache_proxy.py:
    {cache_root}/{domain}/{url_path}
    {cache_root}/{domain}/{url_path}.sha256

Example:
    ./hf_cache/cas-bridge.xethub.hf.co/xet-bridge-us/621ffdc.../abc123...
    ./hf_cache/cas-bridge.xethub.hf.co/xet-bridge-us/621ffdc.../abc123....sha256
"""
import os
import sys
import csv
import hashlib
import shutil
import argparse
import requests
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import huggingface_hub
from huggingface_hub import HfApi, hf_hub_url

MAPPING_CSV = "model_cache_mapping.csv"
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co")


def calculate_sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def get_lfs_redirect_info(repo_id, filename, repo_type="model", revision="main", token=None):
    """
    Get the LFS redirect URL and metadata for a file.
    Returns: (lfs_url, commit_hash, linked_etag, linked_size)
    """
    url = hf_hub_url(repo_id=repo_id, filename=filename, repo_type=repo_type, revision=revision)
    
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        resp = requests.head(url, headers=headers, allow_redirects=False, timeout=30)
        if resp.status_code == 302:
            return (
                resp.headers.get("Location"),
                resp.headers.get("X-Repo-Commit"),
                resp.headers.get("X-Linked-Etag", "").strip('"'),
                resp.headers.get("X-Linked-Size")
            )
        return None, None, None, None
    except Exception as e:
        print(f"[!] Error getting redirect URL for {filename}: {e}")
        return None, None, None, None


def parse_lfs_url(lfs_url):
    """
    Parse LFS URL to get domain and path for caching.
    Example: https://cas-bridge.xethub.hf.co/xet-bridge-us/621ffdc.../abc123...?query=...
    Returns: (cas-bridge.xethub.hf.co, xet-bridge-us/621ffdc.../abc123...)
    """
    if not lfs_url:
        return None, None
    
    parsed = urlparse(lfs_url)
    domain = parsed.netloc
    path = parsed.path.lstrip("/")
    return domain, path


def download_and_cache_lfs(lfs_url, cache_root, commit_hash=None, linked_etag=None, 
                          linked_size=None, local_file_path=None):
    """
    Download file from LFS URL and cache it in the correct format.
    Cache path: {cache_root}/{domain}/{path}
    Metadata: {cache_root}/{domain}/{path}.meta (JSON with commit_hash, linked_etag)
    """
    domain, url_path = parse_lfs_url(lfs_url)
    if not domain or not url_path:
        return None
    
    cache_file_path = os.path.join(cache_root, domain, url_path)
    sha256_file_path = cache_file_path + ".sha256"
    meta_file_path = cache_file_path + ".meta"
    
    if os.path.exists(cache_file_path) and os.path.exists(sha256_file_path):
        print(f"[=] Already cached: {domain}/{url_path[:50]}...")
        if commit_hash and not os.path.exists(meta_file_path):
            import json
            with open(meta_file_path, "w") as f:
                json.dump({"commit_hash": commit_hash, "linked_etag": linked_etag, "linked_size": linked_size}, f)
        return cache_file_path
    
    os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
    
    temp_path = cache_file_path + ".tmp"
    
    print(f"[*] Downloading LFS: {domain}/{url_path[:50]}...")
    
    cmd = ["curl", "-L", "-s", "-o", temp_path, lfs_url]
    result = subprocess.run(cmd, timeout=3600)
    
    if result.returncode != 0 or not os.path.exists(temp_path):
        print(f"[!] Failed to download: {lfs_url[:100]}...")
        return None
    
    sha256_hash = calculate_sha256(temp_path)
    
    os.rename(temp_path, cache_file_path)
    with open(sha256_file_path, "w") as f:
        f.write(sha256_hash)
    
    if commit_hash:
        import json
        with open(meta_file_path, "w") as f:
            json.dump({"commit_hash": commit_hash, "linked_etag": linked_etag, "linked_size": linked_size}, f)
    
    print(f"[+] Cached: {domain}/{url_path[:50]}... (sha256: {sha256_hash[:16]}...)")
    
    if local_file_path:
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        shutil.copy2(cache_file_path, local_file_path)
        print(f"[+] Copied to: {local_file_path}")
    
    return cache_file_path


def download_small_file(repo_id, filename, cache_root, repo_type="model", revision="main", 
                        token=None, local_file_path=None):
    """Download non-LFS (small) file directly."""
    url = hf_hub_url(repo_id=repo_id, filename=filename, repo_type=repo_type, revision=revision)
    
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    cache_dir = os.path.join(cache_root, "small_files", repo_id.replace("/", "--"))
    os.makedirs(cache_dir, exist_ok=True)
    
    temp_path = os.path.join(cache_dir, filename + ".tmp")
    cache_file_path = os.path.join(cache_dir, filename)
    
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    
    print(f"[*] Downloading small file: {filename}")
    
    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=300)
        resp.raise_for_status()
        
        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        sha256_hash = calculate_sha256(temp_path)
        
        os.rename(temp_path, cache_file_path)
        with open(cache_file_path + ".sha256", "w") as f:
            f.write(sha256_hash)
        
        print(f"[+] Downloaded: {filename} (sha256: {sha256_hash[:16]}...)")
        
        if local_file_path:
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            shutil.copy2(cache_file_path, local_file_path)
        
        return cache_file_path
    except Exception as e:
        print(f"[!] Error downloading {filename}: {e}")
        return None


def update_mapping_csv(cache_root, repo_id, repo_type, cache_dirs, revision=None):
    csv_path = os.path.join(cache_root, MAPPING_CSV)
    
    existing_rows = []
    fieldnames = ["repo_id", "repo_type", "cache_dirs", "revision", "updated_at"]
    
    if os.path.exists(csv_path):
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing_rows = [row for row in reader if row["repo_id"] != repo_id]
    
    existing_rows.append({
        "repo_id": repo_id,
        "repo_type": repo_type,
        "cache_dirs": ";".join(cache_dirs),
        "revision": revision or "main",
        "updated_at": datetime.now().isoformat()
    })
    
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)
    
    print(f"[+] Updated mapping CSV: {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Download models/datasets from Hugging Face with LFS-compatible caching."
    )
    parser.add_argument("repo_id", help="Repository ID (e.g., 'gpt2' or 'facebook/opt-125m')")
    parser.add_argument("--repo-type", choices=["model", "dataset", "space"], default="model")
    parser.add_argument("--local-dir", help="Directory to download files to (actual files, no symlinks)")
    parser.add_argument("--cache-dir", default="./hf_cache", help="Cache directory (default: ./hf_cache)")
    parser.add_argument("--token", help="Hugging Face API token")
    parser.add_argument("--revision", default="main", help="Specific branch/tag/commit")
    parser.add_argument("--include", nargs="+", help="Patterns for files to include")
    parser.add_argument("--exclude", nargs="+", help="Patterns for files to exclude")
    
    args = parser.parse_args()

    cache_root = os.path.abspath(args.cache_dir)
    os.makedirs(cache_root, exist_ok=True)
    
    print(f"[*] Repository: {args.repo_id}")
    print(f"[*] Cache root: {cache_root}")
    if args.local_dir:
        print(f"[*] Local directory: {os.path.abspath(args.local_dir)}")
    
    api = HfApi()
    
    try:
        print(f"[*] Fetching file list...")
        files = api.list_repo_files(
            repo_id=args.repo_id,
            repo_type=args.repo_type,
            revision=args.revision,
            token=args.token
        )
        
        if args.include:
            import fnmatch
            filtered = []
            for f in files:
                for pattern in args.include:
                    if fnmatch.fnmatch(f, pattern):
                        filtered.append(f)
                        break
            files = filtered
        
        if args.exclude:
            import fnmatch
            filtered = []
            for f in files:
                excluded = False
                for pattern in args.exclude:
                    if fnmatch.fnmatch(f, pattern):
                        excluded = True
                        break
                if not excluded:
                    filtered.append(f)
            files = filtered
        
        print(f"[*] Total files to download: {len(files)}")
        
        cache_dirs = set()
        
        for filename in files:
            local_file_path = None
            if args.local_dir:
                local_file_path = os.path.join(os.path.abspath(args.local_dir), filename)
            
            lfs_url, commit_hash, linked_etag, linked_size = get_lfs_redirect_info(
                repo_id=args.repo_id,
                filename=filename,
                repo_type=args.repo_type,
                revision=args.revision,
                token=args.token
            )
            
            if lfs_url:
                cache_path = download_and_cache_lfs(
                    lfs_url, cache_root, 
                    commit_hash=commit_hash, 
                    linked_etag=linked_etag,
                    linked_size=linked_size,
                    local_file_path=local_file_path
                )
                if cache_path:
                    domain, _ = parse_lfs_url(lfs_url)
                    if domain:
                        cache_dirs.add(os.path.join(cache_root, domain))
            else:
                cache_path = download_small_file(
                    repo_id=args.repo_id,
                    filename=filename,
                    cache_root=cache_root,
                    repo_type=args.repo_type,
                    revision=args.revision,
                    token=args.token,
                    local_file_path=local_file_path
                )
                if cache_path:
                    cache_dirs.add(os.path.dirname(cache_path))
        
        update_mapping_csv(cache_root, args.repo_id, args.repo_type, list(cache_dirs), args.revision)
        
        print(f"[+] Download complete!")
        print(f"[+] Cache directories: {cache_dirs}")
        
    except Exception as e:
        print(f"[!] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
