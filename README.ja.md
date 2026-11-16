# yu-chun-kit.github.io

[繁體中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

[Hexo](https://hexo.io/) と Landscape テーマで生成する個人ブログです。
公開サイトは <https://yu-chun-kit.github.io> です。

## 技術スタック

- `hexo-theme-landscape` を使う Hexo 8.1.1
- Node.js（GitHub Actions では Node.js 20 を使用）
- JavaScript 依存関係の管理は npm または pnpm
- 任意の `chatblog` Python CLI（Python 3.11 以上）：OpenWebUI または公開 Gemini
  の会話を Hexo の記事へ変換

## ローカル開発

Node.js 20 を用意し、`package.json` のスクリプトを実行します。

```bash
pnpm install          # または npm install
pnpm run server       # または npm run server; http://localhost:4000
pnpm run build        # または npm run build; ./public に出力
pnpm run clean        # または npm run clean; Hexo のキャッシュ/出力を削除
```

`public/` は生成物で Git の対象外です。コミットしないでください。

`chatblog` を使う場合は Python 3.11 以上と [uv](https://docs.astral.sh/uv/) を用意し、
`uv sync` を実行します。`scripts/.env.example` を `scripts/.env` にコピーし、
`OPENWEBUI_API_BASE` と `OPENWEBUI_API_TOKEN` を設定してから次のコマンドを使います。

```bash
uv run chatblog list --limit 10 --page 1
uv run chatblog show <chat_id>
uv run chatblog publish <chat_id>
uv run chatblog interactive
uv run chatblog import-gemini https://gemini.google.com/share/<share_id>
```

## リポジトリ構成

```text
.
├── source/_posts/              # Markdown 記事
├── source/css/                 # 記事/サイトのスタイル
├── source/images/              # 画像アセット
├── src/chatblog/               # 会話 CLI の Python ソース
├── tools/                      # 旧 CLI のエントリーポイント
├── tests/                      # chatblog のテスト
├── themes/                     # リポジトリ内のテーマファイル
├── _config.yml                 # Hexo 設定
├── package.json                # Node.js スクリプトと依存関係
└── .github/workflows/pages.yml # GitHub Pages ワークフロー
```

## 記事作成とコントリビューション

1. `source/_posts/` に Markdown ファイルを追加し、front matter の `title`、`date`、
   `tags`、`categories` などを設定します。
2. `pnpm run server`（または `npm run server`）で確認し、`pnpm run build`（または
   `npm run build`）で本番ビルドを検証します。
3. 変更をコミットして `master` へ push し、デプロイワークフローに処理させます。

`chatblog` を変更した場合は `uv run pytest` で `tests/` のテストを実行できます。
API トークンを含む実際の `scripts/.env` はコミットしないでください。

## デプロイ

`master` への push で `.github/workflows/pages.yml` が起動します。Node.js 20 を使い、
`npm install` と `npm run build` を実行した後、`public/` をアップロードして GitHub Pages
へデプロイします。

## ライセンス

ライセンスは [LICENSE](LICENSE) を参照してください。
