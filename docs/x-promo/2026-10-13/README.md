# SP Colle — X宣伝用のページ別比較画像

44ページ、各1枚。PNG / 1600 × 1200 px / 4:3。Xへの投稿は実施していません。

各画像は左が修正前、右が修正後。右端にそのページの変更点を3つ掲載しています。
修正前のない新規7ページでは、左に「修正前にはなかったページ」と明示しています。
画面の文字やデータは描き直さず、指定されたスマホ幅390pxのスクリーンショットをHTML/CSSで配置し、上部844px相当を掲載しました。
PC画像と全ページの原寸画像は元のフォルダに残っています。

素材: `C:\Users\Teikyo\Desktop\my-all-directory\application-directory\sakamichi_photo_app\docs\page-comparisons\2026-10-12-page-comparisons\2026-10-12`
撮影時点: 2026-10-12。サンプルデータを使用した比較画面です。
後日の完全無料化、種類表記・並び順の修正は素材に含まれていないため、画像内でこれらの変更を宣伝していません。
利用グループ設定・グループ選択・料金プラン・決済処理中・特商法の5ページは、その後変更された旧画面の参考比較と明示しています。

一覧: [index.html](index.html) / [overview.png](overview.png)
`images/` に投稿用PNG、`layouts/` に各画像の再編集可能なHTML、`manifest.json` に文言・元画像のSHA-256を保存。
ZIPには投稿用PNG・一覧・README・manifestを収録しています。

## ページ一覧

- [01. 写真を追加](images/01-add.png)
- [02. 管理・写真DB](images/02-admin--photos.png)
- [03. パスワード変更](images/03-change_password.png)
- [04. 退会確認](images/04-confirm_delete_account.png)
- [05. 退会の最終確認](images/05-confirm_delete_final.png)
- [06. ダッシュボード](images/06-dashboard.png)
- [07. プロフィール編集](images/07-edit_profile.png)
- [08. ログイン処理中](images/08-finish-login.png)
- [09. 初回登録](images/09-first-register.png)
- [10. 利用グループ設定](images/10-force_select_group.png)（旧画面の参考比較）
- [11. 写真を減らす](images/11-give.png)
- [12. グループ](images/12-group.png)
- [13. アイコン設定](images/13-icon_setting.png)
- [14. コレクション](images/14-index.png)
- [15. 特定商取引法に基づく表記](images/15-legal.png)（旧画面の参考比較）
- [16. ログイン](images/16-login.png)
- [17. トップ・サービス紹介](images/17-lp.png)
- [18. 未所持の写真](images/18-missing.png)
- [19. マイページ](images/19-mypage.png)
- [20. 決済処理中](images/20-payment_success.png)（旧画面の参考比較）
- [21. プライバシーポリシー](images/21-privacy.png)
- [22. 生写真DB・衣装詳細](images/22-public--costume_detail.png)
- [23. 生写真DB・衣装一覧](images/23-public--costume_list.png)
- [24. 生写真DB・グループ一覧](images/24-public--index.png)
- [25. 生写真DB・メンバー衣装](images/25-public--member_costumes.png)
- [26. 新規登録](images/26-register.png)
- [27. グループ選択](images/27-select_group.png)（旧画面の参考比較）
- [28. コレクション・非公開](images/28-shared_collection--not_shared.png)
- [29. 公開コレクション](images/29-shared_collection--shared_view.png)
- [30. 公開コレクション統計](images/30-shared_stats.png)
- [31. 統計](images/31-stats.png)
- [32. 利用規約](images/32-terms.png)
- [33. トレード・募集作成](images/33-trade--editor.png)（新規）
- [34. トレード・募集詳細](images/34-trade--listing.png)（新規）
- [35. トレード・自分の募集](images/35-trade--mine.png)（新規）
- [36. トレード・募集一覧](images/36-trade--search.png)（新規）
- [37. トレード・取引詳細](images/37-trade--transaction.png)（新規）
- [38. トレード・取引一覧](images/38-trade--transactions.png)（新規）
- [39. 料金プラン](images/39-upgrade.png)（旧画面の参考比較）
- [40. 欲しい写真を追加](images/40-want--add.png)
- [41. 欲しい写真](images/41-want--index.png)
- [42. 公開の欲しい写真・マッチング](images/42-want--public_base.png)
- [43. 欲しい写真・非公開](images/43-want--public_private.png)
- [44. 欲しい写真の公開設定](images/44-want--share_setting.png)（新規）

## 再作成

リポジトリのルートで `myenv/Scripts/python.exe tools/create_x_promo_images.py` を実行。
必要環境: Playwright、Pillow、Chrome、Meiryo。
素材フォルダが変わった場合は `--source`、出力先は `--output` で指定できます。
