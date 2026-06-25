# SecurityIncidentArchive Dashboard

このディレクトリはGitHub Pagesで公開する静的ダッシュボードです。

## セキュリティ上の方針

- 外部JavaScript、外部CSS、外部フォント、トラッキングを使用しません。
- 依存関係はPython標準ライブラリとGitHub公式Actionsのみです。
- アーカイブ本文はHTMLとして挿入せず、DOM APIの `textContent` 相当で表示します。
- Content Security Policyを `index.html` に設定し、外部リソース読み込みやフォーム送信を抑制します。
- 原典URLは `http` / `https` のみリンク化し、外部リンクには `rel="noopener noreferrer"` を付与します。

## ローカル確認

```bash
python scripts/build_dashboard_data.py
python -m http.server 8000 -d docs
```

ブラウザで `http://localhost:8000/` を開いて確認します。
