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

**No test framework is currently configured.** This is a content-focused static site. If adding tests in the future:

- Install test runner: `pnpm add -D vitest` or `pnpm add -D jest`
- Run single test: `pnpm vitest run <test-file>`
- Run all tests: `pnpm test`

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

1. **No tests to run**: This is a static site generator, not an application with test suites
2. **No linting**: Hexo doesn't enforce code style on content; maintain consistent Markdown
3. **Content-focused**: Most changes are adding/editing Markdown files in `source/_posts/`
4. **Deployment is automatic**: Push to `master` triggers the workflow
5. **Use pnpm**: Preferred over npm when available
6. **Be careful with `_config.yml`**: YAML syntax errors break the entire build
