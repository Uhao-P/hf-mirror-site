import os
import hashlib
import requests
import subprocess
import threading
from flask import Flask, request, Response, stream_with_context
from urllib.parse import urlparse, parse_qs, urlencode

app = Flask(__name__)

CACHE_ROOT = os.environ.get("CACHE_ROOT", "./hf_cache")
OUTBOUND_PROXY = os.environ.get("OUTBOUND_PROXY", "http://127.0.0.1:6666")  # 可以设为空来测试

download_locks = threading.Lock()
active_downloads = set()

# 禁用 SSL 警告（仅用于调试）
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_proxies():
    if OUTBOUND_PROXY:
        return {"http": OUTBOUND_PROXY, "https": OUTBOUND_PROXY}
    return None

def is_xethub_url(domain):
    """检查是否是 XetHub 的 URL"""
    return domain and ('xethub' in domain or 'cas-bridge' in domain)

def get_xethub_cache_path(domain, path):
    """
    获取 XetHub 文件的缓存路径
    XetHub URL 格式: cas-bridge.xethub.hf.co/xet-bridge-us/{repo_hash}/{file_hash}
    缓存路径: {CACHE_ROOT}/{domain}/xet-bridge-us/{repo_hash}/{file_hash}
    """
    cache_key_path = os.path.join(domain, path)
    return os.path.join(CACHE_ROOT, cache_key_path)

def proxy_to_upstream_with_cache(real_url, method, local_cache_path=None):
    """代理到上游，可选地缓存响应内容"""
    try:
        # 构建转发的 headers
        skip_headers = ['host', 'content-length', 'transfer-encoding']
        headers = {}
        
        for k, v in request.headers.items():
            if k.lower() not in skip_headers:
                headers[k] = v
        
        parsed = urlparse(real_url)
        headers['Host'] = parsed.netloc
        
        print(f"[*] [LFS] Direct proxy to: {real_url[:100]}...")
        print(f"[DEBUG] Method: {method}")
        
        up_resp = requests.request(
            method=method,
            url=real_url, 
            proxies=get_proxies(), 
            headers=headers, 
            stream=True, 
            timeout=300,
            verify=False,
            allow_redirects=False
        )
        
        print(f"[DEBUG] Upstream status: {up_resp.status_code}")
        
        # 如果上游返回重定向
        if up_resp.status_code in [301, 302, 303, 307, 308]:
            location = up_resp.headers.get('Location', '')
            print(f"[DEBUG] Redirect to: {location[:100]}...")
        
        excluded_headers = ['content-encoding', 'transfer-encoding', 'connection']
        resp_headers = [(name, value) for (name, value) in up_resp.raw.headers.items()
                        if name.lower() not in excluded_headers]
        
        if method == 'HEAD':
            resp = Response(status=up_resp.status_code, headers=resp_headers)
            if 'content-length' not in [h[0].lower() for h in resp_headers]:
                cl = up_resp.headers.get('Content-Length', '0')
                resp.headers['Content-Length'] = cl
            return resp

        # GET 请求：如果需要缓存，边下载边写入缓存文件
        if local_cache_path and up_resp.status_code == 200:
            return stream_and_cache_response(up_resp, resp_headers, local_cache_path)
        
        return Response(
            stream_with_context(up_resp.iter_content(chunk_size=1024*1024)), 
            status=up_resp.status_code, 
            headers=resp_headers
        )
    except Exception as e:
        print(f"[ERROR] Proxy failed: {e}")
        import traceback
        traceback.print_exc()
        return str(e), 502

def stream_and_cache_response(up_resp, resp_headers, local_cache_path):
    """边流式返回响应，边写入缓存文件"""
    os.makedirs(os.path.dirname(local_cache_path), exist_ok=True)
    temp_path = local_cache_path + ".tmp"
    
    def generate_and_cache():
        h = hashlib.sha256()
        try:
            with open(temp_path, 'wb') as cache_file:
                for chunk in up_resp.iter_content(chunk_size=1024*1024):
                    if chunk:
                        cache_file.write(chunk)
                        h.update(chunk)
                        yield chunk
            
            # 下载完成，原子替换
            sha_val = h.hexdigest()
            os.rename(temp_path, local_cache_path)
            with open(local_cache_path + ".sha256", "w") as f:
                f.write(sha_val)
            print(f"[+] [CACHE] Cached XetHub file: {local_cache_path}")
        except Exception as e:
            print(f"[ERROR] Cache write failed: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            # 继续 yield 剩余数据，不影响客户端下载
            for chunk in up_resp.iter_content(chunk_size=1024*1024):
                if chunk:
                    yield chunk
    
    return Response(
        stream_with_context(generate_and_cache()),
        status=up_resp.status_code,
        headers=resp_headers
    )

def proxy_to_upstream(real_url, method):
    """直接代理到上游（向后兼容）"""
    return proxy_to_upstream_with_cache(real_url, method, None)

@app.route('/proxy/<protocol>/<domain>/<path:path>', methods=['GET', 'HEAD'])
def dynamic_proxy(protocol, domain=None, path=None):
    if not domain or not path:
        return "Invalid path", 400

    query_string = request.query_string.decode('utf-8') if request.query_string else ""
    
    if query_string:
        real_url = f"{protocol}://{domain}/{path}?{query_string}"
    else:
        real_url = f"{protocol}://{domain}/{path}"
    
    range_header = request.headers.get('Range')
    print(f"\n{'='*60}")
    print(f"[*] [LFS] {request.method} {real_url[:100]}...")
    print(f"[*] [LFS] Range: {range_header}")
    print(f"[*] [LFS] Domain: {domain}")

    cache_key_path = os.path.join(domain, path)
    local_file_path = os.path.join(CACHE_ROOT, cache_key_path)

    # 检查本地缓存（对所有类型的 URL 都适用）
    if os.path.exists(local_file_path):
        print(f"[*] [CACHE] Serving from cache: {local_file_path}")
        if request.method == 'HEAD':
            size = os.path.getsize(local_file_path)
            resp = Response(status=200)
            resp.headers['Content-Length'] = str(size)
            resp.headers['Accept-Ranges'] = 'bytes'
            sha_path = local_file_path + ".sha256"
            if os.path.exists(sha_path):
                with open(sha_path, 'r') as f:
                    resp.headers['ETag'] = f'"{f.read().strip()}"'
            return resp
        return serve_local_file(local_file_path, range_header)

    # XetHub：带缓存的代理（边下载边缓存）
    if is_xethub_url(domain):
        print(f"[*] [LFS] XetHub detected, proxy with cache")
        if request.method == 'GET' and not range_header:
            return proxy_to_upstream_with_cache(real_url, request.method, local_file_path)
        return proxy_to_upstream(real_url, request.method)

    # 普通 CDN-LFS：后台下载缓存
    if request.method == 'GET':
        trigger_background_download(real_url, local_file_path)

    return proxy_to_upstream(real_url, request.method)

def trigger_background_download(url, local_path):
    with download_locks:
        if local_path in active_downloads:
            return
        if os.path.exists(local_path):
            return
        active_downloads.add(local_path)
        print(f"[*] [CACHE] Triggering background download for: {url}")
        t = threading.Thread(target=robust_download, args=(url, local_path))
        t.daemon = True
        t.start()

def robust_download(url, local_path):
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        temp_path = local_path + ".tmp"
        
        cmd = ["curl", "-L", "-s", "-o", temp_path, url]
        if OUTBOUND_PROXY:
            cmd.extend(["-x", OUTBOUND_PROXY])
        
        print(f"[*] [CACHE] Starting: {url}")
        result = subprocess.run(cmd, timeout=1200)
        
        if result.returncode == 0 and os.path.exists(temp_path):
            h = hashlib.sha256()
            with open(temp_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            sha_val = h.hexdigest()
            
            os.rename(temp_path, local_path)
            with open(local_path + ".sha256", "w") as mf:
                mf.write(sha_val)
            print(f"[+] [CACHE] Done: {local_path}")
        else:
            print(f"[!] [CACHE] Failed: {url}")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        with download_locks:
            if local_path in active_downloads:
                active_downloads.remove(local_path)

def serve_local_file(path, range_header):
    size = os.path.getsize(path)
    if range_header:
        try:
            ranges = range_header.replace('bytes=', '').split('-')
            if ranges[0]:
                start = int(ranges[0])
                end = int(ranges[1]) if (len(ranges) > 1 and ranges[1]) else size - 1
            else:
                end = size - 1
                start = size - int(ranges[1])
            
            start = max(0, min(start, size - 1))
            end = max(start, min(end, size - 1))
            
            def gen():
                with open(path, "rb") as f:
                    f.seek(start)
                    rem = end - start + 1
                    while rem > 0:
                        chunk = f.read(min(1024*1024, rem))
                        if not chunk: break
                        yield chunk
                        rem -= len(chunk)
            res = Response(gen(), status=206, content_type="application/octet-stream")
            res.headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            res.headers['Content-Length'] = str(end - start + 1)
            res.headers['Accept-Ranges'] = 'bytes'
            return res
        except Exception as e:
            print(f"[!] [LFS] Error parsing range {range_header}: {e}")
    
    def gen_full():
        with open(path, "rb") as f:
            while c := f.read(1024*1024): 
                yield c
    res = Response(gen_full(), status=200, content_type="application/octet-stream")
    res.headers['Content-Length'] = str(size)
    res.headers['Accept-Ranges'] = 'bytes'
    return res

if __name__ == '__main__':
    port = int(os.environ.get("CACHE_PROXY_PORT", 50001))
    print(f"[*] Starting LFS proxy on port {port}")
    print(f"[*] Cache root: {CACHE_ROOT}")
    print(f"[*] Outbound proxy: {OUTBOUND_PROXY or 'None'}")
    app.run(host='0.0.0.0', port=port, threaded=True, debug=True)