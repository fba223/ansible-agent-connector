AI 驱动的 Ansible Connector（Copilot Studio 工具后端）
================================================

本项目只聚焦于在 **Ansible Master 节点** 上部署一个 RESTful Connector，使 Copilot Studio 智能体能够通过统一 API 访问 Ansible 能力。Copilot Studio 负责自然语言解析与 LLM 推理，这里仅提供底层执行与数据管理。

## 能力范围

1. **上传/生成后的 Playbook 写入**  
   `POST /files/write` 将 Copilot 侧生成的 YAML 内容写入到 master 节点的 `data/playbooks/` 目录。

2. **Inventory 管理**  
   - `POST /inventory/hosts` 添加/更新主机信息  
   - `GET /inventory/hosts` 列出当前主机  
   - `DELETE /inventory/hosts/{name}` 删除主机  

   Inventory 数据落地为 `data/inventory/inventory.yml`，Ansible 随时可用。

3. **Playbook 执行与日志流**  
   - `POST /playbooks/run` 启动 `ansible-playbook` 任务，返回 `run_id`  
   - `GET /stream/{run_id}` 通过 SSE 持续推送实时日志  
   - `GET /runs/{run_id}` 查询执行状态与摘要  

4. **健康检查**  
   `GET /healthz` 供 Copilot Studio 探测服务存活状态。

## 组件结构

```
┌────────────────────┐        ┌──────────────────────────┐
│ Copilot Studio     │  HTTP  │ Copilot Ansible Connector│
│ (LLM 聊天窗口)     │ <──────┤ FastAPI 应用              │
└────────────────────┘        ├──────────────────────────┤
                               │InventoryService (YAML)   │
                               │FileStorage (playbooks)   │
                               │PlaybookRunner (async CLI)│
                               └──────────────────────────┘
                                        │
                                        ▼
                            ┌────────────────────────┐
                            │Ansible CLI / Playbooks │
                            └────────────────────────┘
```

### 关键模块
- `inventory.service.InventoryService`：线程安全的 YAML 库存管理。
- `storage.files.FileStorage`：限制在指定目录下的安全文件写入。
- `executor.playbook_runner.PlaybookRunner`：异步运行 `ansible-playbook`，收集日志并生成摘要。
- `api`：FastAPI 定义的 REST/SSE 接口。
- `config`：统一配置来源，支持环境变量覆盖。

## 从零开始的部署指南

以下示例以 **Ubuntu Server 22.04 LTS** 为基线，其他发行版请参考对应包管理器命令（CentOS / RHEL 在附录给出）。步骤覆盖从准备 GitHub 仓库到在虚拟机上运行服务的全过程。

### 0. 准备 GitHub 仓库
0.1 在 GitHub 新建一个空仓库，例如 `copilot-ansible-connector`，保持默认分支为 `main`。  
0.2 在本地开发环境（当前目录）执行：
```bash
git init
git add .
git commit -m "Initial connector implementation"
git remote add origin git@github.com:<your-account>/copilot-ansible-connector.git
git branch -M main
git push -u origin main
```
> 如果使用 HTTPS，替换为 `https://github.com/<your-account>/copilot-ansible-connector.git`。

完成后，虚拟机即可直接 `git clone` 获取代码。

### 1. 准备目标虚拟机
1.1 创建一台具备公网访问能力的虚拟机，推荐配置：2 vCPU、4 GiB RAM、20 GiB 磁盘。  
1.2 为虚拟机添加安全组或防火墙规则，允许端口 22（SSH）及 8000（连接器 HTTP 服务，后续可自定义）。  
1.3 通过 SSH 登录虚拟机，确认具备 sudo 权限：
```bash
ssh ubuntu@<vm-ip>
sudo whoami
```

### 2. 安装系统依赖
执行以下命令安装 Python3.11、虚拟环境工具、Git、Ansible 及基础工具：
```bash
sudo apt update
sudo apt install -y software-properties-common curl jq
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git ansible
sudo ln -sf /usr/bin/python3.11 /usr/local/bin/python3
```
验证安装：
```bash
python3 --version     # 应输出 3.11.x
ansible --version
git --version
```

### 3. 克隆仓库与用户权限
3.1 在 `/opt` 或其他工作目录中克隆仓库：
```bash
cd /opt
sudo git clone git@github.com:<your-account>/copilot-ansible-connector.git
sudo chown -R $USER:$USER copilot-ansible-connector
cd copilot-ansible-connector
```
如需使用 HTTPS，可替换为 `https://github.com/...`。  
3.2 若打算以专用用户运行服务，可先创建用户：
```bash
sudo useradd -m -s /bin/bash ansibleagent
sudo usermod -aG sudo ansibleagent
sudo chown -R ansibleagent:ansibleagent /opt/copilot-ansible-connector
```
后续切换到该用户执行剩余步骤：
```bash
sudo -iu ansibleagent
cd /opt/copilot-ansible-connector
```

### 4. 创建 Python 虚拟环境并安装
4.1 创建虚拟环境并激活：
```bash
python3 -m venv .venv
source .venv/bin/activate
```
4.2 更新 pip 并安装项目：
```bash
pip install --upgrade pip wheel setuptools
pip install -e .
```
4.3 如需本地单元测试或静态检查，安装开发依赖：
```bash
pip install -e .[dev]
pytest  # 可选
```

### 5. 配置 Ansible 访问能力
5.1 确保 master 节点可以访问目标主机（SSH 密钥或密码），可将私钥置于 `~/.ssh` 并配置权限：
```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_rsa
```
5.2 验证到被管节点的连通性：
```bash
ssh user@managed-node-ip uptime
```
5.3 可选：预置一个初始 inventory，后续也可以通过 API 完全管理：
```bash
cat <<'EOF' > data/inventory/inventory.yml
all:
  hosts: {}
EOF
```
运行服务时若文件不存在会自动创建。

### 6. 启动服务（开发模式）
在激活虚拟环境的终端内运行：
```bash
copilot-ansible-agent
```
默认监听地址为 `http://0.0.0.0:8000`。若需修改端口，可设置环境变量后再启动：
```bash
export UVICORN_PORT=9000  # 例：更换端口
copilot-ansible-agent
```
（若要改主机/端口，可改用 `uvicorn copilot_ansible_agent.api:app --host 0.0.0.0 --port 9000`。）

### 7. 部署为 systemd 服务（推荐）
7.1 创建 systemd 单元文件（请根据实际用户名修改 `User`、`WorkingDirectory` 和虚拟环境路径）：
```bash
sudo tee /etc/systemd/system/copilot-ansible-agent.service <<'EOF'
[Unit]
Description=Copilot Ansible Connector
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=ansibleagent
WorkingDirectory=/opt/copilot-ansible-connector
Environment="PATH=/opt/copilot-ansible-connector/.venv/bin"
ExecStart=/opt/copilot-ansible-connector/.venv/bin/copilot-ansible-agent
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```
7.2 刷新并启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now copilot-ansible-agent
sudo systemctl status copilot-ansible-agent
```
7.3 查看日志：
```bash
sudo journalctl -u copilot-ansible-agent -f
```

### 8. 防火墙与安全加固
8.1 若启用 UFW，开放 8000 端口：
```bash
sudo ufw allow 8000/tcp
sudo ufw status
```
8.2 若通过云厂商安全组管理端口，保证 8000 对 Copilot Studio 所在网段开放。  
8.3 如需 HTTPS，可在前面加一个 Nginx/Traefik 反向代理并配置 TLS 证书。  
8.4 建议将系统用户权限限制在最低范围，定期更新系统补丁。  

### 9. 验证 API
9.1 健康检查：
```bash
curl http://127.0.0.1:8000/healthz
```
9.2 主机管理：
```bash
curl -X POST http://127.0.0.1:8000/inventory/hosts \
  -H "Content-Type: application/json" \
  -d '{
        "name": "web-01",
        "hostname": "10.0.0.10",
        "username": "ubuntu",
        "groups": ["web"],
        "variables": {"ansible_become": true}
      }'

curl http://127.0.0.1:8000/inventory/hosts
```
9.3 写入示例 Playbook：
```bash
curl -X POST http://127.0.0.1:8000/files/write \
  -H "Content-Type: application/json" \
  -d '{
        "relative_path": "quickstart/install_nginx.yml",
        "content": "- hosts: all\n  become: true\n  tasks:\n    - name: Install nginx\n      apt:\n        name: nginx\n        state: present\n        update_cache: true\n"
      }'
```
9.4 执行 Playbook 并获取日志：
```bash
RUN_ID=$(curl -s -X POST http://127.0.0.1:8000/playbooks/run \
  -H "Content-Type: application/json" \
  -d '{"relative_playbook_path": "quickstart/install_nginx.yml"}' | jq -r .run_id)

curl http://127.0.0.1:8000/runs/$RUN_ID
curl http://127.0.0.1:8000/stream/$RUN_ID
```
如果日志输出乱码或为空，检查 Ansible 是否能访问目标主机，以及服务运行用户是否拥有 Playbook 和 inventory 目录的读写权限。

### 10. 与 Copilot Studio 集成
10.1 在 Copilot Studio 创建自定义连接器，指定基础 URL（例如 `https://connector.example.com`）。  
10.2 配置动作，对应上述 API：`POST /inventory/hosts`、`POST /files/write`、`POST /playbooks/run`、`GET /runs/{run_id}`、`GET /stream/{run_id}`。  
10.3 在 Chatflow 中为 Agent 添加这些动作，注意保存和传递 `run_id`。  
10.4 可使用 SSE 流结果实时反馈日志，执行完成后读取摘要并进行自然语言总结。  

### 11. 常见故障排查
- **无法访问 8000 端口**：检查安全组、防火墙、systemd 服务状态。  
- **执行 Playbook 失败**：查看 `/stream/{run_id}` 日志，确认目标主机凭据与网络。  
- **Inventory 未更新**：确认请求体 `name` 无冲突，查看 `data/inventory/inventory.yml` 是否写入成功。  
- **服务重启频繁**：查看 `journalctl`，可能是 Python 依赖缺失或路径配置错误。  

### 附录：RHEL / CentOS 7/8 命令对照
1. 启用 EPEL 与 Python 3.11 源：
```bash
sudo yum install -y gcc openssl-devel bzip2-devel libffi-devel make git ansible
sudo dnf install -y python3.11 python3.11-devel python3.11-venv  # CentOS Stream 8+
```
若仓库没有 Python 3.11，可使用 `pyenv` 或源码编译。  
2. 其余步骤与 Ubuntu 类似，需要注意 systemd 单元中的用户与路径。  

### 示例调用流程

1. Copilot Studio 上传官方文档并生成 Playbook 文本。
2. Copilot Studio 调用 `POST /files/write`，写入 `cluster/install_k8s.yml`。
3. 用户在对话中提供服务器 IP/账号，Copilot Studio 调用 `POST /inventory/hosts`。
4. Copilot Studio 调用 `POST /playbooks/run` 启动执行，并订阅 `GET /stream/{run_id}` 查看输出。
5. 执行结束后，Copilot Studio 调用 `GET /runs/{run_id}` 获取摘要，转述给用户。

### 配置要点
- 默认数据目录：`project_root/data/`
  - `inventory/inventory.yml`
  - `playbooks/*.yml`
  - `executions/` 预留给后续扩展
- 环境变量：
  - `ANSIBLE_PLAYBOOK_BINARY`（可选）覆盖默认命令。
  - `CONNECTOR_TYPE` 等字段预留给未来扩展。

### 后续可拓展方向
- 增加 Token/Basic Auth 保护。
- 支持 Playbook 执行完成后的附件收集（日志、报告）。
- 在摘要阶段解析 `PLAY RECAP` 更多维度（ok/changed/failed/unreachable）。
- 扩展到 RESTful Inventory（例如调用 AWX / AAP）。
