# yu-chun-kit.github.io

[繁體中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

以 [Hexo](https://hexo.io/) 建置的個人部落格，使用 Landscape 主題，發佈網址為
<https://yu-chun-kit.github.io>。

## 技術棧

- Hexo 8.1.1 與 `hexo-theme-landscape`
- Node.js（GitHub Actions 使用 Node.js 20）
- npm 或 pnpm 管理 JavaScript 相依套件
- 選用的 `chatblog` Python CLI（Python 3.11 以上），可將 OpenWebUI 或公開 Gemini
  對話轉成 Hexo 文章

## 本機開發

先安裝 Node.js 20，再安裝相依套件：

```bash
pnpm install          # 或：npm install
pnpm run server       # 或：npm run server，開啟 http://localhost:4000
pnpm run build        # 或：npm run build，輸出到 ./public
pnpm run clean        # 或：npm run clean，清理 Hexo 快取與輸出
```

`public/` 是建置產物，已列入 `.gitignore`，不應提交。

若要使用 `chatblog`，請先準備 Python 3.11 以上與 [uv](https://docs.astral.sh/uv/)，
再執行 `uv sync`。將 `scripts/.env.example` 複製為 `scripts/.env`，填入
`OPENWEBUI_API_BASE` 與 `OPENWEBUI_API_TOKEN` 後，可使用：

```bash
uv run chatblog list --limit 10 --page 1
uv run chatblog show <chat_id>
uv run chatblog publish <chat_id>
uv run chatblog interactive
uv run chatblog import-gemini https://gemini.google.com/share/<share_id>
uv run chatblog import-gemini https://share.gemini.google/<short_id> --force-assets
```

`python -m chatblog`（或 `uv run python -m chatblog`）與 `chatblog` 指令等價。Gemini
匯入需要 Playwright 的 Chromium：`uv run playwright install chromium`。

若 OpenWebUI 的 API token 過期或不想申請 token，可直接讀取 NAS 上的資料庫
（與 `openwebui-local-reader` 相同做法：SSH 進容器後唯讀查詢 SQLite）：

```bash
uv run chatblog publish <chat_id> --source auto    # 先試 API，401 就改用本機資料庫
uv run chatblog publish <chat_id> --source ssh     # 走 johnsons_nas → docker exec
uv run chatblog publish <chat_id> --source sqlite  # 讀本機／SMB 的 webui.db
uv run chatblog list --limit 20 --source ssh
```

可用 `CHATBLOG_OWUI_SSH_HOST`、`CHATBLOG_OWUI_CONTAINER`、`CHATBLOG_OWUI_DB_PATH`、
`CHATBLOG_OWUI_LOCAL_DB`、`CHATBLOG_OWUI_UPLOADS` 覆寫預設值。

### Studio 自動分類

執行 `uv run chatblog gui`，開啟本機的 Chatblog Studio。於 `.env` 或 `scripts/.env`
設定 `GEMINI_API_KEY` 後，自動分類會使用 `gemini-decision-1`：

```dotenv
GEMINI_API_KEY=你的金鑰
CHATBLOG_CLASSIFIER=gemini
CHATBLOG_DECISION_BASE_URL=https://generativelanguage.googleapis.com/v1beta
CHATBLOG_DECISION_MODEL=gemini-decision-1
```

使用反代時，將 `CHATBLOG_DECISION_BASE_URL` 改成自己的反代網址。也接受以
`/v1beta/openai` 結尾的網址，程式會改用同一反代的原生 `/v1beta/decisions` 路徑。
修改 `.env` 後重啟 Studio；在「設定」可看到目前分類模型，並用「測試連線」驗證。
勾選對話後按「自動分類」即可產生標籤。設定金鑰後，分類會將標題、metadata 和
最多約 9,000 字元的對話節錄傳給模型，沿用先判定領域、再細分主題的兩批問題。
既有標籤要重新勾選分類才會更新。沒有金鑰或模型請求失敗時會使用關鍵詞規則。

若要切回原本的 OpenJev，設定 `CHATBLOG_CLASSIFIER=openjev`，並保留原本的
`OPENJEV_API_KEY`（或 `CODIV_API_KEY`）等設定。金鑰請只放 `.env`，不要填進範例檔。

### chatblog 的對話匯入流程

- OpenWebUI 對話以 Markdown 儲存，由 `chatblog.render` 以 markdown-it 轉成 HTML。
- Gemini 分享頁是 Angular 應用，需以 Playwright 抓取；答案的 HTML 只保留
  「對話用得到」的標籤（標題、清單、表格、粗體、程式碼），citation chip、
  follow-up 按鈕等 UI 雜訊會被移除（見 `chatblog.sanitize`）。
- 圖片附件下載到 `source/images/<provider>/<chat_id>/`；重複匯入會沿用既有檔案，
  加上 `--force-assets` 才會重新下載。
- 分支（OpenWebUI 的重新生成／編輯訊息）會在分歧點就地插入提示，其餘分支收合成
  `分支 N/總數` 區塊；若一段對話有多個根節點（編輯使用者訊息造成），額外的樹會以
  「另一段對話」收合呈現，不會漏掉訊息。
- 產生的文章使用 `layout: dialog` 與 `/css/dialog.css`，以對話泡泡形式呈現。

`chatblog` 會從工作目錄往上尋找含 `_config.yml` 與 `package.json` 的目錄作為 repo
根目錄，也可用 `CHATBLOG_REPO_ROOT`、`CHATBLOG_POSTS_DIR` 環境變數覆寫。

## 目錄結構

```text
.
├── source/_posts/              # Markdown 文章
├── source/css/                 # 文章或網站樣式
├── source/images/              # 圖片資產
├── src/chatblog/               # 對話匯入 CLI 的 Python 原始碼
├── tools/                      # 舊版 CLI 入口包裝
├── tests/                      # chatblog 測試
├── themes/                     # 專案內主題檔案
├── _config.yml                 # Hexo 設定
├── package.json                # Node.js 腳本與相依套件
└── .github/workflows/pages.yml # GitHub Pages 工作流程
```

## 撰寫與貢獻流程

1. 在 `source/_posts/` 新增 Markdown 檔，使用 front matter 設定 `title`、`date`、
   `tags` 與 `categories`。
2. 執行 `pnpm run server`（或 `npm run server`）預覽，並以 `pnpm run build`（或
   `npm run build`）確認可產生網站。
3. 提交變更並推送至 `master`，讓部署工作流程處理後續作業。

修改 `chatblog` 時，可用 `uv run pytest` 執行 `tests/` 中的測試；請勿提交含有真實
Token 的 `scripts/.env`。

## 部署

推送至 `master` 會觸發 `.github/workflows/pages.yml`：工作流程使用 Node.js 20、執行
`npm install` 與 `npm run build`，再將 `public/` 上傳並部署至 GitHub Pages。

## 授權

授權資訊請參閱 [LICENSE](LICENSE)。
