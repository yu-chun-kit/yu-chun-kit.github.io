# AGENTS.md - Hexo Blog Repository Guidelines

## Repository Overview

This is a **Hexo-based static blog/site** deployed to GitHub Pages. The repository uses GitHub Actions for automated deployment on pushes to the `master` branch.

**Site URL**: https://yu-chun-kit.github.io  
**Framework**: Hexo v8.1.1  
**Theme**: landscape (default)  
**Package Manager**: pnpm (preferred) or npm

---

## Build & Development Commands

### Essential Commands

```bash
# Install dependencies
pnpm install
# OR
npm install

# Build the site (generates to ./public)
pnpm run build
npm run build
hexo generate

# Start local development server (http://localhost:4000)
pnpm run server
npm run server
hexo server

# Clean generated files and cache
pnpm run clean
npm run clean
hexo clean

# Create new post
hexo new post "My Post Title"
hexo new page "My Page Title"
```

### Testing

**Hexo content has no test suite**, but the `chatblog` conversation importer does
(see the chatblog section below):

```bash
uv run pytest                    # all chatblog tests
uv run pytest tests/test_render.py
# From WSL with the repo's Windows venv:
./.venv/Scripts/pytest.exe -q
```

---

## Code Style Guidelines

### Markdown Content (Blog Posts)

Located in `source/_posts/`

**Front-matter format:**
```yaml
---
title: Post Title
date: 2024-01-15 10:30:00
tags:
  - tag1
  - tag2
categories:
  - category1
---
```

**Content guidelines:**
- Use ATX-style headers (`# Header`) not Setext
- Fenced code blocks with language specifier: ```javascript
- Use relative links for internal content
- Keep lines under 100 characters when possible
- Use `<!-- more -->` for manual excerpt break, or rely on auto-excerpt (150 chars)

### Configuration Files

**`_config.yml` (main config):**
- 2-space indentation
- Use single quotes for strings with special characters
- Date format: `YYYY-MM-DD`
- URL: `https://yu-chun-kit.github.io`

**Theme config (`_config.landscape.yml`):**
- Keep landscape theme customizations here
- Leave empty if using defaults

### File Naming & Organization

```
source/
  _posts/           # Blog posts: YYYY-MM-DD-title.md
  about/            # Static pages
  images/           # Static assets
  CNAME             # Custom domain (if any)

themes/             # Custom themes (if not using npm package)
scaffolds/          # Post/page templates
public/             # Generated site (gitignored)
backup/             # Legacy files (to be removed)
```

### Git Workflow

**Branching:**
- `master`: Production branch, triggers GitHub Actions deployment
- Use feature branches for significant changes: `git checkout -b feature/description`

**Commit messages:**
```
type: brief description

Longer explanation if needed.
```

Types: `feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `post:`

**Important:** Never commit the `public/` folder (it's in .gitignore and generated during CI)

---

## chatblog (conversation → Hexo post pipeline)

`src/chatblog/` is a small Python CLI (Python 3.11+, `uv`) that turns AI
conversations into dialog-style posts. It lives outside the Hexo build; it only
writes Markdown into `source/_posts/` and images into `source/images/`.

```bash
uv sync                                   # install (Windows venv: .venv/Scripts/)
uv run playwright install chromium        # required for Gemini shares
uv run chatblog list --limit 10           # OpenWebUI chats
uv run chatblog publish <chat_id>         # OpenWebUI chat → post (+ images)
uv run chatblog import-gemini <share_url> # public Gemini share → post
uv run chatblog interactive               # pick + preview + publish
uv run pytest                             # tests in tests/
```

`python -m chatblog` is equivalent to the `chatblog` entry point. Legacy wrappers
`tools/convert_chat.py` and `tools/publish_chat.py` still work.

**How a post is produced**

- OpenWebUI chats come from `GET /api/v1/chats/{id}`; message content is Markdown.
- Gemini share pages are fully client-rendered (the HTML shell contains no
  conversation data), so `chatblog.gemini` scrapes the DOM with Playwright and
  keeps the response markup it finds.
- `chatblog.sanitize` reduces Gemini HTML to a safe whitelist (headings, lists,
  tables, code, bold…), dropping citation chips, follow-up buttons and icons.
- `DialogNode.content_format` is `markdown` (OpenWebUI) or `html` (Gemini);
  `chatblog.render` renders Markdown with markdown-it (`html=False`) and
  sanitizes HTML before embedding it.
- Branches: the first child of a node is the inline main line, the others become
  collapsed `<details>` blocks labelled `分支 N/總數` at the divergence point.
  Keep those labels unique — nested divergences must not both say "分支 2".
- Images land in `source/images/<provider>/<chat_id>/image-NN.ext`; re-running
  reuses existing files unless `--force-assets` is passed.

**Testing the renderer without live data**: build a `Conversation` in Python
(`tests/test_render.py::build_wide_branch_conversation` is a good template),
`render_hexo_post()` it, then `hexo generate` and open the page. Verifying the
built HTML (`public/.../index.html`) catches Hexo/marked interactions that unit
tests cannot.

### Studio (local GUI: pick chats → write posts)

```bash
uv run chatblog gui          # http://127.0.0.1:8765 (alias: chatblog studio)
uv run chatblog gemini-login # open the managed Chrome profile on Gemini
```

The studio merges OpenWebUI (API → NAS SQLite over SSH) and Gemini (managed
Chrome profile) into one list, sorted by last modified, and writes the selected
conversations with the same renderer as the CLI. State lives in `.chatblog/`
(gitignored): `index.json` is the published-post ledger, `catalog.json` the last
source listing, `settings.json` the GUI preferences.

- **Already-uploaded detection** comes from the ledger *and* from
  `source_provider` / `source_chat_id` front matter, so posts written before the
  studio existed show up as published on first launch. A title or `updated_at`
  change marks a row `有更新` instead of hiding it.
- **Fine-grained tags** are produced by typed System One questions
  (`src/chatblog/taxonomy.py`: domain → subdomain → concept → genre → depth →
  language → sensitivity → flags). The backend is a Jev-compatible endpoint
  (Codiv's `https://api.codiv.ai`, `openjev-latest`, free 100M input tokens; or
  a self-hosted `openjev`). Without a key the classifier falls back to keyword
  rules, which are coarser but still show a domain/concept.
- **Ask in two batches, not one.** OpenJev is a 26B diffusion model: a single
  request carrying all eleven questions plus 80 subdomain and 47 concept options
  answered "nietzsche / anxiety" for a programming chat and drifted towards
  `philosophy` for everything abstract. `classify.py` therefore asks
  domain/genre/depth/language/sensitivity first, then offers only the chosen
  domain's subdomains and concepts (plus the noul flags). The state is sent
  twice (~7.6k tokens per chat, ≈13k chats on the free quota) and the labels
  become specific enough to read without opening the chat.
- Overriding the model per call is possible; `GET /v1/models` lists
  `openjev-latest`, `laya-1.0`, `verdict-1.4`, `clm-v0.1`, `jevk5-0.3`,
  `clef-flash-1.0` — the small ones are fine for yes/no questions only.
- **Front matter only gets coarse tags** (`AI对话`, provider, domain); the fine
  tags stay in the studio and in `.chatblog/`. Keep it that way unless the tag
  pages are meant to explode.
- **Gemini needs a login once.** Google's device-bound sessions and App-Bound
  Encryption make a copied Chrome profile log out, and Chrome 136+ refuses
  `--remote-debugging-port` on the default profile. The studio therefore uses
  `%LOCALAPPDATA%\chatblog\chrome-profile`: press 登入 Gemini, sign in in the
  window that opens, then scan. `chatblog.gemini_web` documents the details.
  The signed-out Gemini shell is *not* a redirect to accounts.google.com — it
  renders normally with `[data-test-id="signed-out-disclaimer"]`, so treat that
  marker (not the URL) as the login test.
- **The Gemini list comes from the app's own RPC, not the sidebar.**
  `gemini_web.list_conversations` POSTs `MaZiqc` to
  `/_​BardChatUi/data/batchexecute` with `at=window.WIZ_global_data.SNlM0e`
  and reads rows shaped `["c_<id>", title, …, [epoch, nanos]]`. That yields up to
  100 conversations **with real timestamps**; the sidebar only ever exposed ~30
  rows and no dates at all (the 2026 UI has no "Today/Yesterday" headings — every
  row landed in one group called 全部). The DOM scrape stays as a fallback.
- **Never read `user-query` with `innerText` alone.** In a background tab and
  before first paint `innerText` is empty, which silently dropped the user's
  question from the post (a 6-message chat rendered 5 bubbles). `_FETCH_JS` now
  falls back to `textContent`, and `fetch_conversation` only emits nodes that
  actually carry text or images.
- **Links open server-side** (`/api/open`) because Chrome is inside TunnlTo's
  tunnel and cannot reach the LAN `192.168.128.111`: `auto` sends LAN links to
  Firefox and everything else to Chrome.
- **Background jobs** run one at a time (browser contention); the GUI polls
  `/api/jobs/<id>`. Publish results update the ledger immediately.
- **Run the server detached, not as a managed job.** Killing a managed job that
  carries the same command line (`serve(port=8765)`) can take down the instance
  you just started (observed once: exit 255 right after a restart). Use
  `nohup .venv/Scripts/python.exe -u -c "..." > .chatblog/server.log 2>&1 &`
  and check `curl http://127.0.0.1:8765/` instead of trusting the job status.
- The HTTP server binds `127.0.0.1` only and every `/api` call except
  `/api/bootstrap` needs the per-session `X-Studio-Token`.
- Add extra topics without touching code by dropping
  `.chatblog/taxonomy.json` (`{"concepts": {"id": {"label", "description",
  "parent", "keywords"}}}`); built-ins cannot be removed that way.

### OpenWebUI access (this machine)

| Endpoint | Notes |
| --- | --- |
| `http://192.168.128.111:3000` | NAS OpenWebUI directly on the LAN; API base `/api/v1` |
| `https://openwebui.lan` | Same NAS behind a local reverse proxy; self-signed certificate chain, so `curl` needs `-k` and Playwright needs `ignore_https_errors=True` |
| `https://chat.openearth.me` | Public hostname behind **Cloudflare Zero Trust Access**; anonymous requests 302 to `openearthai.cloudflareaccess.com`. Needs an Access service token or a browser session—a plain bearer token will not get through |

- Credentials live in `scripts/.env` (`OPENWEBUI_API_BASE`, `OPENWEBUI_API_TOKEN`);
  it is gitignored. Never print or commit tokens.
- **Check token expiry before debugging anything else.** OpenWebUI API keys from
  Settings → Account → API Key are long-lived, but session JWTs carry an `exp`
  claim (~28 days) and fail with `401 Unauthorized` once stale. Decode the
  middle JWT segment to read `exp` — do not guess.
- Network path: this repo is edited from WSL, where traffic egresses through the
  WSL NAT and is **not** affected by Windows split-tunnel (TunnlTo) rules.
  Playwright launches a Windows browser (`chrome.exe`, which is in the TunnlTo
  allow-list), so Gemini scraping may leave through a different route than
  `curl`/`httpx` running inside WSL.

### Reading OpenWebUI chats without an API token

`chatblog.owui_local` mirrors the approach of the existing
`openwebui-local-reader` tool (`E:\code\ai\202606\open-webui-plugin\openwebui-local-reader`):
read the SQLite database directly instead of going through the API.

```bash
uv run chatblog publish <chat_id>                 # auto: API, then local db
uv run chatblog publish <chat_id> --source ssh    # force the NAS database
uv run chatblog publish <chat_id> --source sqlite # a local/SMB webui.db copy
uv run chatblog list --limit 20 --source ssh      # list without the API
uv run chatblog show <chat_id> --source auto
```

- SSH mode pipes a read-only program through
  `ssh johnsons_nas /usr/local/bin/docker exec -i open-webui python -`; it only
  issues `SELECT`s (`PRAGMA query_only=ON`) and writes nothing on the NAS. The
  Windows OpenSSH alias `johnsons_nas` (192.168.128.111:9090) must exist.
- Attached images are found through the `file` table (`path` →
  `/app/backend/data/uploads/...`), read inside the container and handed over as
  `data:` URLs; `chatblog.assets` then stores them under
  `source/images/<provider>/<chat_id>/image-NN.ext`. `--source sqlite` can only
  read them when `CHATBLOG_OWUI_UPLOADS` points at a copy of `uploads/`.
- Overrides: `CHATBLOG_OWUI_SSH_HOST`, `CHATBLOG_OWUI_CONTAINER`,
  `CHATBLOG_OWUI_DB_PATH`, `CHATBLOG_OWUI_LOCAL_DB`, `CHATBLOG_OWUI_UPLOADS`.
- **A chat can contain several roots.** OpenWebUI creates a second root when a
  *user* message is edited, so walking only `conversation.root_id` silently drops
  messages. `render.render_conversation_body` renders the extra trees as
  collapsed `另一段對話 N/M` blocks — keep that behaviour when refactoring.
- Real-data quirks worth remembering: a single node can hold 10+ regeneration
  branches (a 13-way fork exists in "🌤️ 天气预报表"), and branch previews must
  never leak raw HTML — use `render.preview_text`.

### Private / sensitive posts

Posts the author does not want published are listed in `.gitignore`
(e.g. `source/_posts/2026-09-24-解析黄果短剧的黑灰产模式.md`) together with their
`source/images/<provider>/<chat_id>/` folder. CI builds from the repository, so an
ignored post stays local-only. Follow that pattern instead of deleting content.

---

## GitHub Actions Deployment

**Workflow**: `.github/workflows/pages.yml`

Triggers automatically on push to `master`:
1. Installs Node.js 20
2. Caches and installs npm dependencies
3. Builds site with `npm run build`
4. Deploys `./public` folder to GitHub Pages

**Manual deployment (if Actions fails):**
```bash
# Not recommended - prefer fixing the Actions workflow
hexo generate
hexo deploy  # Uses hexo-deployer-git (configured in _config.yml)
```

---

## Dependencies & Plugins

**Core Hexo packages:**
- `hexo`: Framework
- `hexo-generator-*`: Archive, category, index, tag pages
- `hexo-renderer-ejs`, `hexo-renderer-marked`: Template & Markdown rendering
- `hexo-renderer-stylus`: CSS preprocessing
- `hexo-server`: Dev server

**Custom plugins:**
- `hexo-auto-excerpt`: Truncates posts on homepage (150 chars configured)
- `hexo-deployer-git`: Git-based deployment (legacy, prefer Actions)

**To add/remove plugins:**
```bash
pnpm add hexo-plugin-name
pnpm remove hexo-plugin-name
```

---

## Common Tasks

### Update site metadata
Edit `_config.yml`:
- `title`: Site title
- `subtitle`: Tagline
- `description`: Meta description
- `author`: Your name
- `url`: https://yu-chun-kit.github.io

### Add new blog post
```bash
hexo new post "My New Article"
# Edit source/_posts/My-New-Article.md
```

### Change theme
1. Install new theme: `pnpm add hexo-theme-<name>`
2. Update `_config.yml`: `theme: <name>`
3. Copy theme's sample config to `_config.<name>.yml`

### Update Node version
Modify `.github/workflows/pages.yml`:
```yaml
- name: Use Node.js 20
  uses: actions/setup-node@v4
  with:
    node-version: '20'  # Change this
```

---

## Troubleshooting

**Build fails in Actions:**
- Check `npm install` output for dependency conflicts
- Ensure no syntax errors in `_config.yml`
- Verify all posts have valid front-matter

**Local server won't start:**
```bash
hexo clean
pnpm install
hexo server
```

**Theme changes not reflecting:**
- Run `hexo clean` before `hexo server`
- Check that theme is properly installed in `node_modules/`

---

## Notes for AI Agents

1. **Tests**: the Hexo site has no test suite, but the `chatblog` tool does —
   run `uv run pytest` (or `./.venv/Scripts/pytest.exe` when working from WSL,
   where `.venv/` is a Windows virtualenv). Always run it after touching
   `src/chatblog/`.
2. **No linting**: Hexo doesn't enforce code style on content; maintain consistent Markdown
3. **Content-focused**: Most changes are adding/editing Markdown files in `source/_posts/`
4. **Deployment is automatic**: Push to `master` triggers the workflow
5. **Use pnpm**: Preferred over npm when available
6. **Be careful with `_config.yml`**: YAML syntax errors break the entire build
7. **Read the chatblog section above** before importing conversations, and check
   `scripts/.env` token expiry first if OpenWebUI returns `401`.
8. **Sensitive posts**: add the post path *and* its image folder to `.gitignore`
   instead of deleting or publishing it; ignored posts never reach CI.
9. **Verify rendering, not just tests**: after generating a post, run
   `./node_modules/.bin/hexo generate` and inspect the built HTML (or screenshot
   it) — Markdown/HTML interactions only show up there.
10. **Line endings**: the working tree is CRLF while the git index is LF, so
    `git status` shows many files as modified. Do not "fix" that wholesale and do
    not commit those unrelated diffs.
