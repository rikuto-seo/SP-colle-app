# SP Colle 新UI・GitHub版の比較

左：GitHub origin/main `94de73f96b151f2e84a40be528f3db4883522949`。右：2026年10月14日の作業中UI。
画像にもファイル名にも連番を付けていません。スマホ画像は1000×1080px、PC画像は1600×690px。
スマホは幅390pxの先頭844px、PCは幅1440pxの先頭900pxを掲載。全体の原寸スクリーンショットはraw/before・raw/afterに保存しています。
実テンプレートを同じサンプルデータで描画。本番アカウントや本番DBは使わず、認証・広告・分析・決済の外部通信を停止しています。新しいトレードはメモリ内SQLiteと実ルートで表示しています。
旧版にはないページは「変更前にはない画面」、廃止された料金・グループ設定ページは「この画面は廃止しました」と表示しています。
旧版で発生するJavaScriptエラー・横幅超過はraw/capture-results.jsonに記録し、旧コードを書き換えずに撮影しています。

[比較画像の一覧](index.html) / [一覧画像](overview.png)

## 各ページ

- [写真を追加](mobile\add.png) / [PC](desktop\add.png)
- [管理・写真DB](mobile\admin--photos.png) / [PC](desktop\admin--photos.png)
- [パスワード変更](mobile\change_password.png) / [PC](desktop\change_password.png)
- [退会確認](mobile\confirm_delete_account.png) / [PC](desktop\confirm_delete_account.png)
- [退会の最終確認](mobile\confirm_delete_final.png) / [PC](desktop\confirm_delete_final.png)
- [ダッシュボード](mobile\dashboard.png) / [PC](desktop\dashboard.png)
- [プロフィール編集](mobile\edit_profile.png) / [PC](desktop\edit_profile.png)
- [ログイン処理中](mobile\finish-login.png) / [PC](desktop\finish-login.png)
- [初回登録](mobile\first-register.png) / [PC](desktop\first-register.png)
- [利用グループ設定](mobile\force_select_group.png) / [PC](desktop\force_select_group.png)
- [写真を減らす](mobile\give.png) / [PC](desktop\give.png)
- [グループ](mobile\group.png) / [PC](desktop\group.png)
- [アイコン設定](mobile\icon_setting.png) / [PC](desktop\icon_setting.png)
- [コレクション](mobile\index.png) / [PC](desktop\index.png)
- [特定商取引法に基づく表記](mobile\legal.png) / [PC](desktop\legal.png)
- [ログイン](mobile\login.png) / [PC](desktop\login.png)
- [トップ・サービス紹介](mobile\lp.png) / [PC](desktop\lp.png)
- [未所持の写真](mobile\missing.png) / [PC](desktop\missing.png)
- [マイページ](mobile\mypage.png) / [PC](desktop\mypage.png)
- [決済処理中](mobile\payment_success.png) / [PC](desktop\payment_success.png)
- [プライバシーポリシー](mobile\privacy.png) / [PC](desktop\privacy.png)
- [生写真DB・衣装詳細](mobile\public--costume_detail.png) / [PC](desktop\public--costume_detail.png)
- [生写真DB・衣装一覧](mobile\public--costume_list.png) / [PC](desktop\public--costume_list.png)
- [生写真DB・グループ一覧](mobile\public--index.png) / [PC](desktop\public--index.png)
- [生写真DB・メンバー衣装](mobile\public--member_costumes.png) / [PC](desktop\public--member_costumes.png)
- [新規登録](mobile\register.png) / [PC](desktop\register.png)
- [グループ選択](mobile\select_group.png) / [PC](desktop\select_group.png)
- [コレクション・非公開](mobile\shared_collection--not_shared.png) / [PC](desktop\shared_collection--not_shared.png)
- [公開コレクション](mobile\shared_collection--shared_view.png) / [PC](desktop\shared_collection--shared_view.png)
- [公開コレクション統計](mobile\shared_stats.png) / [PC](desktop\shared_stats.png)
- [統計](mobile\stats.png) / [PC](desktop\stats.png)
- [利用規約](mobile\terms.png) / [PC](desktop\terms.png)
- [トレード・募集作成](mobile\trade--editor.png) / [PC](desktop\trade--editor.png)
- [トレード・募集詳細](mobile\trade--listing.png) / [PC](desktop\trade--listing.png)
- [トレード・自分の募集](mobile\trade--mine.png) / [PC](desktop\trade--mine.png)
- [トレード・募集一覧](mobile\trade--search.png) / [PC](desktop\trade--search.png)
- [トレード・取引詳細](mobile\trade--transaction.png) / [PC](desktop\trade--transaction.png)
- [トレード・取引一覧](mobile\trade--transactions.png) / [PC](desktop\trade--transactions.png)
- [料金プラン](mobile\upgrade.png) / [PC](desktop\upgrade.png)
- [欲しい写真を追加](mobile\want--add.png) / [PC](desktop\want--add.png)
- [欲しい写真](mobile\want--index.png) / [PC](desktop\want--index.png)
- [公開の欲しい写真・マッチング](mobile\want--public_base.png) / [PC](desktop\want--public_base.png)
- [欲しい写真・非公開](mobile\want--public_private.png) / [PC](desktop\want--public_private.png)
- [欲しい写真の公開設定](mobile\want--share_setting.png) / [PC](desktop\want--share_setting.png)
