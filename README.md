# MM Madam - AI 財經聊天機器人 API

MacroMicro 財經平台的 AI 聊天助手後端服務。

## 專案概述

MM Madam 是一個基於 FastAPI 開發的 AI 聊天機器人 API，專為 MacroMicro 財經平台設計。系統整合了 Google Gemini AI 模型，提供財經知識檢索、多語系客服支援等功能。

**核心技術：**
- **後端框架：** FastAPI + Mangum（AWS Lambda 適配器）
- **AI 模型：** Google Gemini（gemini-3-flash-preview / gemini-3.1-pro-preview）
- **套件管理：** uv
- **部署環境：** AWS Lambda + Docker/ECR
- **前端元件：** chat-widget.js（可嵌入式聊天視窗）

## 主要功能

### 多語系支援
- 繁體中文（www.macromicro.me）
- 簡體中文（sc.macromicro.me）
- 英文（en.macromicro.me）

系統會自動偵測使用者語言，並以對應語言回應。

### 財經知識檢索（RAG）
針對付費用戶，系統會平行檢索以下知識庫：

| 資料來源 | 說明 |
|---------|------|
| 圖表資料（Charts） | MM 圖表及時間序列數據 |
| 短評（Quickies） | MM 財經短評 |
| 部落格（Blog） | 中英文財經部落格文章 |
| EDM 報告 | 獨家財經報告 |
| Podcast | Podcast 逐字稿 |
| Google Search | 即時網路搜尋（Gemini 原生工具） |

### 客服功能
- Help Center 整合（知識庫檢索）
- 根據使用者語言自動切換 Help Center 區域

### 使用者分類
系統會自動將使用者問題分為三類：
1. **總經** - 財經市場相關問題
2. **客服** - 網站功能操作問題
3. **製圖** - 圖表製作請求（開發中）

## 系統架構

詳細架構圖請參閱 [ARCHITECTURE.md](./ARCHITECTURE.md)。

## 快速開始

### 環境變數設定

建立 `.env` 檔案並設定以下環境變數：

```bash
# Google Gemini API（透過 genai 套件自動讀取 GOOGLE_API_KEY）
GOOGLE_API_KEY=your_gemini_api_key

# Google Custom Search API（站內搜尋）
SEARCH_API_KEY=your_search_api_key

# 系統提示詞 URL
SYSTEM_PROMPT_URL=https://your-prompt-url
MARKETING_PROMPT_URL=https://your-marketing-prompt-url

# 知識庫 API
KNOWLEDGE_CSV_API=https://your-knowledge-api
CHARTS_DATA_API=https://your-charts-api
PODCAST_FOLDER_URL=https://drive.google.com/drive/folders/xxx

# 日誌記錄
LOGGER=https://your-logger-endpoint
GITHUB_GIST_API=https://api.github.com/gists/xxx
GITHUB_ACCESS_TOKEN=your_github_token

# JWT 驗證
JWT_SECRET=your_jwt_secret

# 用量限制 API
USAGE_API=https://your-usage-api

# MCP Server（選用）
REMOTE_MCP_SERVER=https://your-mcp-server

# 前端設定（測試用，預設關閉）
ENABLE_FRONTEND=false
MM_HIDE_CHAT_BUBBLE=false
```

### 本地開發

```bash
# 安裝依賴（使用 uv）
uv sync

# 啟動開發伺服器
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 啟用測試前端（選用）
ENABLE_FRONTEND=true uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

開發伺服器啟動後，可透過以下方式存取：
- API 文件：http://localhost:8000/docs
- 測試頁面：http://localhost:8000（需設定 `ENABLE_FRONTEND=true`）

### Docker 部署

```bash
# 建置 Docker 映像
docker build -t mm-madam .

# 本地測試
docker run -p 9000:8080 --env-file .env mm-madam
```

## API 端點說明

### GET /health
健康檢查端點，用於 AWS Lambda 監控。

**Response:**
```json
{
  "status": "healthy"
}
```

### POST /chat
主要聊天端點，處理使用者訊息並回傳 AI 回應。

**Request Body:**
```json
{
  "user_id": 12345,
  "message": "請問美國 CPI 最新數據是多少？",
  "jwt": "eyJhbGciOiJIUzI1NiIs...",
  "conversation_history": [],
  "config": {
    "is_paid_user": true,
    "has_chart": true,
    "has_quickie": true,
    "has_blog": true,
    "has_edm": true,
    "has_podcast": true,
    "has_google_search": true,
    "has_help_center": true,
    "conversation_rounds": 2,
    "thinking_budget": 500,
    "quality_model": "gemini-3-flash-preview",
    "N_most_relevant": 5
  },
  "response_type": "html",
  "current_page_html": "<html>...</html>",
  "current_page_url": "https://www.macromicro.me/charts/1/xxx"
}
```

**Response:**
```json
{
  "response_html": "<p>根據最新數據...</p>",
  "response_markdown": "根據最新數據...",
  "cost": 0.023,
  "token_usage": {
    "prompt_tokens": 15000,
    "completion_tokens": 500,
    "thinking_tokens": 200,
    "total_tokens": 15700
  },
  "conversation_history": [...],
  "response_seconds": 3.5,
  "started": 1705900000,
  "requested": 1705900001,
  "responded": 1705900004
}
```

**429 Response（用量超限）：**
```json
[{"question_type": "客服", "usage": 5, "limit": 5, "period": "daily"}]
```

### POST /chat-stream
串流聊天端點，使用 Server-Sent Events（SSE）即時回傳 AI 回應。請求格式與 `/chat` 相同。用量超限時回傳 HTTP 429（同 `/chat` 格式）。

### POST /search
站內搜尋端點，使用 Google Custom Search API。

**Request Body:**
```json
{
  "query": "美國 CPI"
}
```

**Response:**
```json
{
  "results": "<ul><li>📈 <a href='...'>...</a></li></ul>"
}
```

### GET /config
取得前端設定（如是否隱藏聊天氣泡）。需設定 `ENABLE_FRONTEND=true`。

**Response:**
```json
{
  "MM_HIDE_CHAT_BUBBLE": "false"
}
```

### POST /system-prompt
取得當前系統提示詞（除錯用途）。

## 設定選項

### ConfigModel 功能開關

| 參數 | 預設值 | 說明 |
|-----|-------|------|
| `is_paid_user` | `true` | 是否為付費用戶（影響知識檢索功能） |
| `has_chart` | `true` | 啟用圖表資料檢索 |
| `has_quickie` | `true` | 啟用短評檢索 |
| `has_blog` | `true` | 啟用部落格檢索 |
| `has_edm` | `true` | 啟用 EDM 報告檢索 |
| `has_podcast` | `true` | 啟用 Podcast 檢索 |
| `has_google_search` | `true` | 啟用 Google 搜尋 |
| `has_help_center` | `true` | 啟用 Help Center 檢索 |
| `conversation_rounds` | `2` | 對話歷史保留輪數 |
| `thinking_budget` | `500` | Gemini 思考 token 預算 |
| `quality_model` | `gemini-3-flash-preview` | 使用的 AI 模型 |
| `N_most_relevant` | `5` | 每個知識庫檢索的最大項目數 |
| `no_single_series` | `false` | 過濾單一序列圖表 |

### 模型定價參考

| 模型 | 輸入 ($/M) | 輸出 ($/M) | 思考 ($/M) | 快取 ($/M) |
|-----|-----------|-----------|-----------|-----------|
| gemini-3-flash-preview | 0.5 | 3.0 | 3.0 | 0.05 |
| gemini-3.1-pro-preview | 2.0 | 12.0 | 12.0 | 0.2 |

## 部署方式

### AWS Lambda + Docker/ECR

1. **登入 ECR**
   ```bash
   aws ecr get-login-password --region ap-northeast-1 | \
     docker login --username AWS --password-stdin \
     <account-id>.dkr.ecr.ap-northeast-1.amazonaws.com
   ```

2. **建置並推送映像**
   ```bash
   docker build -t mm-madam .
   docker tag mm-madam:latest <account-id>.dkr.ecr.ap-northeast-1.amazonaws.com/mm-madam:latest
   docker push <account-id>.dkr.ecr.ap-northeast-1.amazonaws.com/mm-madam:latest
   ```

3. **更新 Lambda 函數**
   ```bash
   aws lambda update-function-code \
     --function-name <function-name> \
     --image-uri <account-id>.dkr.ecr.ap-northeast-1.amazonaws.com/mm-madam:latest
   ```

或使用部署腳本：
```bash
./aws-docker.sh
```

### 設定 Lambda Streaming（選用）

```bash
# 啟用 Streaming 模式
aws lambda update-function-url-config \
  --function-name <function-name> \
  --invoke-mode RESPONSE_STREAM

# 設定環境變數
aws lambda update-function-configuration \
  --function-name <function-name> \
  --environment 'Variables={AWS_LWA_INVOKE_MODE=RESPONSE_STREAM,...}'
```

## 專案結構

```
mm-madam-aws/
├── main.py              # FastAPI 應用程式主檔案
├── pyproject.toml       # Python 依賴與專案設定（uv）
├── uv.lock              # 依賴鎖定檔
├── .python-version      # Python 版本
├── Dockerfile           # Docker 建置檔
├── aws-docker.sh        # AWS 部署腳本
├── test-frontend/       # 測試前端（需 ENABLE_FRONTEND=true）
│   ├── index.html       # 測試頁面
│   ├── chat-widget.js   # 前端聊天視窗元件
│   └── *.png            # 圖示資源
├── knowledge/           # Help Center 知識庫
│   └── <date>/
│       ├── zh-tw/       # 繁體中文文章
│       ├── zh-cn/       # 簡體中文文章
│       └── en-001/      # 英文文章
└── .env                 # 環境變數（不納入版控）
```

## 依賴套件

依賴定義於 `pyproject.toml`，使用 [uv](https://docs.astral.sh/uv/) 管理。

- `fastapi` - Web 框架
- `mangum` - AWS Lambda 適配器
- `uvicorn` - ASGI 伺服器
- `google-genai` - Google Gemini AI SDK
- `httpx` - 非同步 HTTP 客戶端
- `pyjwt` - JWT 驗證
- `markdown` - Markdown 轉 HTML
- `markdownify` - HTML 轉 Markdown
- `gdown` - Google Drive 下載工具
- `python-dotenv` - 環境變數管理
