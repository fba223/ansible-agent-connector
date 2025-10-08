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

以下流程假设使用 **Ubuntu Server 22.04 LTS**，并以最常见的 SSH+systemd 部署为例。每个步骤都给出完整命令，照抄即可完成环境搭建。其他发行版请参考附录。

### 步骤 A：准备 GitHub 仓库
1. 在 GitHub 控制台创建空仓库 `copilot-ansible-connector`（无需 README）。  
2. 在本地项目目录执行：
   ```bash
   git init
   git add .
   git commit -m "Initial connector implementation"
   git remote add origin https://github.com/<your-account>/copilot-ansible-connector.git
   git branch -M main
   git push -u origin main
   ```
   如使用 SSH，将远端地址改为 `git@github.com:<your-account>/copilot-ansible-connector.git`。
3. 验证 GitHub 上仓库文件是否同步成功。

### 步骤 B：创建并配置虚拟机
1. 申请一台云服务器（建议 2 vCPU / 4 GiB / 20 GiB），系统镜像选 Ubuntu 22.04。  
2. 配置安全组或防火墙：允许入站 TCP 22（SSH）及 8000（后续服务端口）。  
3. 通过 SSH 登录：
   ```bash
   ssh ubuntu@<vm-ip>
   sudo whoami   # 确认具备 root 权限
   ```

### 步骤 C：安装基础软件
```bash
sudo apt update
sudo apt install -y software-properties-common curl jq git ansible
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip
sudo ln -sf /usr/bin/python3.11 /usr/local/bin/python3

python3 --version
ansible --version
git --version
```

### 步骤 D：拉取仓库并准备运行用户
1. 克隆仓库（默认放在 `/opt`）：
   ```bash
   cd /opt
   sudo git clone https://github.com/<your-account>/copilot-ansible-connector.git
   sudo chown -R $USER:$USER copilot-ansible-connector
   cd copilot-ansible-connector
   ```
   若使用 SSH，替换为 `git@github.com:...`。
2. （可选）创建专用运行用户 `ansibleagent` 并转移文件所有权：
   ```bash
   sudo useradd -m -s /bin/bash ansibleagent
   sudo usermod -aG sudo ansibleagent
   sudo chown -R ansibleagent:ansibleagent /opt/copilot-ansible-connector
   sudo -iu ansibleagent
   cd /opt/copilot-ansible-connector
   ```

### 步骤 E：创建 Python 虚拟环境
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -e .
```
可选：安装测试依赖并运行测试（若 `pytest` 可用）：
```bash
pip install -e .[dev]
pytest
```

### 步骤 F：准备 Ansible 凭据
1. 将连接目标主机所需的 SSH Key 放置于 `~/.ssh`：
   ```bash
   mkdir -p ~/.ssh
   chmod 700 ~/.ssh
   cp /path/to/id_rsa ~/.ssh/
   chmod 600 ~/.ssh/id_rsa
   ```
2. 测试连通性：
   ```bash
   ssh -i ~/.ssh/id_rsa user@<managed-node-ip> "hostname && uptime"
   ```
3.（可选）提前创建空 inventory：
   ```bash
   mkdir -p data/inventory
   cat <<'EOF' > data/inventory/inventory.yml
   all:
     hosts: {}
   EOF
   ```

### 步骤 G：开发模式启动验证
```bash
source .venv/bin/activate
copilot-ansible-agent
```
默认监听 `http://0.0.0.0:8000`。如需更换端口：
```bash
UVICORN_HOST=0.0.0.0 UVICORN_PORT=9000 copilot-ansible-agent
```
（或直接使用 `uvicorn copilot_ansible_agent.api:app --host 0.0.0.0 --port 9000`）。

### 步骤 H：注册为 systemd 服务
1. 创建 systemd 单元文件（请根据实际用户和路径替换）：
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
2. 激活服务：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now copilot-ansible-agent
   sudo systemctl status copilot-ansible-agent
   ```
3. 查看实时日志：
   ```bash
   sudo journalctl -u copilot-ansible-agent -f
   ```

### 步骤 I：开放防火墙端口
若使用 UFW：
```bash
sudo ufw allow OpenSSH
sudo ufw allow 8000/tcp
sudo ufw enable    # 若未启用
sudo ufw status
```
在云供应商控制台也需开放对应端口。

### 步骤 J：API 功能验证
1. 健康检查：
   ```bash
   curl http://127.0.0.1:8000/healthz
   ```
2. 添加主机：
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
3. 写入 Playbook：
   ```bash
   curl -X POST http://127.0.0.1:8000/files/write \
     -H "Content-Type: application/json" \
     -d '{
           "relative_path": "quickstart/install_nginx.yml",
           "content": "- hosts: all\n  become: true\n  tasks:\n    - name: Install nginx\n      apt:\n        name: nginx\n        state: present\n        update_cache: true\n"
         }'
   ```
4. 执行并查看日志：
   ```bash
   RUN_ID=$(curl -s -X POST http://127.0.0.1:8000/playbooks/run \
     -H "Content-Type: application/json" \
     -d '{"relative_playbook_path": "quickstart/install_nginx.yml"}' | jq -r .run_id)

   curl http://127.0.0.1:8000/runs/$RUN_ID
   curl http://127.0.0.1:8000/stream/$RUN_ID
   ```
若返回报错，请检查 `journalctl` 日志以及 `/data` 目录权限。

### 步骤 K：连接 Copilot Studio
1. 在 Copilot Studio 中打开“插件/连接器”，创建新连接器。  
2. 指定基础 URL（如 `https://connector.example.com`，若无域名可用公网 IP）。  
3. 新建动作：
   - `POST /inventory/hosts` → “添加主机”；
   - `GET /inventory/hosts` → “查看主机列表”；
   - `POST /files/write` → “写入 Playbook”；
   - `POST /playbooks/run` → “执行 Playbook”；
   - `GET /runs/{run_id}` → “查询执行状态”；
   - `GET /stream/{run_id}` → “订阅执行日志”（SSE）。  
4. 在 Agent Flow 中使用这些动作，使用变量存储 `run_id` 并轮询 `/runs/{run_id}`；前端可通过 SSE 实时展示 `/stream/{run_id}` 日志。

### 步骤 L：常见问题排查
```text
- 端口无法访问：确认安全组/UFW/systemd 均已允许；使用 `ss -tlnp | grep 8000` 查看监听状态。
- Playbook 执行失败：查看 `/stream/{run_id}` 输出；确认被管节点 SSH 凭据正确。
- Inventory 未写入：检查 `data/inventory/inventory.yml` 是否存在及其权限；确保请求中的 `name` 唯一。
- systemd 服务崩溃：`journalctl -u copilot-ansible-agent -f` 查看栈；若缺少 Python 包或路径错误，重新执行安装或修正单元文件。
```

### 附录：RHEL / CentOS 7/8 对照命令
1. 安装依赖：
   ```bash
   sudo yum install -y gcc openssl-devel bzip2-devel libffi-devel make git ansible
   sudo dnf install -y python3.11 python3.11-devel python3.11-venv  # CentOS Stream 8+
   sudo alternatives --set python3 /usr/bin/python3.11
   ```
   若官方仓库无 Python 3.11，可安装 `pyenv` 或从源码编译。
2. 其余步骤（拉仓库、创建虚拟环境、systemd 配置）与 Ubuntu 基本相同，只需将命令中的路径/用户调整为实际值。

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