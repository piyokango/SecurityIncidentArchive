# SecurityIncidentArchive Dashboard

このディレクトリはGitHub Pagesで公開する静的ダッシュボードです。

## セキュリティ上の方針

- 外部JavaScript、外部CSS、外部フォント、トラッキングを使用しません。
- 依存関係はPython標準ライブラリとGitHub公式Actionsのみです。
- アーカイブ本文や企業情報補正データはHTMLとして挿入せず、DOM APIの `textContent` 相当で表示します。
- Content Security Policyを `index.html` に設定し、外部リソース読み込みやフォーム送信を抑制します。
- 原典URLは `http` / `https` のみリンク化し、外部リンクには `rel="noopener noreferrer"` を付与します。
- 業種・業態・企業規模は自動断定せず、`data/organization_overrides.json` に登録された手動確認済みデータのみを反映します。

## 企業情報の補正

`data/organization_overrides.json` に組織名完全一致で補正データを登録できます。

```json
{
  "organizations": {
    "株式会社Example": {
      "industry": "情報通信業",
      "businessType": "クラウドサービス",
      "companySize": "中小企業",
      "source": "手動確認",
      "confidence": "high",
      "note": "法人名完全一致。確認日: 2026-06-25"
    }
  }
}
```

未登録の組織はダッシュボード上で `未登録` と表示されます。

## 未登録組織の確認Issue

`scripts/build_organization_candidates.py` は、アーカイブ内の組織名と `data/organization_overrides.json` を比較し、未登録組織の確認候補を生成します。

GitHub Actions の `Organization metadata candidates` は、毎週または手動実行でこの候補を生成し、`[dashboard] 未登録組織の企業情報確認` Issueを1件だけ作成または更新します。

このIssueに掲載されるテンプレート候補を確認し、必要な組織だけ `data/organization_overrides.json` に反映してください。

ローカル生成:

```bash
python scripts/build_organization_candidates.py --output-json data/organization_candidates.json --output-md data/organization_candidates.md
```

## ローカル確認

```bash
python scripts/build_dashboard_data.py
python -m http.server 8000 -d docs
```

ブラウザで `http://localhost:8000/` を開いて確認します。
