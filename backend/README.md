# Yvaine Astra AI - Python 后端

## 快速开始

### 1. 安装依赖

```powershell
# 在项目根目录执行
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

### 2. 配置环境变量

```powershell
copy backend\.env.example backend\.env
# 编辑 backend\.env，填入你的 DeepSeek API Key
```

### 3. 启动后端

```powershell
# 方法 1: 使用启动脚本
.\start_backend.ps1

# 方法 2: 手动启动
.\venv\Scripts\Activate.ps1
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. 验证

打开浏览器访问: http://127.0.0.1:8000

## API 文档

启动后访问:
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

## WebSocket 协议

**连接**: `ws://127.0.0.1:8000/ws/chat`

**发送消息**:
```json
{"text": "你好，Yvaine！"}
```

**接收消息**:
```json
{
  "type": "message",
  "text": "Hello！我收到你说：「你好，Yvaine！」",
  "emotion": "开心"
}
```