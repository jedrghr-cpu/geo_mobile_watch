# geo-mobile-watch

ゲオモバイル（UQ mobile代理店）の **キャンペーン新着** と **端末価格・在庫変動** を GitHub Actions で自動監視し、
新キャンペーン検知時に **X投稿・YouTube概要欄/コミュニティ投稿の下書き** を自動生成するツール。
py_ahamo_used_iphone と同じ GitHub Actions + GitHub Pages 構成。

## 動作イメージ

1. 定時実行（JST 9:00 / 12:00 / 17:00 / 21:00）＋手動実行（Actions → Run workflow）
2. `/campaign/` 一覧の新着URLを検知 → 個別ページから訴求ポイント抽出
3. 下書き生成
   - リポジトリSecretsに `ANTHROPIC_API_KEY` があれば **Claude APIで自動生成**（関西弁X本文・標準語YouTube文、スタイルルール込み）
   - なければ **テンプレ差し込み**で生成
4. 出力先
   - `docs/drafts/YYYYMMDD_スラッグ.md` … 下書き本体（GitHub Pagesで閲覧可）
   - **GitHub Issue** を自動作成 … 下書き全文入り。Issueの通知メールがそのまま新着アラートになる
5. 端末一覧の MNP価格・中古価格・在庫を state.json と比較し、変動日を記録して `docs/index.html` に表として出力

※ X本文にはリンクを入れず、リンクはリプ用に分離（本文リンク禁止ルール準拠）。
※ リンクは全て `【アフィリンクに差し替え】` プレースホルダ。投稿前に媒体別リンク台帳の該当列と差し替えること。

## セットアップ

1. GitHubで新規リポジトリ作成（例: `geo_mobile_watch`）、このフォルダ一式をpush
2. **Settings → Pages** → Source: `Deploy from a branch`、Branch: `main` / `/docs`
3. （任意）**Settings → Secrets and variables → Actions** → `ANTHROPIC_API_KEY` を登録
   - モデルは環境変数 `CLAUDE_MODEL` で変更可（デフォルト: claude-sonnet-4-6）
4. **Actions タブで workflow を有効化** → 「Run workflow」で初回実行
   - 初回は既存キャンペーンを「記録のみ」して通知しない（過去分でIssueが大量に立つのを防止）
5. 2回目以降、新着があれば Issue＋下書きが生成される

## ローカルテスト

```bash
pip install -r requirements.txt
python scripts/watch.py
# docs/index.html をブラウザで開いて確認
```

## カスタマイズポイント

- 監視URL・注記文言・プレースホルダ: `scripts/watch.py` 冒頭の定数
- 実行時刻: `.github/workflows/watch.yml` の cron（UTC指定なので JST−9時間）
- 下書きの文体ルール: `drafts_claude()` 内のプロンプト / `drafts_template()` のテンプレ

## 注意

- スクレイピング先のHTML構造が変わるとパーサ調整が必要（`parse_campaigns` / `parse_devices`）
- 生成された数字・期間・条件は **必ず公式ページで最終確認**してから投稿すること（景表法・誤情報対策）
- X への自動投稿はしない設計（凍結リスク回避のため、投稿は人間が実施）
