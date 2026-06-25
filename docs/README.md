# SecurityIncidentArchive Dashboard

このディレクトリはGitHub Pagesで公開する静的ダッシュボードです。

## セキュリティ上の方針

- 外部JavaScript、外部CSS、外部フォント、トラッキングを使用しません。
- ブラウザ側で外部APIを呼び出さず、GitHub Actionsで生成したJSONだけを読み込みます。
- アーカイブ本文や上場判定データはHTMLとして挿入せず、DOM APIの `textContent` 相当で表示します。
- Content Security Policyを `index.html` に設定し、外部リソース読み込みやフォーム送信を抑制します。
- 原典URLは `http` / `https` のみリンク化し、外部リンクには `rel="noopener noreferrer"` を付与します。
- 上場判定はJPXの東証上場銘柄一覧との正規化一致に限定します。一致しない場合は `未確認` と表示し、非上場とは断定しません。

## 上場判定データ

`scripts/build_listed_companies.py` がJPXの東証上場銘柄一覧を取得し、`data/jpx_listed_companies.json` を生成します。

`scripts/build_dashboard_data.py` はこのJSONを読み込み、各公表情報に以下を付与します。

- `listedStatus`: `上場` / `未確認` / `対象外`
- `securitiesCode`: 証券コード
- `listedMarket`: 市場区分
- `listedName`: JPX上の銘柄名
- `listedConfidence`: 判定信頼度

表記揺れ、子会社名、持株会社名などで手動補正が必要な場合は `data/listed_company_overrides.json` に登録します。

## ローカル確認

```bash
python -m pip install xlrd==2.0.1
python scripts/build_listed_companies.py
python scripts/build_dashboard_data.py
python -m http.server 8000 -d docs
```

ブラウザで `http://localhost:8000/` を開いて確認します。
