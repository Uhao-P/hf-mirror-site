# Hugging Face 本地加速镜像站 (Local Mirror)

本项目通过 Caddy 转发和本地缓存，实现国内环境下 Hugging Face 模型和数据集的高速下载。

---

## 🚀 快速开始 (本地测试模式)

如果你只想在本地 (127.0.0.1) 快速启动并测试，请遵循以下步骤。此模式不需要 root 权限，也不需要安装额外插件。

### 1. 配置环境
```bash
# 进入配置目录
cd scripts/caddy
# 复制并编辑环境变量 (默认已配置好本地测试参数)
cp .env.template .env
```

### 2. 启动服务
使用本地测试专用的配置文件（监听端口 `8080`，已配置兼容 127.0.0.1 和 localhost）：
```bash
caddy run --envfile scripts/caddy/.env --config scripts/caddy/Caddyfile.local
```

### 3. 验证
访问 [http://localhost:8080](http://localhost:8080) 或执行：
```bash
export HF_ENDPOINT=http://localhost:8080
huggingface-cli download gpt2
```

---

## 🛠️ 生产部署 (全功能模式)

要启用全功能（如页面关键词自动替换、HTTPS 支持），建议在 macOS (M 系列) 上直接使用项目根目录下的定制版 Caddy：
```bash
./caddy_darwin_arm64_custom run --envfile scripts/caddy/.env --config scripts/caddy/Caddyfile
```
该版本已预装 `replace-response`、`transform-encoder` 和 `cloudflare` 插件。

---

## 📦 进阶：本地缓存与自动校验 (全域名支持)

本镜像站支持 **"一次下载，永久缓存"**，且已升级支持 HF 所有的分发后端（包括 `cdn-lfs` 和 `cas-bridge`）。

### 1. 启动逻辑
1. **启动缓存代理脚本**:
   ```bash
   export CACHE_ROOT=./hf_cache
   # 如果需要代理，请设置 OUTBOUND_PROXY
   python scripts/lfs_cache_proxy.py
   ```
2. **启动 Caddy (本地模式)**:
   ```bash
   caddy run --envfile scripts/caddy/.env --config scripts/caddy/Caddyfile.local
   ```

### 2. 功能原理
-   **动态拦截**: Caddy 会自动捕获官方返回的所有 LFS 重定向链接。
-   **本地中转**: 重定向会被重写为本地 `localhost:8080` 的路径，确保 `huggingface-cli` 能够安全地跟随重定向。
-   **流式缓存**: 采用了稳健的 **后台下载 + 临时文件原子替换** 机制，支持多线程 Range 请求。
-   **自动校验**: 采用 HF 官方标准的 **SHA256** 算法进行校验。下载完成后自动生成 `.sha256` 文件。再次请求时，脚本会对比官方 `ETag` (SHA256)，若不匹配则自动重下。

### 3. 验证缓存
下载完成后，检查目录：
```bash
ls -R ./hf_cache
```
你会看到按域名分类存储的模型原始文件及其 `.sha256` 校验文件。

