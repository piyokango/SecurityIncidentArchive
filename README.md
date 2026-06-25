# 国内インシデント公表アーカイブ
- このリポジトリでは、日本国内におけるインシデント関連の公表資料を保存します。
- 保存対象はpiyokangoが確認した公開情報のうち、不正アクセスやシステム障害に起因または関連したインシデント（事故）公表の内容です。
- 続報等で事実確認なしや影響なしと公表される事例も含めているため、このアーカイブに掲載された組織でインシデントの発生を必ずしも示すものではありません。本文を必ず確認してください。
- 保存対象にはメールアドレス、電話番号は含めません。また全文を抜粋しない場合があります。

# このアーカイブに関する連絡先
- Bluesky: @piyokango.bsky.social
- X: @piyokango

## ダッシュボード

GitHub Pages向けの静的ダッシュボードを `docs/` 配下に生成します。

- 生成スクリプト: `scripts/build_dashboard_data.py`
- 公開対象: `docs/`
- データ: `docs/data/incidents.json`
- 企業情報補正データ: `data/organization_overrides.json`
- 公開URL: GitHub Pages有効化後、`https://piyokango.github.io/SecurityIncidentArchive/`

ローカル確認:

```bash
python scripts/build_dashboard_data.py
python -m http.server 8000 -d docs
```

GitHub Pagesは `.github/workflows/pages.yml` により、`main` へのpushまたは手動実行で更新されます。

### 業種・業態・企業規模の登録

業種・業態・企業規模は、企業名だけから自動断定せず、`data/organization_overrides.json` に登録された手動確認済みデータだけをダッシュボードに表示します。未登録の組織は `未登録` と表示されます。

登録例:

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

同名企業や表記揺れがある場合は、`confidence` を `low` または `needs-review` とし、`note` に判断理由を残してください。
