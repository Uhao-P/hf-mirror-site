# Bayes Hub (huggingface-hub 镜像封装库)

`bayes_hub` 是 `huggingface_hub` 库的专用封装（锁定版本为 0.21.4）。它设计用于自动将所有 Hugging Face Hub 请求重定向到本地镜像（默认：`http://localhost:8080`），同时保持完整的 API 兼容性。

---

## 💻 本地安装

要从本仓库的源码本地安装 `bayes_hub`：

1. **进入项目根目录**：
   ```bash
   cd /path/to/hf-mirror-site
   ```

2. **使用 pip 安装**：
   ```bash
   # 标准安装
   python3 -m pip install .

   # 或开发模式安装（可编辑模式）
   python3 -m pip install -e .
   ```

3. **验证安装**：
   ```bash
   python3 -c "import bayes_hub; print(f'Default Endpoint: {bayes_hub.constants.ENDPOINT}')"
   # 预期输出：Default Endpoint: http://localhost:8080
   ```

---

## 🌐 远程部署

在远程环境（如 GPU 服务器或 CI/CD 流水线）中使用 `bayes_hub`：

### 1. 准备工作
确保您的本地镜像服务器（Caddy + LFS 代理）正在运行，并且远程机器可以访问。如果镜像服务器在不同主机上，您需要覆盖默认端点。

### 2. 远程安装
如果源码可用，您可以直接安装，或者打包成 wheel 文件：

```bash
# 在本地机器上构建 wheel 包
python3 -m build

# 将 .whl 文件传输到远程服务器
scp dist/bayes_hub-0.1.0-py3-none-any.whl user@remote-host:/tmp/

# 在远程服务器上安装 wheel 包
pip install /tmp/bayes_hub-0.1.0-py3-none-any.whl
```

### 3. 环境配置
如果您的镜像不在 `localhost:8080`，请在导入库之前设置 `HF_ENDPOINT` 环境变量：

```bash
export HF_ENDPOINT=http://your-mirror-ip:8080
```

---

## 🚀 使用方法

`bayes_hub` 设计为 `huggingface_hub` 的即插即用替代品。

### Python 代码
```python
# 只需替换导入语句
import bayes_hub as huggingface_hub

# 所有原始函数都可用，默认使用镜像
api = huggingface_hub.HfApi()
print(api.endpoint)  # http://localhost:8080

# 单文件下载
path = huggingface_hub.hf_hub_download(
    repo_id="gpt2",
    filename="config.json"
)

# 仓库下载
local_dir = huggingface_hub.snapshot_download(repo_id="facebook/opt-125m")
```

### CLI 支持
由于它依赖安装 `huggingface-hub` 0.21.4 版本，`huggingface-cli` 命令行工具也将可用。要使其使用镜像：

```bash
export HF_ENDPOINT=http://localhost:8080
huggingface-cli download gpt2
```

---

## 🛠️ 内部机制
- **依赖锁定**：强制安装 `huggingface-hub==0.21.4`。
- **镜像重定向**：在模块加载时立即设置 `os.environ["HF_ENDPOINT"]` 并修补 `huggingface_hub.constants.ENDPOINT`。
- **完全重导出**：使用动态 `globals().update()` 确保保留原始库 100% 的命名空间。
