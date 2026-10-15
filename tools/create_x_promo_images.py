"""Render faithful before/after screenshots into page-specific X promo cards.

The original screenshots are placed unchanged in HTML/CSS layouts. This does
not load the app, access production data, or regenerate the captured screens.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import zipfile

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/page-comparisons/2026-10-12-page-comparisons/2026-10-12"
OUTPUT = ROOT / "docs/x-promo/2026-10-13"
SIZE = (1600, 1200)

# Captions refer to the supplied 10/12 screenshots, not subsequent changes.
# Each item is: headline, three (short title, concrete visible change) pairs.
COPY = {
    "add": ("写真の登録を、\nすっきりした画面で。", [
        ("入力欄が、すぐそこに", "大きなヘッダーと余白を整理。画面上部から入力欄が見える構成へ。"),
        ("読みやすいフォーム", "文字・枠線・余白を統一。メンバー、衣装、種類を順に確認。"),
        ("よく使う機能へ", "スマホ下部にナビを追加。登録画面から一覧へ移動しやすく。")]),
    "admin--photos": ("管理画面も、\nひと目でわかりやすく。", [
        ("項目をひとまとめに", "グループ切替と写真の追加項目を、共通デザインの画面に整理。"),
        ("入力のまとまりを明確に", "メンバーや衣装の入力欄を、淡い背景と余白で区切る構成へ。"),
        ("色と文字を統一", "水色・青中心の画面から、落ち着いた緑と読みやすい文字へ。")]),
    "change_password": ("大切な設定を、\n迷わず変更。", [
        ("フォームを見やすく", "現在・新しいパスワードの入力欄を、統一した文字と枠線で表示。"),
        ("操作の色を整理", "青い変更ボタンから緑へ。戻るボタンは控えめな枠線に。"),
        ("共通ナビを追加", "ロゴ付きヘッダーとスマホ下部ナビで、ほかの機能へ移動。")]),
    "confirm_delete_account": ("大切な確認を、\n読みやすく。", [
        ("確認欄が上部に", "大きなヘッダーをコンパクトに。退会前の説明と入力欄が見やすく。"),
        ("注意と操作を区別", "削除操作は赤、キャンセルは白。文章とボタンの余白も統一。"),
        ("画面全体を統一", "アカウント設定も、ほかの画面と同じ文字・背景・ナビへ。")]),
    "confirm_delete_final": ("最後の確認まで、\nわかりやすく。", [
        ("警告をカードに集約", "最終確認の説明と操作を、まとまりのある白いカードで表示。"),
        ("選択肢を見分けやすく", "赤い削除ボタンと白いキャンセルボタンを、上下に整理。"),
        ("ヘッダーをコンパクトに", "共通ロゴと小さなメニューを採用。確認内容が上部から見える。")]),
    "dashboard": ("コレクション管理の\n入口を、すっきり。", [
        ("やることが見つかる", "所持写真、追加、減らすなどを、余白のある機能カードに整理。"),
        ("見出しをコンパクトに", "グループ名と画面の目的を、上部にまとめて表示。"),
        ("ナビも同じ使い心地に", "共通ヘッダーと下部ナビを追加。各ページの見た目を統一。")]),
    "edit_profile": ("プロフィール編集を、\nすっきり見やすく。", [
        ("項目の区切りを明確に", "基本情報・SNS情報の見出しを、読みやすい文字と余白で整理。"),
        ("入力欄を統一", "細い枠線と淡い背景を採用。ラベルと入力欄のまとまりが明確に。"),
        ("ほかの画面へ移動", "ヘッダーを小さくし、スマホ下部に共通ナビを追加。")]),
    "finish-login": ("待っている間も、\n統一された画面に。", [
        ("処理状況をシンプルに", "ログイン処理中の表示を、余白のある落ち着いたカードに。"),
        ("ブランドを統一", "水色の大きなヘッダーから、SP Colleのロゴ付きヘッダーへ。"),
        ("フッターも整理", "ページ下部のリンクを、共通の文字と配置でまとめる構成へ。")]),
    "first-register": ("はじめの登録を、\nすっきりした画面で。", [
        ("登録欄が上部に", "大きなヘッダーを小さくし、初回登録フォームを見やすい位置へ。"),
        ("読みやすい入力欄", "ユーザー名とパスワードの文字・枠線・余白を統一。"),
        ("次の操作を見つけやすく", "青いボタンから、ほかの画面と同じ緑のボタンへ。")]),
    "force_select_group": ("設定画面も、\n落ち着いたデザインへ。", [
        ("選択ボタンを整理", "色付きの大きな面から、白を基調にした枠線付きの選択肢へ。"),
        ("設定操作を見分ける", "設定ボタンは緑、補助操作は淡い色に。色の役割を整理。"),
        ("説明を読みやすく", "ヘッダーと余白を小さくし、見出し・説明・選択肢をまとめる構成へ。")]),
    "give": ("枚数の調整を、\n見やすいフォームで。", [
        ("フォームが上部に", "大きな見出しの余白を整理。メンバー・衣装の選択欄がすぐ見える。"),
        ("操作をひとまとめに", "種類・枚数の入力欄を、統一した文字と白いカードで表示。"),
        ("下部ナビを追加", "一覧・追加・トレード・マイページへ、画面下部から移動。")]),
    "group": ("グループの入口を、\nもっとすっきり。", [
        ("見出しと説明を整理", "中央の大きなタイトルから、左揃えのグループ名と説明へ。"),
        ("ボタンの見た目を統一", "青いボタンから、緑と枠線のボタンへ。操作の並びもコンパクトに。"),
        ("よく使う機能へ", "共通ヘッダーと下部ナビで、コレクション管理へ移動。")]),
    "icon_setting": ("自分のアイコンを、\n見やすく設定。", [
        ("設定項目が上部に", "大きなヘッダーと見出しの余白を整理。現在のアイコンがすぐ見える。"),
        ("操作の色を統一", "アップロードは緑、削除は赤。カードの枠線と余白も統一。"),
        ("ナビを追加", "スマホ下部から一覧・追加・トレード・マイページへ移動。")]),
    "index": ("推しの一枚を、\nひと目で見渡す。", [
        ("検索欄を折りたたみ", "常時表示の検索フォームを、開閉できる「検索・並び順」に集約。"),
        ("写真の見せ方を選べる", "「情報付き／画像のみ」を追加。名前や所持状況が読みやすいカードに。"),
        ("追加・移動が身近に", "見出し横に追加ボタン、スマホ下部に共通ナビを配置。")]),
    "legal": ("サービスの案内も、\n読みやすい画面に。", [
        ("見出しを見やすく", "大きなヘッダーを小さくし、案内のタイトルと本文を上部へ。"),
        ("本文の文字を統一", "ほかの画面と同じ書体・色・行間で、長い説明を読みやすく。"),
        ("ページ全体を統一", "ロゴ付きヘッダーと共通フッターで、サービス内の見た目を揃える。")]),
    "login": ("いつものログインを、\n新しい顔で。", [
        ("入口のメッセージを刷新", "「ログイン」のみの見出しから、「おかえりなさい。」と説明付きの画面へ。"),
        ("フォームをコンパクトに", "入力欄とログインボタンを、緑を基調にした統一デザインへ。"),
        ("登録への案内も整理", "ロゴ付きヘッダーと、新規登録へのリンクを備えた構成へ。")]),
    "lp": ("推しの一枚を、\nもっと大切に。", [
        ("トップの印象を刷新", "紫の背景から、淡い背景と緑へ。生写真への想いが伝わる見出しに。"),
        ("画面プレビューを追加", "実際のコレクション管理をイメージできる、アプリ画面の紹介を配置。"),
        ("始め方をわかりやすく", "登録と生写真DBへの入口を、最初の画面にまとめて表示。")]),
    "missing": ("足りない一枚を、\n見やすく探す。", [
        ("検索欄が上部に", "大きなヘッダーと見出しの余白を整理。絞り込みフォームが見やすく。"),
        ("検索ボタンを統一", "青から緑へ。入力欄・カードも、ほかの画面と同じ見た目に。"),
        ("一覧へ戻りやすく", "スマホ下部に共通ナビを追加。コレクションの確認へ移動。")]),
    "mypage": ("自分のコレクションを、\nすっきり把握。", [
        ("アカウント欄を整理", "大きな見出しと色付きの枠を見直し、シンプルな情報カードへ。"),
        ("数字が読みやすく", "所持総数とグループ別の枚数を、統一した文字と余白で表示。"),
        ("日々の操作へ移動", "スマホ下部の共通ナビから、一覧・追加・トレードへ。")]),
    "payment_success": ("処理中の画面も、\nすっきり統一。", [
        ("案内を読みやすく", "処理中の見出しと説明を、コンパクトなヘッダーの下に配置。"),
        ("色と文字を統一", "水色のヘッダーから、ロゴ・緑・淡い背景を基調にした画面へ。"),
        ("共通ナビを追加", "下部のナビとフッターを、ほかの画面と同じ見た目に。")]),
    "privacy": ("長い説明も、\n読みやすく。", [
        ("本文が上部に", "大きなヘッダーを小さくし、ポリシーの見出しと本文を上部へ。"),
        ("文字と行間を統一", "本文や箇条書きを、ほかの画面と同じ書体と落ち着いた色で表示。"),
        ("サービス全体で統一", "共通ロゴとフッターを採用。案内ページにも同じデザインを。")]),
    "public--costume_detail": ("衣装ごとの写真を、\nすっきり確認。", [
        ("アプリと同じ見た目に", "水色のDBヘッダーから、SP Colle共通のロゴ付きヘッダーへ。"),
        ("表を落ち着いた色に", "水色の背景を淡い色へ。メンバーと種類の対応を読みやすく。"),
        ("見出しと枚数を整理", "衣装名と人数・種類数を、まとまりのある上部に配置。")]),
    "public--costume_list": ("衣装の一覧を、\n見やすく探す。", [
        ("DBの見た目を統一", "水色の画面から、アプリと同じ緑・白・淡い背景のデザインへ。"),
        ("検索欄を整理", "検索の入力欄とボタンを、細い枠線と緑でわかりやすく表示。"),
        ("衣装をカードで確認", "衣装名と人数・種類数を、読みやすい文字と余白で表示。")]),
    "public--index": ("あの一枚を、\n生写真DBで探す。", [
        ("DBの入口を刷新", "「生写真データベース」から、「次の一枚を、探しに。」の見出しへ。"),
        ("グループを見やすく", "大きな色付きの面から、色の目印と矢印を備えた白いカードへ。"),
        ("サービスと統一", "SP Colle共通のロゴ・配色・フッターを採用。")]),
    "public--member_costumes": ("メンバーの衣装を、\nすっきり確認。", [
        ("見出しを読みやすく", "DBの水色ヘッダーから共通ヘッダーへ。メンバー名と衣装名を整理。"),
        ("表の背景を落ち着かせる", "水色の面を淡い背景へ。種類ごとの情報を統一した文字で表示。"),
        ("DBとアプリを統一", "ロゴ・ログイン入口・フッターを共通デザインに。")]),
    "register": ("新しいコレクションを、\nここから。", [
        ("登録の入口を刷新", "「ユーザー登録」のみの見出しから、「推しの一枚と、ここに。」へ。"),
        ("フォームを見やすく", "メール入力と登録ボタンを、白いカードと緑で統一。"),
        ("案内をひとまとめに", "説明・入力・ログインへのリンクを、まとまりのある構成へ。")]),
    "select_group": ("選択画面も、\nすっきりした見た目に。", [
        ("グループを見分ける", "色付きの大きな面から、グループ色の枠線を使った白い選択肢へ。"),
        ("見出しをコンパクトに", "大きなヘッダーと余白を整理。選択欄を画面上部にまとめる。"),
        ("共通のデザインへ", "ロゴ・文字・背景・ナビを、ほかの画面と同じ見た目に。")]),
    "shared_collection--not_shared": ("公開状態も、\n伝わりやすく。", [
        ("状態をひと目で確認", "非公開の説明を、鍵のアイコン付きのシンプルなカードに。"),
        ("画面の余白を整理", "大きなヘッダーとタイトルをコンパクトにし、案内を上部へ。"),
        ("共通ロゴを採用", "公開コレクションの画面にも、アプリと同じブランド表示を。")]),
    "shared_collection--shared_view": ("コレクション共有も、\n読みやすく。", [
        ("名前とグループを整理", "中央の大きな見出しから、左揃えのタイトルと余白へ。"),
        ("カードの文字を統一", "メンバー・衣装・枚数の情報を、読みやすい共通の書体で表示。"),
        ("画面全体を統一", "公開画面にもロゴ付きヘッダーと共通フッターを採用。")]),
    "shared_stats": ("共有した数字も、\nすっきり見える。", [
        ("見出しをコンパクトに", "大きなヘッダーとタイトルを整理。統計の内容が上部に。"),
        ("数字と項目を統一", "総所持数とランキングを、落ち着いた緑と共通の文字で表示。"),
        ("公開画面も同じ印象に", "ロゴ・背景・フッターを、サービス内のほかの画面と統一。")]),
    "stats": ("集めた数字を、\nすっきり眺める。", [
        ("数字が上部に", "ヘッダーと見出しを小さくし、総所持数とランキングが見やすい位置へ。"),
        ("色を落ち着かせる", "青い数字・色付きの項目から、緑を基調にした統一デザインへ。"),
        ("日々の操作へ移動", "スマホ下部に共通ナビを追加。一覧や追加画面へ移動。")]),
    "terms": ("利用の案内も、\n読みやすく。", [
        ("本文を上部へ", "大きなヘッダーと余白を整理。規約の見出しと文章を上部に。"),
        ("長文の見た目を統一", "文字の書体・色・行間を、ほかのページと同じデザインに。"),
        ("共通のブランド表示", "案内ページにもSP Colleのロゴと共通フッターを採用。")]),
    "trade--editor": ("交換の募集を、\nアプリの中で。", [
        ("募集作成ページを追加", "募集用の表示名、交換方法、交換場所を入力できる画面に。"),
        ("公開内容を案内", "ページ上部に、下書きと公開情報についての説明を表示。"),
        ("交換条件をまとめる", "同種優先などの条件を、専用の入力欄で記載。")]),
    "trade--listing": ("交換したい写真を、\n募集ページで確認。", [
        ("募集の詳細ページを追加", "募集名・公開状態・交換方法を、ひとつの画面にまとめて表示。"),
        ("譲る写真と希望を確認", "提供写真と交換したい写真を、まとまりのあるカードで表示。"),
        ("条件も一緒に読む", "交換条件を上部に配置。募集・自分の募集・取引のナビも追加。")]),
    "trade--mine": ("自分の交換募集を、\nひとつの画面で。", [
        ("自分の募集一覧を追加", "自分が作った募集と公開状態を、カードにまとめて表示。"),
        ("状態を見分けやすく", "表示名・交換方法・更新日を、ラベルと余白で整理。"),
        ("募集作成への入口", "見出し横の作成ボタンと、募集・取引へのナビを配置。")]),
    "trade--search": ("次の交換相手を、\n募集から探す。", [
        ("トレード募集一覧を追加", "募集の表示名・交換方法・写真を、カードにまとめて表示。"),
        ("絞り込みの入口", "メンバーや衣装の選択、マッチ候補の表示などを上部に配置。"),
        ("募集も取引もここから", "募集作成ボタンと、自分の募集・取引管理へのナビを追加。")]),
    "trade--transaction": ("交換内容と進み具合を、\n一緒に確認。", [
        ("取引の詳細ページを追加", "取引状況・交換方法・相手を、上部にまとめて表示。"),
        ("双方の写真を見比べる", "募集者と応募者が渡す写真を、左右のカードで確認。"),
        ("次の操作をまとめる", "実物画像の共有・交換の確定・見送りのボタンを配置。")]),
    "trade--transactions": ("交換のやり取りを、\nひとつの一覧に。", [
        ("取引一覧を追加", "進行中の取引を、募集名・相手・状態のカードで確認。"),
        ("状況を見分けやすく", "交渉中などの状態を、カード内のラベルで表示。"),
        ("募集と取引を行き来", "募集検索・自分の募集・取引管理の共通ナビを配置。")]),
    "upgrade": ("案内画面も、\n見やすいカードに。", [
        ("見出しをコンパクトに", "大きなヘッダーと中央の余白を整理。説明とカードを上部へ。"),
        ("カードの文字を統一", "プランの項目を、共通の書体・枠線・余白で読みやすく表示。"),
        ("画面の色を整理", "青・黄などの色使いを見直し、落ち着いた緑と淡い背景へ。")]),
    "want--add": ("欲しい一枚を、\n見やすくリストへ。", [
        ("入力欄が上部に", "大きなヘッダーと見出しを整理。通常登録の選択欄がすぐ見える。"),
        ("登録項目をまとめる", "通常登録と無限回収登録を、統一した文字・カードで表示。"),
        ("よく使う機能へ", "見出し横の一覧ボタンと、スマホ下部の共通ナビを追加。")]),
    "want--index": ("欲しい一枚を、\nすっきり一覧に。", [
        ("一覧が上部に", "大きなヘッダーと見出しをコンパクトに。カードが上部から見える。"),
        ("カードを読みやすく", "衣装・メンバー・種類を、共通の書体と余白で整理。"),
        ("追加の入口を配置", "見出し横に追加ボタン。下部には共通ナビを追加。")]),
    "want--public_base": ("欲しい写真の共有も、\nすっきり見やすく。", [
        ("見出しを整理", "大きな中央タイトルから、左揃えの名前とグループ表示へ。"),
        ("希望カードを統一", "写真の情報と所持ラベルを、落ち着いた配色・文字で表示。"),
        ("交換チェックも見やすく", "交換チェックの操作を、共通の緑のボタンに統一。")]),
    "want--public_private": ("非公開の案内も、\nわかりやすく。", [
        ("説明を上部に", "大きなヘッダーと余白を整理。非公開の案内カードがすぐ見える。"),
        ("文字と枠線を統一", "説明とトップへのボタンを、共通の書体・細い枠線で表示。"),
        ("画面全体を揃える", "SP Colleのロゴ・背景・フッターを採用。下部ナビも追加。")]),
    "want--share_setting": ("欲しい写真の公開を、\n設定画面で。", [
        ("公開設定ページを追加", "欲しい写真の公開状態を確認できる、専用の画面を追加。"),
        ("今の状態がわかる", "見出しの下に「現在：非公開」など、現在の設定を表示。"),
        ("切替の操作を明確に", "公開するためのボタンと、公開範囲の説明をまとめて配置。")]),
}

# These captured pages were later retired or changed during the free-service work.
HISTORICAL = {"force_select_group", "select_group", "upgrade", "payment_success", "legal"}

CSS = """
*{box-sizing:border-box}html,body{margin:0;width:1600px;height:1200px;overflow:hidden}
body{font-family:Meiryo,"Yu Gothic",sans-serif;color:#253830;background:#f6f7f2}
.card{position:relative;width:1600px;height:1200px;isolation:isolate}
.accent{position:absolute;left:0;top:0;width:12px;height:1200px;background:#315e4b}
.brand{position:absolute;left:64px;top:36px;display:flex;align-items:center;gap:15px}
.mark{width:44px;height:44px;border-radius:12px;background:#315e4b;display:grid;place-items:center}
.mark svg{width:28px;height:28px}.brand-name{font-size:29px;font-weight:700;letter-spacing:-1px}
.brand-caption{margin-left:6px;font-size:17px;color:#65736b}
.edition{position:absolute;right:64px;top:40px;font-size:19px;color:#65736b;display:flex;align-items:center;gap:18px}
.edition span{padding:7px 16px;border:1px solid #cfdbd0;border-radius:30px;background:#fff}
.page-title{position:absolute;left:64px;top:103px;margin:0;font-size:24px;font-weight:700;color:#65736b;white-space:nowrap}
.history{font-size:19px;font-weight:400;margin-left:20px;color:#877557}
h1{position:absolute;left:60px;top:136px;margin:0;font-size:51px;font-weight:700;line-height:1.2;letter-spacing:-2px;padding-bottom:8px}
.compare{position:absolute;left:80px;top:288px;display:grid;grid-template-columns:374px 374px;gap:70px}
.label{height:39px;display:flex;align-items:center;gap:14px;margin-bottom:16px;font-weight:700;font-size:25px}
.tag{font-size:16px;letter-spacing:1.1px;border-radius:6px;padding:4px 12px;color:#687269;background:#e8ece6}
.new .tag{color:#fff;background:#315e4b}.new .label{color:#315e4b}
.frame{width:374px;height:805px;border:2px solid #d8ded5;border-radius:17px;overflow:hidden;background:#fff;box-shadow:0 12px 28px #25383010}
.new .frame{border-color:#315e4b;box-shadow:0 12px 30px #315e4b1b}
.screen{display:block;width:370px;height:auto;max-width:none}
.arrow{position:absolute;left:474px;top:695px;width:30px;height:30px;color:#315e4b;display:grid;place-items:center}
.arrow svg{width:28px;height:28px}
.notes{position:absolute;left:964px;top:288px;width:572px;height:860px;padding:38px 40px;border-radius:26px;background:#315e4b;color:#fff}
.notes-kicker{color:#d7e9ce;font-size:17px;font-weight:700;letter-spacing:2px;margin-bottom:13px}
.notes h2{font-size:32px;line-height:1.4;letter-spacing:-1px;margin:0 0 30px}
.point{padding-top:25px;border-top:1px solid #ffffff33;margin-top:27px}
.point-title{display:flex;gap:14px;align-items:baseline;font-size:29px;font-weight:700;line-height:1.45;letter-spacing:-1px}
.num{font-size:18px;letter-spacing:1px;color:#d7e9ce;flex-shrink:0;min-width:26px}
.point p{font-size:24px;line-height:1.75;color:#eef4ea;margin:12px 0 0 40px;letter-spacing:-.35px}
.bottom{position:absolute;left:80px;right:64px;bottom:20px;display:flex;justify-content:space-between;align-items:center;font-size:17px;color:#65736b}
.bottom strong{font-weight:700;color:#315e4b;letter-spacing:1px}
.absent{background:#edf1e9;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;position:relative;box-shadow:none}
.absence-icon{height:86px;width:86px;margin-bottom:35px;border-radius:50%;display:grid;place-items:center;background:#dce6d8;color:#6e806d}
.absence-icon svg{width:42px;height:42px}.absence-title{font-size:30px;line-height:1.6;font-weight:700;color:#526751}
.absence-body{font-size:22px;color:#65736b;line-height:1.8;margin-top:21px;padding:0 30px}
.absence-pill{margin-top:35px;border:1px solid #bfcebd;border-radius:30px;padding:10px 21px;font-size:19px;color:#526751}
.gallery-body{width:auto;height:auto;overflow:auto;padding:50px;max-width:1800px;margin:auto}
.gallery-body h1{position:static;font-size:38px}.gallery-body p{font-size:19px;line-height:1.8}
.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}
.gallery a{color:#253830;text-decoration:none;font-size:17px}.gallery img{width:100%;display:block;border:1px solid #d8ded5;border-radius:10px;margin-bottom:9px}
"""


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def data_image(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


LOGO = '<svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M3 11 16 5l13 6-13 6Z" fill="white"/><path d="m3 16 13 6 13-6M3 21l13 6 13-6" stroke="white" stroke-width="2.5" stroke-linejoin="round"/></svg>'
ARROW = '<svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M4 16h22M18 8l8 8-8 8" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>'
PLUS = '<svg viewBox="0 0 48 48" fill="none" aria-hidden="true"><rect x="7" y="7" width="34" height="34" rx="7" stroke="currentColor" stroke-width="2"/><path d="M24 15v18M15 24h18" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>'


def render_html(record: dict, number: int, total: int, source: Path) -> str:
    slug = record["slug"]
    headline, points = COPY[slug]
    historical = slug in HISTORICAL
    if record["new"]:
        before = f'<div class="frame absent"><div class="absence-icon">{PLUS}</div><div class="absence-title">修正前には<br>なかったページ</div><div class="absence-body">今回の更新で<br>新しく追加されました。</div><div class="absence-pill">新機能を追加</div></div>'
    else:
        before = f'<div class="frame"><img class="screen" src="{data_image(source / "before" / f"{slug}-390.png")}" alt="修正前の画面"></div>'
    after = f'<div class="frame"><img class="screen" src="{data_image(source / "after" / f"{slug}-390.png")}" alt="修正後の画面"></div>'
    notes = "".join(f'<div class="point"><div class="point-title"><span class="num">{i:02d}</span><span>{esc(title)}</span></div><p>{esc(body)}</p></div>' for i, (title, body) in enumerate(points, 1))
    history = '<span class="history">旧画面の参考比較</span>' if historical else ""
    edition = "新しいページ" if record["new"] else ("デザイン比較 / 参考" if historical else "画面リニューアル")
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>{esc(record['label'])} | SP Colle</title><style>{CSS}</style></head><body>
<main class="card"><div class="accent"></div><div class="brand"><div class="mark">{LOGO}</div><span class="brand-name">SP Colle</span><span class="brand-caption">生写真と、推しの毎日。</span></div>
<div class="edition"><span>{edition}</span>{number:02d} / {total:02d}</div><p class="page-title">{esc(record['label'])}{history}</p><h1>{esc(headline).replace(chr(10), '<br>')}</h1>
<div class="compare"><section><div class="label"><span class="tag">BEFORE</span>修正前</div>{before}</section><section class="new"><div class="label"><span class="tag">{'NEW' if record['new'] else 'AFTER'}</span>{'新しく追加' if record['new'] else '修正後'}</div>{after}</section></div><div class="arrow">{ARROW}</div>
<aside class="notes"><div class="notes-kicker">{'NEW FEATURE' if record['new'] else 'UPDATE POINTS'}</div><h2>{'新しくできること' if record['new'] else 'ここが変わりました'}</h2>{notes}</aside>
<footer class="bottom"><strong>生写真と、推しの毎日。</strong><span>2026.10.12 撮影 / サンプル画面 / スマホ画面の上部を抜粋</span></footer></main></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--browser", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    parser.add_argument("--limit", type=int, help="Render only the first N cards for preview")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    records = json.loads((source / "capture-results.json").read_text(encoding="utf-8"))["pages"]
    assert set(COPY) == {r["slug"] for r in records}, "Every page needs its own verified caption"
    output.mkdir(parents=True, exist_ok=True)
    for directory in ("images", "layouts"):
        (output / directory).mkdir(exist_ok=True)
    manifest, gallery = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.browser)
        page = browser.new_page(viewport={"width":SIZE[0], "height":SIZE[1]}, device_scale_factor=1)
        # Every font and asset is local or embedded. Prevent external requests.
        page.route("http://**/*", lambda route: route.abort())
        page.route("https://**/*", lambda route: route.abort())
        for number, record in enumerate(records[:args.limit] if args.limit else records, 1):
            name = f"{number:02d}-{record['slug']}"
            layout_path = output / "layouts" / f"{name}.html"
            layout_path.write_text(render_html(record, number, len(records), source), encoding="utf-8")
            page.goto(layout_path.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.wait_for_function("Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)")
            overflow = page.evaluate("""() => [...document.querySelectorAll('h1,.page-title,.notes,.point-title,.point p,.label')].filter(e => e.scrollHeight > e.clientHeight + 8 || e.scrollWidth > e.clientWidth + 1).map(e => e.className || e.tagName)""")
            assert not overflow, (name, overflow)
            # Check sidebar and title positions, rather than just successful rendering.
            geometry = page.evaluate("""() => ({titleBottom:document.querySelector('h1').getBoundingClientRect().bottom,compareTop:document.querySelector('.compare').getBoundingClientRect().top,lastPointBottom:document.querySelector('.point:last-child').getBoundingClientRect().bottom,notesBottom:document.querySelector('.notes').getBoundingClientRect().bottom})""")
            assert geometry["titleBottom"] < geometry["compareTop"] - 12, (name, geometry)
            assert geometry["lastPointBottom"] < geometry["notesBottom"] - 20, (name, geometry)
            png_path = output / "images" / f"{name}.png"
            page.screenshot(path=str(png_path))
            with Image.open(png_path) as check:
                assert check.size == SIZE
                check.verify()
            assert png_path.stat().st_size < 5_000_000, (name, "Image too large")
            inputs = {}
            for version in ("before", "after"):
                path = source / version / f"{record['slug']}-390.png"
                if path.exists():
                    inputs[version] = {"path":str(path), "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
            manifest.append({"number":number, "slug":record["slug"], "page":record["label"], "image":f"images/{name}.png", "size":list(SIZE), "new":record["new"], "historical":record["slug"] in HISTORICAL, "headline":COPY[record["slug"]][0], "points":[{"title":t,"description":d} for t,d in COPY[record["slug"]][1]], "sources":inputs})
            gallery.append(f'<a href="images/{name}.png"><img src="images/{name}.png" alt="{esc(record["label"])}">{number:02d}. {esc(record["label"])}</a>')
            print(f"{number:02d}/{len(records)} {name}", flush=True)
        page.close()
        index = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>SP Colle X用比較画像一覧</title><style>{CSS}</style></head><body class="gallery-body"><h1>SP Colle — ページ別の比較画像</h1><p>1ページにつき1枚。画像をクリックすると原寸PNGを開きます。<br>ご指定の2026年10月12日時点のスクリーンショットを使用。後日の無料化・並び順修正は反映していません。<br>旧プラン・選択・決済・特商法画面は「旧画面の参考比較」として掲載しています。</p><div class="gallery">{''.join(gallery)}</div></body></html>'''
        (output / "index.html").write_text(index, encoding="utf-8")
        # Browser-rendered contact sheet; no source screenshot pixels are edited.
        preview = browser.new_page(viewport={"width":1700, "height":1200}, device_scale_factor=1)
        preview.goto((output / "index.html").as_uri(), wait_until="load")
        preview.evaluate("document.fonts.ready")
        preview.wait_for_function("Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)")
        preview.screenshot(path=str(output / "overview.png"), full_page=True)
        browser.close()
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = f'''# SP Colle — X宣伝用のページ別比較画像

{len(manifest)}ページ、各1枚。PNG / 1600 × 1200 px / 4:3。Xへの投稿は実施していません。

各画像は左が修正前、右が修正後。右端にそのページの変更点を3つ掲載しています。
修正前のない新規7ページでは、左に「修正前にはなかったページ」と明示しています。
画面の文字やデータは描き直さず、指定されたスマホ幅390pxのスクリーンショットをHTML/CSSで配置し、上部844px相当を掲載しました。
PC画像と全ページの原寸画像は元のフォルダに残っています。

素材: `{source}`
撮影時点: 2026-10-12。サンプルデータを使用した比較画面です。
後日の完全無料化、種類表記・並び順の修正は素材に含まれていないため、画像内でこれらの変更を宣伝していません。
利用グループ設定・グループ選択・料金プラン・決済処理中・特商法の5ページは、その後変更された旧画面の参考比較と明示しています。

一覧: [index.html](index.html) / [overview.png](overview.png)
`images/` に投稿用PNG、`layouts/` に各画像の再編集可能なHTML、`manifest.json` に文言・元画像のSHA-256を保存。
ZIPには投稿用PNG・一覧・README・manifestを収録しています。

## ページ一覧

''' + "\n".join(f'- [{r["number"]:02d}. {r["page"]}]({r["image"]})' + ("（新規）" if r["new"] else "（旧画面の参考比較）" if r["historical"] else "") for r in manifest) + '''

## 再作成

リポジトリのルートで `myenv/Scripts/python.exe tools/create_x_promo_images.py` を実行。
必要環境: Playwright、Pillow、Chrome、Meiryo。
素材フォルダが変わった場合は `--source`、出力先は `--output` で指定できます。
'''
    (output / "README.md").write_text(readme, encoding="utf-8")
    if not args.limit:
        archive = output.parent / f"{output.name}-x-promo.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for file in sorted((output / "images").glob("*.png")):
                bundle.write(file, file.relative_to(output))
            for filename in ("index.html", "overview.png", "README.md", "manifest.json"):
                bundle.write(output / filename, filename)
        print(f"Saved {len(manifest)} images and {archive}", flush=True)


if __name__ == "__main__":
    main()
