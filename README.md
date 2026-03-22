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

这个项目包含两个Python脚本，用于将 OpenWebUI 的AI对话导出为 Hexo 博客文章。

### 环境配置

两个脚本都需要配置文件。复制模板并填写你的OpenWebUI API Token：

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

### 脚本1: publish_chat.py（推荐日常使用）

**功能**: 交互式选择并发布对话

**特点**:
- 自动列出最近的15个对话
- 支持编号选择，有预览功能
- 显示消息数量和内容摘要
- 支持日期覆盖（可用于发布历史对话）
- 可选自动git提交

**用法**:

```bash
# 交互模式 - 列出对话供选择
cd scripts
python3 publish_chat.py

# 直接模式 - 用对话ID直接导出
python3 publish_chat.py <chat_id>

# 指定日期覆盖（用于发布历史对话）
python3 publish_chat.py --date 2026-01-15 <chat_id>
```

**交互流程示例**:
```
🔍 获取最近对话...

📅 最近对话:
   1. 如何优化Python性能                     (2026-02-22)
   2. React组件设计讨论                      (2026-02-21)
   3. Docker部署问题                         (2026-02-20)

选择编号 [1-3]: 1

🔄 获取对话详情: 如何优化Python性能...

📝 预览: 如何优化Python性能
   消息数: 12

  用户: 最近在处理大数据集时遇到性能问题...
  AI: 可以从以下几个方面优化: 1.使用pandas的向量化操作...

📅 对话日期: 2026-02-22
   (直接回车使用对话日期，输入日期如 2026-01-15 覆盖)
日期: 

确认发布? [Y/n]: y

📝 生成博客文章...
✅ 已生成: source/_posts/2026-02-22-如何优化Python性能.md

提交到git? [Y/n]: y
✅ 已提交
```

### 脚本2: convert_chat.py（直接导出）

**功能**: 通过对话ID直接导出为博客文章

**特点**:
- 简单直接，适合知道chat_id的情况
- 快速导出，无交互确认
- 兼容原有使用习惯

**用法**:

```bash
cd scripts
python3 convert_chat.py <chat_id> [output_file]

# 示例
python3 convert_chat.py 1d75ee42-34a1-444f-be66-2866a80fdae1
```

### 对话显示效果

生成的博客文章使用对话框样式展示，包含以下特性：

- **区分角色**: 用户消息（右侧紫色）、AI消息（左侧灰色）
- **显示模型**: AI消息会标注使用的模型名称
- **支持分支**: 对话分叉（fork）会以折叠方式展示，可展开查看
- **代码高亮**: 支持代码块的语法高亮
- **过滤思考**: 自动移除AI的思考过程（`<details type="reasoning">`）
- **使用对话时间**: 文章日期使用对话实际时间，而非今天

### 安全提示

⚠️ **重要**: `scripts/.env` 文件包含敏感信息，已被 `.gitignore` 忽略，**不要提交到GitHub**。

```bash
# 安全做法
git add scripts/convert_chat.py scripts/publish_chat.py
git add scripts/.env.example  # 只提交模板，不提交真实.env
git commit -m "feat: add chat publishing scripts"
```

---

## 目录结构

```
.
├── scripts/              # Python工具脚本
│   ├── convert_chat.py   # 直接导出脚本
│   ├── publish_chat.py   # 交互式导出脚本
│   ├── .env.example      # 配置文件模板
│   └── .env              # 实际配置文件（gitignore）
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
