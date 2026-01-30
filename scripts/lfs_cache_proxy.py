import os
import hashlib
import requests
import subprocess
import threading
from flask import Flask, request, Response, stream_with_context

app = Flask(__name__)

CACHE_ROOT = os.environ.get("CACHE_ROOT", "./hf_cache")
OUTBOUND_PROXY = os.environ.get("OUTBOUND_PROXY", "http://127.0.0.1:6666")

download_locks = threading.Lock()
active_downloads = set()

def get_proxies():
    if OUTBOUND_PROXY:
        return {"http": OUTBOUND_PROXY, "https": OUTBOUND_PROXY}
    return None

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
                while chunk := f.read(1024*1024):
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

@app.route('/proxy/<protocol>/<domain>/<path:path>')
def dynamic_proxy(protocol, domain, path):
    full_request_path = request.full_path
    prefix = f"/proxy/{protocol}/{domain}/"
    if full_request_path.startswith(prefix):
        actual_path_and_query = full_request_path[len(prefix):]
    else:
        actual_path_and_query = path
        
    real_url = f"{protocol}://{domain}/{actual_path_and_query}"
    
    cache_key_path = os.path.join(domain, path)
    local_file_path = os.path.join(CACHE_ROOT, cache_key_path)
    
    range_header = request.headers.get('Range')
    print(f"[*] [LFS] {real_url} | Range: {range_header}")

    if os.path.exists(local_file_path):
        return serve_local_file(local_file_path, range_header)

    trigger_background_download(real_url, local_file_path)

    try:
        headers = {'Range': range_header} if range_header else {}
        up_resp = requests.get(real_url, proxies=get_proxies(), headers=headers, stream=True, timeout=30, verify=False)
        
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        resp_headers = [(name, value) for (name, value) in up_resp.raw.headers.items()
                        if name.lower() not in excluded_headers]
        
        return Response(stream_with_context(up_resp.iter_content(chunk_size=1024*1024)), 
                        status=up_resp.status_code, 
                        headers=resp_headers)
    except Exception as e:
        return str(e), 502

def trigger_background_download(url, local_path):
    with download_locks:
        if local_path not in active_downloads:
            active_downloads.add(local_path)
            t = threading.Thread(target=robust_download, args=(url, local_path))
            t.daemon = True
            t.start()

def serve_local_file(path, range_header):
    size = os.path.getsize(path)
    if range_header:
        try:
            ranges = range_header.replace('bytes=', '').split('-')
            start = int(ranges[0])
            end = int(ranges[1]) if (len(ranges) > 1 and ranges[1]) else size - 1
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
        except Exception: pass
    def gen_full():
        with open(path, "rb") as f:
            while c := f.read(1024*1024): yield c
    res = Response(gen_full(), status=200, content_type="application/octet-stream")
    res.headers['Content-Length'] = str(size)
    res.headers['Accept-Ranges'] = 'bytes'
    return res

if __name__ == '__main__':
    port = int(os.environ.get("CACHE_PROXY_PORT", 50001))
    app.run(host='0.0.0.0', port=port, threaded=True)
