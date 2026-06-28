# yu-chun-kit.github.io

基于 [Hexo](https://hexo.io/) 的个人博客，使用 [landscape](https://github.com/hexojs/hexo-theme-landscape) 主题。

🔗 **访问地址**: https://yu-chun-kit.github.io

---

## 开发命令

```bash
# 安装依赖
pnpm install

# 本地开发服务器
pnpm run server

# 构建（生成到 ./public）
pnpm run build

# 清理缓存
pnpm run clean
```

---

## AI对话导出工具

这个项目包含一个 UV 管理的 Python CLI，用于将 OpenWebUI 的 AI 对话导出为 Hexo 博客文章。

### 环境配置

工具需要配置文件。复制模板并填写你的 OpenWebUI API Token：

```bash
cp scripts/.env.example scripts/.env
```

编辑 `scripts/.env`：

```bash
# OpenWebUI API base URL (no trailing slash)
OPENWEBUI_API_BASE=http://localhost:3000/api/v1

# Your OpenWebUI API token
# Get it from: OpenWebUI → Settings → Account → API Key
OPENWEBUI_API_TOKEN=your_api_token_here
```

### 推荐用法: chatblog CLI

**功能**: 列出、预览、选择并生成对话文章

**特点**:
- 使用 UV 管理 Python 依赖
- 自动列出 OpenWebUI 对话
- 支持分页、限制数量、编号选择、预览
- 显示消息数、分支数、模型、来源日期
- 生成 Hexo `layout: dialog` 静态文章
- 默认不保存 raw JSON，也不自动 git commit

**用法**:

```bash
# 安装/同步 Python 依赖
uv sync

# 列出最近10个对话
uv run chatblog list --limit 10 --page 1

# 查看单个对话摘要
uv run chatblog show <chat_id>

# 通过对话ID生成文章
uv run chatblog publish <chat_id>

# 指定日期覆盖（用于发布历史对话）
uv run chatblog publish <chat_id> --date 2026-01-15

# 交互模式 - 列出、选择、预览、确认生成
uv run chatblog interactive
```

### 兼容旧入口

旧入口仍然保留在 `tools/` 下，但现在只是调用新的 `chatblog` 核心逻辑：

```bash
# 交互模式
python tools/publish_chat.py

# 直接模式
python tools/publish_chat.py <chat_id>

# 日期覆盖
python tools/publish_chat.py --date 2026-01-15 <chat_id>

# 原 convert_chat.py 用法
python tools/convert_chat.py <chat_id> [output_file]
```

### 对话显示效果

生成的博客文章使用对话框样式展示，包含以下特性：

- **区分角色**: 用户消息（右侧蓝色）、AI消息（左侧浅色）
- **显示模型**: AI消息会标注使用的模型名称
- **支持分支**: 对话分叉（fork）会以折叠方式展示，可展开查看
- **显示元数据**: 来源、对话日期、模型、消息数、分支数
- **代码高亮**: 支持代码块的语法高亮
- **过滤思考**: 自动移除AI的思考过程（`<details type="reasoning">`）
- **使用对话时间**: 文章日期使用对话实际时间，而非今天

### 安全提示

⚠️ **重要**: `scripts/.env` 文件包含敏感信息，已被 `.gitignore` 忽略，**不要提交到GitHub**。

```bash
# 安全做法
git add tools/convert_chat.py tools/publish_chat.py
git add src/chatblog pyproject.toml uv.lock
git add scripts/.env.example  # 只提交模板，不提交真实.env
git commit -m "feat: add chatblog OpenWebUI publisher"
```

---

## 目录结构

```
.
├── tools/                # Python工具兼容入口
│   ├── convert_chat.py   # 旧入口兼容包装
│   └── publish_chat.py   # 旧入口兼容包装
├── scripts/              # Hexo脚本目录，只放Hexo可加载的脚本或配置模板
│   ├── .env.example      # 配置文件模板
│   └── .env              # 实际配置文件（gitignore）
├── src/
│   └── chatblog/         # OpenWebUI -> Hexo CLI核心
├── tests/                # Python测试
├── source/
│   ├── _posts/           # 博客文章
│   └── css/
│       └── dialog.css    # 对话样式
├── _config.yml           # Hexo配置
└── ...
```

---

## 部署

本项目使用 GitHub Actions 自动部署：
- 推送到 `master` 分支自动触发构建和部署
- 无需手动操作
