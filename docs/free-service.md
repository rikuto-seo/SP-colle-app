# 完全無料サービスへの変更

全ユーザーが3グループ・所持登録・詳細統計・画像保存・QR共有・希望リスト・トレードを無料で利用できます。保存容量と登録数のプラン上限はありません。1枚10MBのアップロード上限、ファイル検証、ログイン、所有者確認、管理者権限、CSRF、トレードの在庫整合性は維持しています。

新規登録はユーザー名・パスワードと任意のアイコン設定を終えるとコレクションに移動します。グループの事前選択はありません。初期表示は乃木坂46で、登録後に自由に切り替えられます。既存ユーザーの表示グループは保持します。

既存DBのプラン値やStripe契約情報は、既存契約の照合と終了処理のために残しています。機能やアクセス権はそれらの値に依存せず、DBマイグレーションなしで既存アカウントも全機能を利用できます。旧料金・グループ選択URLはホームまたはマイページへ転送し、課金開始・再開APIおよび旧Webhookは410を返します。

## 本番切り替え

ローカルの変更だけではStripe側の既存契約は終了しません。既存契約がある場合は無料版公開時に停止します。以下のコマンドはFirebaseやapp.pyを起動せず、DBに登録済みの契約のみを確認します。契約の顧客ID、ユーザーIDのメタデータ（存在する場合）、旧プランの価格IDを照合します。

```powershell
# 照合のみ（契約・DBの変更なし）
& myenv/Scripts/python.exe -X utf8 tools/retire_legacy_subscriptions.py --env-file .env
# 照合した契約を即時終了（追加請求や返金は作成しない）
& myenv/Scripts/python.exe -X utf8 tools/retire_legacy_subscriptions.py --env-file .env --apply
```

本番の環境変数がすでに設定されている場合、`--env-file`は不要です。Stripe側で終了を確認してからDBの契約状態を更新し、既に終了済みの契約は再度解約しません。失敗がある場合は非ゼロの終了コードを返します。実際の本番契約に対する実行は、このローカル変更作業では行っていません。

無料版公開時に、Stripe Dashboardで旧Webhook・Payment Links・公開中のCheckoutセッションを停止し、未回収の請求書や進行中の決済がないか確認してください。DB未登録の契約や以前の請求・返金は、このスクリプトの処理対象に含みません。不要になったStripe用環境変数は契約終了後に削除できます。

## 表示・ポリシー

LPとメニュー・マイページから料金プランや容量上限の表示を取り除きました。規約は無料提供とユーザー間交換の費用負担を明記し、プライバシーポリシーから新規決済の利用目的を削除しました。旧契約がある場合の終了処理・問い合わせ・保存の扱いは残しています。

`/legal`は運営情報・利用料金の案内として継続し、販売・有償サービス・カード登録・自動請求を行わないことを明記しています。消費者庁の説明では、通信販売は商品・権利の販売または有償の役務提供を対象としています。この説明に合わせ、従来の有料販売条件を無料サービスの案内に変更しました。[消費者庁：通信販売広告Q&A](https://www.no-trouble.caa.go.jp/qa/advertising.html)

無料サービスでも収集情報と利用目的の案内を維持しています。[個人情報保護委員会：通則編](https://www.ppc.go.jp/personalinfo/legal/guidelines_tsusoku/)

契約終了時のAPIはStripe公式仕様の`invoice_now=false`・`prorate=false`を使用します。[Stripe：契約終了API](https://docs.stripe.com/api/subscriptions/cancel)

## 検証

```powershell
& myenv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_*.py'
& myenv/Scripts/python.exe -X utf8 tests/check_design_browser.py --browser 'C:/Program Files/Google/Chrome/Application/chrome.exe' --only collection,mypage,lp,login,register,setup,terms,privacy,legal
```

テストはメモリ内SQLite、認証・画像保存のモック、画面用サンプルデータを使用します。本番DB・本番Stripe・Firebaseには接続しません。

確認結果：テスト35件成功。主要9ページをスマホ・PC・ダークモードで確認し、JavaScriptエラーと横方向のはみ出しはありませんでした。確認用の画像は保管せず、再実行時は一時フォルダに出力します。
