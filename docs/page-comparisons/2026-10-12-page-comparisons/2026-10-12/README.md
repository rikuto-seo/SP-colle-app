# 各ページの修正前・修正後比較

修正前：GitHub origin/main `94de73f96b151f2e84a40be528f3db4883522949`。修正後：撮影時のローカルのテンプレート・静的ファイル。

各比較PNGにはスマホとPCの全ページ撮影を収録。左が修正前、中央が修正後、右が差分です。橙色は描画差分で、要素の移動や高さの変化も含みます。PC欄は50%縮小、元スクリーンショットはbefore/afterに原寸保存。

実テンプレートに同一サンプルデータを渡して撮影しています。本番サイト・本番データの撮影ではありません。新しいトレードページは実ルートとメモリ内SQLiteを使用。認証・分析・決済の外部通信を停止。ライトモードの初期表示を対象とし、モーダルや各操作後の状態は含みません。

処理中ページは外部認証・決済を実行せず初期状態で撮影。共通レイアウトと部品テンプレートは個別ページとして撮影せず各ページ内に含めます。

[修正前の全ページ一覧](overview-before.png) / [修正後の全ページ一覧](overview-after.png)

全44ページ、比較画像44枚。新規7ページ。

- [写真を追加](comparisons/01-add.png)
- [管理・写真DB](comparisons/02-admin--photos.png)
- [パスワード変更](comparisons/03-change_password.png)
- [退会確認](comparisons/04-confirm_delete_account.png)
- [退会の最終確認](comparisons/05-confirm_delete_final.png)
- [ダッシュボード](comparisons/06-dashboard.png)
- [プロフィール編集](comparisons/07-edit_profile.png)
- [ログイン処理中](comparisons/08-finish-login.png)
- [初回登録](comparisons/09-first-register.png)
- [利用グループ設定](comparisons/10-force_select_group.png)
- [写真を減らす](comparisons/11-give.png)
- [グループ](comparisons/12-group.png)
- [アイコン設定](comparisons/13-icon_setting.png)
- [コレクション](comparisons/14-index.png)
- [特定商取引法に基づく表記](comparisons/15-legal.png)
- [ログイン](comparisons/16-login.png)
- [トップ・サービス紹介](comparisons/17-lp.png)
- [未所持の写真](comparisons/18-missing.png)
- [マイページ](comparisons/19-mypage.png)
- [決済処理中](comparisons/20-payment_success.png)
- [プライバシーポリシー](comparisons/21-privacy.png)
- [生写真DB・衣装詳細](comparisons/22-public--costume_detail.png)
- [生写真DB・衣装一覧](comparisons/23-public--costume_list.png)
- [生写真DB・グループ一覧](comparisons/24-public--index.png)
- [生写真DB・メンバー衣装](comparisons/25-public--member_costumes.png)
- [新規登録](comparisons/26-register.png)
- [グループ選択](comparisons/27-select_group.png)
- [コレクション・非公開](comparisons/28-shared_collection--not_shared.png)
- [公開コレクション](comparisons/29-shared_collection--shared_view.png)
- [公開コレクション統計](comparisons/30-shared_stats.png)
- [統計](comparisons/31-stats.png)
- [利用規約](comparisons/32-terms.png)
- [トレード・募集作成](comparisons/33-trade--editor.png)（新規）
- [トレード・募集詳細](comparisons/34-trade--listing.png)（新規）
- [トレード・自分の募集](comparisons/35-trade--mine.png)（新規）
- [トレード・募集一覧](comparisons/36-trade--search.png)（新規）
- [トレード・取引詳細](comparisons/37-trade--transaction.png)（新規）
- [トレード・取引一覧](comparisons/38-trade--transactions.png)（新規）
- [料金プラン](comparisons/39-upgrade.png)
- [欲しい写真を追加](comparisons/40-want--add.png)
- [欲しい写真](comparisons/41-want--index.png)
- [公開の欲しい写真・マッチング](comparisons/42-want--public_base.png)
- [欲しい写真・非公開](comparisons/43-want--public_private.png)
- [欲しい写真の公開設定](comparisons/44-want--share_setting.png)（新規）

検証：全ページのHTML描画と画像ファイルの読取を確認。修正前の利用グループ設定ページでは既存JavaScriptのnull参照エラーを記録しています（画面撮影は完了）。詳細はcapture-results.json。
