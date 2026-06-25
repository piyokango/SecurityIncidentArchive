# SecurityIncidentArchive Dashboard

このディレクトリはGitHub Pagesで公開する静的ダッシュボードです。

## セキュリティ上の方針

- 外部JavaScript、外部CSS、外部フォント、トラッキングを使用しません。
- ブラウザ側で外部APIを呼び出さず、GitHub Actionsで生成したJSONだけを読み込みます。
- アーカイブ本文や上場判定データはHTMLとして挿入せず、DOM APIの `textContent` 相当で表示します。
- Content Security Policyを `index.html` に設定し、外部リソース読み込みやフォーム送信を抑制します。
- 原典URLは `http` / `https` のみリンク化し、外部リンクには `rel="noopener noreferrer"` を付与します。
- 上場判定はJPXの東証上場銘柄一覧との正規化一致に限定します。一致しない場合は `未確認` と表示し、非上場とは断定しません。

## 集計単位

`scripts/build_dashboard_data.py` は、1ファイルごとの `releases` と、`事案ID` ごとにまとめた `incidents` の両方を生成します。

`# 公表概要` に同じ `事案ID` を指定した複数ファイルは、事案単位では1件として集計されます。`事案ID` がないファイルは、従来どおり1ファイルを1事案として扱います。

```markdown
# 公表概要
- 不正アクセスによる個人情報漏えいのおそれについて
- 2026年6月10日
- 株式会社Example
- https://example.co.jp/news/...
- 事案ID: example-2026-001
- 公表種別: 初報
```

## 事案グルーピング候補

`scripts/build_incident_group_candidates.py` は、未グループの公表リリースから同一事案の可能性がある候補を抽出します。

`.github/workflows/incident-group-candidates.yml` は、手動実行または週次実行で候補レポートを作成し、候補がある場合は `[dashboard] 事案グルーピング候補` というIssueを作成または更新します。候補は自動確定ではありません。

## 画面操作

- 集計単位: 公表リリース単位 / 事案単位
- 推移粒度: 年別 / 月別 / 日別
- 表示件数: 50件 / 100件
- JPX業種: 上場企業に付与されたJPXの33業種区分で絞り込み

## 上場判定データ

`scripts/build_listed_companies.py` がJPXの東証上場銘柄一覧を取得し、`data/jpx_listed_companies.json` を生成します。

`scripts/build_dashboard_data.py` はこのJSONを読み込み、各公表情報に以下を付与します。

- `listedStatus`: `上場` / `未確認` / `対象外`
- `securitiesCode`: 証券コード
- `listedMarket`: 市場区分
- `listedIndustry33`: JPXの33業種区分
- `listedIndustry17`: JPXの17業種区分
- `listedName`: JPX上の銘柄名
- `listedConfidence`: 判定信頼度

一覧表では出典や判定信頼度の長い説明文は表示せず、CSVには監査用に出力します。

表記揺れ、子会社名、持株会社名などで手動補正が必要な場合は `data/listed_company_overrides.json` に登録します。

## ローカル確認

```bash
python -m pip install xlrd==2.0.1
python scripts/build_listed_companies.py
python scripts/build_dashboard_data.py
python -m http.server 8000 -d docs
```

ブラウザで `http://localhost:8000/` を開いて確認します。
