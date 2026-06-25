# 国内インシデント公表アーカイブ
- このリポジトリでは、日本国内におけるインシデント関連の公表資料を保存します。
- 保存対象はpiyokangoが確認した公開情報のうち、不正アクセスやシステム障害に起因または関連したインシデント（事故）公表の内容です。
- 続報等で事実確認なしや影響なしと公表される事例も含めているため、このアーカイブに掲載された組織でインシデントの発生を必ずしも示すものではありません。本文を必ず確認してください。
- 保存対象にはメールアドレス、電話番号は含めません。また全文を抜粋しない場合があります。

## ダッシュボード
ここに格納している情報を参照できるダッシュボードを以下で参照することができます。

https://piyokango.github.io/SecurityIncidentArchive/

### 業種・業態・企業規模の確認運用

ダッシュボードの業種・業態・企業規模は、`data/organization_overrides.json` に登録された手動確認済みデータを表示します。

未登録組織の確認候補は、GitHub Actions の `Organization metadata candidates` により、毎週または手動実行で `[dashboard] 未登録組織の企業情報確認` というIssueとして作成・更新されます。

運用手順:

1. `Actions` から `Organization metadata candidates` を手動実行する、または定期実行を待つ。
2. 作成・更新された `[dashboard] 未登録組織の企業情報確認` Issueを確認する。
3. Issue内の上位候補や確認用ファイルを見て、必要な組織の業種・業態・企業規模を確認する。
4. 確認できた内容を `data/organization_overrides.json` に追記する。
5. `main` に反映すると、ダッシュボード生成時に `docs/data/incidents.json` へ取り込まれます。

登録例:

```json
{
  "organizations": {
    "株式会社Example": {
      "industry": "情報通信業",
      "businessType": "クラウドサービス",
      "companySize": "中小企業",
      "source": "公式サイト",
      "confidence": "high",
      "note": "会社概要ページで確認。確認日: 2026-06-25"
    }
  }
}
```

同名企業や表記揺れがある場合は、`confidence` を `needs-review` のままにし、`note` に判断理由を残してください。

# このアーカイブに関する連絡先
- Bluesky: @piyokango.bsky.social
- X: @piyokango
