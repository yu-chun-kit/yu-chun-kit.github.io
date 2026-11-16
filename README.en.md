# yu-chun-kit.github.io

[繁體中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

A personal blog generated with [Hexo](https://hexo.io/) and the Landscape theme.
The published site is <https://yu-chun-kit.github.io>.

## Stack

- Hexo 8.1.1 with `hexo-theme-landscape`
- Node.js (the GitHub Actions workflow uses Node.js 20)
- npm or pnpm for JavaScript dependencies
- Optional `chatblog` Python CLI (Python 3.11+) for turning OpenWebUI or public Gemini
  conversations into Hexo posts

## Local development

Install Node.js 20, then install dependencies and use the scripts defined in `package.json`:

```bash
pnpm install          # or: npm install
pnpm run server       # or: npm run server; http://localhost:4000
pnpm run build        # or: npm run build; output goes to ./public
pnpm run clean        # or: npm run clean; remove Hexo cache/output
```

`public/` is generated output and is ignored by Git; do not commit it.

To use `chatblog`, install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then run
`uv sync`. Copy `scripts/.env.example` to `scripts/.env` and set
`OPENWEBUI_API_BASE` and `OPENWEBUI_API_TOKEN` before using the CLI:

```bash
uv run chatblog list --limit 10 --page 1
uv run chatblog show <chat_id>
uv run chatblog publish <chat_id>
uv run chatblog interactive
uv run chatblog import-gemini https://gemini.google.com/share/<share_id>
```

## Repository layout

```text
.
├── source/_posts/              # Markdown posts
├── source/css/                 # Post/site styles
├── source/images/              # Image assets
├── src/chatblog/               # Python source for the conversation CLI
├── tools/                      # Legacy CLI entry-point wrappers
├── tests/                      # chatblog tests
├── themes/                     # In-repository theme files
├── _config.yml                 # Hexo configuration
├── package.json                # Node.js scripts and dependencies
└── .github/workflows/pages.yml # GitHub Pages workflow
```

## Content and contribution workflow

1. Add a Markdown file under `source/_posts/` with front matter such as `title`, `date`,
   `tags`, and `categories`.
2. Preview with `pnpm run server` (or `npm run server`) and verify a production build with
   `pnpm run build` (or `npm run build`).
3. Commit and push to `master` so the deployment workflow can process the change.

When changing `chatblog`, run `uv run pytest` for the tests in `tests/`. Never commit a real
`scripts/.env` containing an API token.

## Deployment

Pushing to `master` triggers `.github/workflows/pages.yml`. It uses Node.js 20, runs
`npm install` and `npm run build`, then uploads `public/` and deploys it to GitHub Pages.

## License

See [LICENSE](LICENSE) for licensing information.
