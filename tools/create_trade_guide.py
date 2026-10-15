"""Render unnumbered trade how-to images from the real UI and an isolated DB.

Run with myenv Python. No app.py, .env, production DB, or real user images.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from flask import Response, redirect, session
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from test_trade_marketplace import make_app, seed
from extensions import db
from models import User, UserPhoto, UserPhotoImage
from trade.models import TradeListing, TradeOffer, TradeWant


def fixture(port):
    app = make_app()
    app.config['WTF_CSRF_ENABLED'] = True
    os.environ['R2_PUBLIC_BASE_URL'] = f'http://127.0.0.1:{port}/sample'
    with app.app_context():
        seed()
        # All images are local vector samples, explicitly shared in the sample flow.
        for uid, pid, index in [(100, 1001, 0), (200, 1002, 1), (200, 1003, 2)]:
            stock = UserPhoto.query.filter_by(user_id=uid, photo_id=pid).one()
            db.session.add(UserPhotoImage(user_id=uid, user_photo_id=stock.id,
                                         image_key=f'{index}.svg', thumbnail_key=f'{index}.svg'))
        db.session.commit()
        image = UserPhotoImage.query.filter_by(user_id=200).first()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for index in range(8):
            listing = TradeListing(user_id=200, group_id=1,
                alias=['はるの交換用', '写真トレード', '郵送で交換希望', 'ライブ会場で交換'][index % 4],
                method=['mail', 'meet', 'either'][index % 3], status='open',
                created_at=now-timedelta(days=index+1), updated_at=now-timedelta(days=index+1))
            offer = TradeOffer(photo_id=1002 if index % 2 else 1003, quantity=1,
                want_mode='any', image_id=image.id if index % 2 else None)
            offer.wants.append(TradeWant(photo_id=1001, quantity=1, priority='normal'))
            listing.offers.append(offer)
            db.session.add(listing)
        db.session.commit()

    @app.get('/sample/<int:index>.svg')
    def sample(index):
        color = ['#d7dfe7', '#ead6df', '#dde4d7'][index % 3]
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="178" height="254" viewBox="0 0 89 127"><rect width="89" height="127" fill="white"/><rect x="4" y="4" width="81" height="113" fill="{color}"/><circle cx="44" cy="41" r="14" fill="#f3e8dd"/><path d="M29 37c-2-24 34-24 30 5-6-12-20-13-30-5z" fill="#62626b"/><path d="M16 111V77c0-24 57-24 57 0v34z" fill="white" opacity=".7"/><path d="m36 62 8 15 8-15" fill="#f3e8dd"/><path d="M44 77v34" stroke="{color}"/><text x="44" y="124" fill="#777" font-family="sans-serif" font-size="4" text-anchor="middle">SAMPLE IMAGE</text></svg>'''
        return Response(svg, mimetype='image/svg+xml')

    @app.get('/guide/login/<int:uid>')
    def login(uid):
        assert uid in (100, 200)
        session['_user_id'] = str(uid)
        session['_fresh'] = True
        return redirect('/trade/hinatazaka')

    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def capture(args, browser):
    origin = f'http://127.0.0.1:{args.port}'
    output = args.output
    raw = output / 'screens'
    raw.mkdir(exist_ok=True)
    context = browser.new_context(service_workers='block', reduced_motion='reduce',
                                  viewport={'width': 390, 'height': 844}, device_scale_factor=2)
    errors, cache, shots = [], {}, {}

    def external(route):
        url = route.request.url
        if urlparse(url).hostname not in ('cdn.jsdelivr.net', 'cdnjs.cloudflare.com'):
            route.abort()
            return
        if url not in cache:
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as response:
                cache[url] = (response.read(), response.headers.get('Content-Type'))
        body, typ = cache[url]
        route.fulfill(body=body, content_type=typ)

    context.route('https://**/*', external)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('dialog', lambda dialog: dialog.accept())

    def goto(path):
        response = page.goto(origin + path, wait_until='networkidle')
        assert response.status < 400, (path, response.status)
        page.evaluate('document.fonts.ready')

    def click(locator):
        locator.click()
        page.wait_for_load_state('networkidle')

    def shot(name, focus=None, highlights=()):
        page.evaluate('document.activeElement?.blur()')
        if focus is None:
            page.evaluate('window.scrollTo(0,0)')
        else:
            focus.evaluate("el => window.scrollTo(0, Math.max(0, el.getBoundingClientRect().top + scrollY - 92))")
        page.wait_for_timeout(180)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), name
        boxes = []
        for locator in highlights:
            box = locator.bounding_box()
            if box and box['y'] >= 0 and box['y'] + box['height'] <= 844:
                boxes.append(box)
            else:
                raise AssertionError(f'{name}: highlight outside screenshot: {box}')
        path = raw / (name + '.png')
        page.screenshot(path=str(path))
        shots[name] = dict(path=str(path.relative_to(output)), boxes=boxes,
                           route=urlparse(page.url).path, scroll=page.evaluate('scrollY'))
        print('Captured ' + name, flush=True)

    goto('/guide/login/100')
    nav = page.locator('.mobile-nav').get_by_role('link', name='トレード', exact=True)
    create = page.get_by_role('link', name='募集する', exact=True)
    shot('entry', highlights=[nav, create])
    click(create)
    page.locator('.trade-picker-photo').first.wait_for()
    page.locator('#listing-alias').fill('はな・交換用')
    page.locator('#listing-method').select_option('mail')
    page.locator('#listing-notes').fill('同種優先。硬質ケース・防水対策で郵送希望です。')
    shot('conditions', page.locator('#listing-alias').locator('..'),
         [page.locator('#listing-alias'), page.locator('#listing-method')])
    shot('offer-picker', page.locator('label[for="picker-target"]'),
         [page.locator('#picker-target'), page.locator('.trade-picker-photo').first])
    page.locator('.trade-picker-photo').first.click()
    add_want = page.get_by_role('button', name='この写真の希望を追加')
    shot('add-wants', page.locator('#editor-offers'), [add_want])
    add_want.click()
    page.locator('#picker-q').fill('メンバーB 春')
    page.locator('#picker-search').click()
    wanted = page.locator('.trade-picker-photo').filter(has_text='チュウ').first
    wanted.wait_for()
    shot('want-picker', page.locator('label[for="picker-target"]'), [wanted])
    wanted.click()
    page.locator('.trade-priority').select_option('high')
    page.locator('#editor-offers input[type="checkbox"]').check()
    shot('offer-wants', page.locator('#editor-offers'),
         [page.locator('.trade-wanted-row'), page.locator('#editor-offers .form-check')])
    save = page.get_by_role('button', name='下書きを保存して公開内容を確認')
    shot('save-draft', save, [save])
    click(save)
    listing = urlparse(page.url).path
    assert '/listing/' in listing
    page.locator('#confirm-public').check()
    publish = page.get_by_role('button', name='確認した内容を公開')
    shot('publish', highlights=[page.locator('label[for="confirm-public"]'), publish])
    click(publish)
    shot('published', highlights=[page.get_by_role('button', name='募集URLをコピー'),
                                 page.get_by_role('button', name='公開を停止する')])
    goto('/trade/hinatazaka/mine')
    shot('mine', highlights=[page.locator('.trade-nav').get_by_role('link', name='自分の募集')])
    goto('/trade/hinatazaka')
    shot('feed', highlights=[page.locator('#trade-q'), page.locator('.trade-listing-card').first])
    page.locator('#trade-filters summary').click()
    page.locator('#trade-side').select_option('offer')
    shot('search-offer', page.locator('label[for="trade-side"]'), [page.locator('#trade-side')])
    page.locator('#trade-side').select_option('want')
    # Choose exact catalogue criteria through TomSelect, as a user would.
    for key, value in [('member','2'), ('costume','1'), ('type','2')]:
        page.locator(f'#trade-{key}').evaluate('(el, value) => el.tomselect.setValue(value)', value)
    page.locator('#trade-method').select_option('mail')
    shot('search-want', page.locator('label[for="trade-side"]'),
         [page.locator('#trade-side'), page.get_by_role('button', name='この条件で見る')])
    click(page.get_by_role('button', name='この条件で見る'))
    assert page.locator('.trade-listing-card').count() == 1
    shot('search-result', highlights=[page.locator('.trade-listing-card').first])
    goto('/guide/login/200')
    goto(listing)
    shot('listing-detail', highlights=[page.locator('.trade-offer-row').first])
    page.locator('#proposal-alias').fill('ゆい・交換希望')
    page.locator('#request-1001').fill('1')
    shot('proposal-select', page.locator('#trade-proposal').locator('..'),
         [page.locator('#request-1001')])
    page.locator('.trade-picker-photo').filter(has_text='チュウ').first.click()
    page.locator('#proposal-note').fill('こちらのチュウ1枚と、ヨリ1枚の交換を希望します。写真の状態を確認させてください。')
    send_proposal = page.get_by_role('button', name='選んだ交換案を送る')
    shot('proposal-send', page.locator('label[for="proposal-note"]'), [send_proposal])
    click(send_proposal)
    transaction = urlparse(page.url).path
    assert '/transaction/' in transaction
    share = page.get_by_role('button', name='実物画像を相手だけに共有')
    shot('private-share', share, [share])
    click(share)
    page.locator('#trade-message').fill('実物画像を共有しました。硬質ケースと防水対策で発送予定です。')
    shot('message', page.locator('label[for="trade-message"]'),
         [page.locator('#trade-message'), page.get_by_role('button', name='送信', exact=True)])
    click(page.get_by_role('button', name='送信', exact=True))
    goto('/guide/login/100')
    goto(transaction)
    confirm = page.get_by_role('button', name='この内容で交換を確定')
    shot('accept', page.locator('[data-trade-actions]'), [confirm])
    click(confirm)
    progress = page.get_by_role('heading', name='双方の進捗').locator('..')
    shot('accepted', progress, [page.get_by_role('button', name='発送を連絡')])
    click(page.get_by_role('button', name='発送を連絡'))
    goto('/guide/login/200')
    goto(transaction)
    click(page.get_by_role('button', name='発送を連絡'))
    shot('receive', page.get_by_role('heading', name='双方の進捗').locator('..'),
         [page.get_by_role('button', name='受取を確認')])
    click(page.get_by_role('button', name='受取を確認'))
    goto('/guide/login/100')
    goto(transaction)
    click(page.get_by_role('button', name='受取を確認'))
    assert '完了' in page.locator('h1 + p').inner_text()
    shot('completed', highlights=[page.locator('h1 + p')])
    goto('/trade/hinatazaka/transactions')
    shot('transactions', highlights=[page.locator('.trade-nav').get_by_role('link', name='取引管理'),
                                      page.locator('.trade-listing-card').first])
    assert not errors, errors
    context.close()
    (output / 'captures.json').write_text(json.dumps(shots, ensure_ascii=False, indent=2), encoding='utf-8')
    return shots


# Exact button names are quoted; headings explain their purpose in ordinary language.
CARDS = [
    dict(slug='trade-overview', category='SP Colle のトレード', title='欲しい一枚から、\n交換完了まで。',
         lead='生写真の募集・検索・相談・進捗を、\nひとつの場所で。',
         steps=[('譲る写真と、求める写真をつなぐ', '出す写真ごとに、欲しい写真と枚数を指定。'),
                ('欲しい側からも、渡せる側からも探せる', 'メンバー・衣装・カットまで絞って検索。'),
                ('交換が決まった後も、そのまま管理', '二人だけの相談から、発送・受取確認まで。')],
         note='募集する人も、探す人も。下部メニューの「トレード」から。',
         screens=[('feed','譲 ⇄ 求で、気になる募集を探す'), ('accepted','確定後の発送・受取も管理')]),
    dict(slug='open-trade', category='募集を公開する', title='入口は、下部メニューの\n「トレード」。',
         lead='ログイン後、利用するグループを選んで始めます。',
         steps=[('画面下の「トレード」を開く', 'PCでは上部メニューの「トレード」から開けます。'),
                ('右上の「＋ 募集する」を押す', '交換に出す写真と、その写真で欲しい写真を設定する画面へ進みます。'),
                ('譲る写真は、先に所持登録', 'まだ登録していない写真は、下部の「追加」から写真・所持枚数を登録してください。')],
         note='公開した募集は「自分の募集」から、いつでも確認できます。', screens=[('entry','ここから募集を作成')]),
    dict(slug='choose-offers', category='募集を公開する', title='まず「譲」を選び、\nその写真の「求」を追加。',
         lead='出す写真ごとに、交換したい相手の写真を結びつけます。',
         steps=[('「譲：自分の所持写真から追加」で選ぶ', '下の候補から、交換に出す写真をタップ。提供する枚数も設定します。'),
                ('「この写真の希望を追加」を押す', '写真の検索が「求」の追加に切り替わります。メンバー・衣装・カットで探して選びます。'),
                ('欲しい写真と枚数・希望度を確認', '複数の提供写真がある場合も、それぞれに希望を追加できます。')],
         note='例：メンバーAのヨリを譲り、メンバーBのチュウを希望。',
         screens=[('offer-picker','所持写真から「譲」を選ぶ'), ('add-wants','この写真に対する「求」を追加')]),
    dict(slug='set-wants-and-conditions', category='募集を公開する', title='交換条件と、\n公開する情報を整える。',
         lead='表示名・交換方法・写真の希望条件を確認します。',
         steps=[('募集用の表示名・交換方法を入力', 'アカウント名とは別の表示名を使えます。郵送／現地・手渡し／どちらも可を選択。'),
                ('「いずれか一つ」か「すべて」を指定', '希望枚数と、熱望・希望・緩く希望を設定。コンプ崩し不可などはセット交換を選びます。'),
                ('実物画像の公開は、自分で選択', '募集に載せる場合だけチェック。登録済みの先頭画像が公開されます。住所や連絡先は公開欄に書かないでください。')],
         note='セット交換は、提供一式と登録した希望写真すべての交換です。',
         screens=[('conditions','表示名と方法を決める'), ('offer-wants','希望条件と画像の公開を確認')]),
    dict(slug='publish-listing', category='募集を公開する', title='下書きで確認してから、\n募集を公開。',
         lead='保存しただけでは、ほかの人には表示されません。',
         steps=[('「下書きを保存して公開内容を確認」', '入力画面の下にあるボタンで、非公開の確認画面へ進みます。写真・枚数・希望条件を見直します。'),
                ('公開のチェックを入れて、公開する', '「この募集内容を検索・共有ページに公開します」にチェックし、「確認した内容を公開」を押します。'),
                ('公開後は、募集URLを共有できる', '「募集URLをコピー」でURLを取得。メール・SNS・コレクション全体は公開されません。')],
         note='変更したいときは「内容を編集」。編集後は、改めて公開操作が必要です。',
         screens=[('publish','この操作で検索・共有ページに公開'), ('published','公開後はURLのコピー・停止が可能')]),
    dict(slug='browse-listings', category='交換相手を探す', title='隙間時間に、\n「譲 ⇄ 求」を眺める。',
         lead='まずは気になる写真から。条件を決めずに見て回れます。',
         steps=[('下部の「トレード」→「募集を探す」', '新しい募集が写真付きで並びます。カードの「譲」は相手が出す写真、「求」は相手の希望です。'),
                ('新着・郵送・現地・セットで切り替え', 'メンバーのタブや、検索欄も利用できます。続きを見たいときは下の「もっと見る」へ。'),
                ('気になるカードをタップ', '写真の種類・枚数・交換方法・希望条件を詳しく確認してから、交換案を送ります。')],
         note='実物画像は、募集者が公開を選んだものだけ表示されます。', screens=[('feed','写真から気になる募集を開く'), ('listing-detail','詳細で枚数と交換条件を確認')]),
    dict(slug='search-by-offer-or-want', category='交換相手を探す', title='欲しい写真でも、\n渡せる写真でも探せる。',
         lead='検索欄の下にある「絞り込み」を開きます。',
         steps=[('欲しい写真を見つけたいとき', '「探す写真」を「譲：欲しい写真を探す」に。相手が提供している写真を検索します。'),
                ('自分の写真を欲しがる人を探すとき', '「求：自分が渡せる写真を探す」に。相手の希望写真を検索します。'),
                ('メンバー・衣装・カットまで指定', '郵送／現地も選び、「この条件で見る」を押します。狙っている一枚まで絞って探せます。')],
         note='「譲」は相手が出す写真。「求」は相手が欲しい写真です。',
         screens=[('search-offer','「譲」から、自分が欲しい写真を検索'), ('search-want','「求」から、自分が渡せる写真を検索')]),
    dict(slug='send-proposal', category='見つかったら、交換案を送る', title='受け取る写真と、\n渡す写真を選んで送信。',
         lead='募集の詳細を開き、ログインして「交換案を送る」へ。',
         steps=[('表示名・方法と、受け取る枚数を入力', '「あなたが受け取る写真」で枚数を指定。セット募集は、提供一式での交換になります。'),
                ('「あなたが渡す写真」を所持品から選ぶ', '相手の希望に合う写真と枚数を指定します。候補にない写真は先に「追加」から所持登録を。'),
                ('相談内容を書き、「選んだ交換案を送る」', '状態や日程など、相手に確認したい内容を添えられます。送信内容は募集者とあなたにだけ表示されます。')],
         note='送信時点では取り置きされません。募集者の承認後に確定します。',
         screens=[('proposal-select','受け取る写真の枚数を指定'), ('proposal-send','相談内容を添えて交換案を送る')]),
    dict(slug='talk-and-share-photos', category='交換内容を相談する', title='二人だけの画面で、\n現物と条件を確認。',
         lead='送信後は「交換内容と取引状況」のページへ進みます。',
         steps=[('「相手へのメッセージ」から相談', '写真の状態、交換日程、梱包・発送方法などを入力し、「送信」を押します。'),
                ('実物画像は、相手だけに共有できる', '「実物画像を相手だけに共有」を押して確認すると、自分が渡す写真の登録済み先頭画像を共有できます。'),
                ('後から開くときは「取引管理」', 'トレード内の「取引管理」から相手を選ぶと、相談と進捗の続きを確認できます。')],
         note='写真や枚数を変える場合は、提案を取り消して新しい交換案を送ります。',
         screens=[('private-share','この交換相手だけに実物画像を共有'), ('message','メッセージで条件を相談')]),
    dict(slug='accept-trade', category='募集した人が、交換を確定する', title='内容に合意したら、\n募集者が「交換を確定」。',
         lead='提案を受けた人は「取引管理」から交換案を開きます。',
         steps=[('双方の写真・枚数・交換方法を確認', '相談と実物画像を確認し、交換内容が合っているか確かめます。'),
                ('「この内容で交換を確定」を押す', 'このボタンは募集者側に表示されます。確認操作を終えると、双方の写真が取り置きされます。'),
                ('確定後は、双方の進捗が表示', '郵送なら発送状況と受取状況を、現地交換なら受取状況を、二人で確認できます。')],
         note='見送る場合は募集者が「見送る」。応募者は確定前なら提案を取り消せます。',
         screens=[('accept','募集者側で、この内容を承認'), ('accepted','確定すると双方の進捗を表示')]),
    dict(slug='ship-and-receive', category='確定したら、発送・受取を記録する', title='発送したら連絡。\n届いたら、受取を確認。',
         lead='交換が確定した取引ページで、それぞれが操作します。',
         steps=[('郵送した人が「発送を連絡」', '実際に発送してから押します。相手の画面にも発送済みとして表示されます。'),
                ('到着後、写真・枚数・状態を確認', '郵送の場合は相手の発送連絡後に「受取を確認」を押します。受取前に押さないでください。'),
                ('現地・手渡しでも、双方が受取確認', '現地交換では発送連絡は不要です。交換した写真を確認した後、二人とも「受取を確認」を押します。')],
         note='「取引管理」から戻れます。メッセージも同じ取引ページに残ります。',
         screens=[('accepted','実際に発送したら連絡'), ('receive','実物を受け取ってから確認')]),
    dict(slug='complete-and-manage', category='交換完了まで、アプリで管理する', title='二人の受取確認で完了。\n所持数も自動で更新。',
         lead='最後は、双方が受け取ったことを確認します。',
         steps=[('双方の確認がそろうと「完了」', '渡した枚数と受け取った枚数が、所持数に反映されます。通常の希望リストも更新されます。'),
                ('履歴は「取引管理」で振り返る', '相手ごとの取引状況と、これまでのやり取りをまとめて確認できます。'),
                ('募集の公開状態は「自分の募集」へ', '募集を開き「公開を停止する」で検索・共有を停止。成立済みの取引は、そのまま取引管理で進めます。')],
         note='確定後のキャンセルは二人の合意が必要です。受取確認前に、取引画面で相談します。',
         screens=[('completed','双方の受取確認がそろい、完了'), ('transactions','相手ごとの取引をまとめて管理')]),
]


def image_data(path):
    return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def compose(card, shots, root):
    screens = []
    for name, caption in card['screens']:
        shot = shots[name]
        rings = ''.join(f'<i class="ring" style="left:{b["x"]/390*100}%;top:{b["y"]/844*100}%;width:{b["width"]/390*100}%;height:{b["height"]/844*100}%"></i>' for b in shot['boxes'])
        screens.append(f'<figure><figcaption>{html.escape(caption)}</figcaption><div class="phone"><img src="{image_data(root / shot["path"])}" alt="{html.escape(caption)}">{rings}</div></figure>')
    steps = ''.join(f'<section><h2>{html.escape(title)}</h2><p>{html.escape(body)}</p></section>' for title, body in card['steps'])
    title = html.escape(card['title']).replace('\n', '<br>')
    lead = html.escape(card['lead']).replace('\n', '<br>')
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>{html.escape(card['title'].replace(chr(10),''))}</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;width:1600px;height:1200px;overflow:hidden}}body{{background:#faf9f7;color:#27272b;font-family:Meiryo,"Yu Gothic",sans-serif;-webkit-font-smoothing:antialiased}}
header{{position:absolute;left:64px;right:64px;top:38px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #dcd9d6;padding-bottom:20px}}.brand{{font-size:28px;font-weight:800;letter-spacing:-1px}}.brand b{{color:#c83c68}}.category{{font-size:19px;font-weight:700;color:#655e62}}
.copy{{position:absolute;left:64px;top:136px;width:618px}}h1{{font-size:52px;line-height:1.38;letter-spacing:-2px;margin:0 0 27px;font-weight:800}}.lead{{font-size:24px;line-height:1.9;margin:0 0 35px;color:#686167;font-weight:500}}section{{border-top:1px solid #ddd8d8;padding-top:22px;margin-top:23px}}h2{{font-size:25px;line-height:1.65;letter-spacing:-.6px;margin:0 0 8px;font-weight:800}}section p{{font-size:22px;line-height:1.85;margin:0;color:#595257}}.note{{font-size:19px;line-height:1.85;margin:29px 0 0;padding-left:18px;border-left:3px solid #c83c68;color:#7d3750}}
.screens{{position:absolute;left:742px;right:54px;top:142px;display:flex;justify-content:center;gap:28px}}figure{{margin:0;width:374px;flex-shrink:0}}figcaption{{height:57px;font-size:18px;line-height:1.6;color:#686167;font-weight:700}}.phone{{width:374px;height:809.374px;position:relative;outline:1px solid #d3ced0;background:#fff;box-shadow:0 9px 28px #2222220c}}.phone img{{display:block;width:100%;height:100%}}.ring{{position:absolute;border:3px solid #c83c68;box-shadow:0 0 0 2px #fff9;pointer-events:none;border-radius:5px}}.screens.single figure{{width:390px}}.screens.single .phone{{width:390px;height:844px}}
footer{{position:absolute;left:64px;right:64px;bottom:35px;border-top:1px solid #dcd9d6;padding-top:20px;display:flex;justify-content:space-between;gap:30px;font-size:15px;color:#817a7e}}.url{{font-size:19px;color:#27272b;font-weight:700;letter-spacing:.5px}}
</style></head><body><header><div class="brand"><b>SP</b> Colle</div><div class="category">{html.escape(card['category'])}</div></header><div class="copy"><h1>{title}</h1><p class="lead">{lead}</p><div class="steps">{steps}</div><p class="note">{html.escape(card['note'])}</p></div><div class="screens {'single' if len(screens)==1 else ''}">{''.join(screens)}</div><footer><span class="url">spcolle.com</span><span>実際のUIで手順を紹介 · 写真・名前・取引はサンプル · 2026.10 作成</span></footer></body></html>'''


def render(args, browser, shots):
    output = args.output
    (output / 'images').mkdir(exist_ok=True)
    (output / 'layouts').mkdir(exist_ok=True)
    page = browser.new_page(viewport={'width':1600,'height':1200}, device_scale_factor=1)
    page.route('http://**/*', lambda route: route.abort())
    page.route('https://**/*', lambda route: route.abort())
    records = []
    for card in CARDS:
        markup = compose(card, shots, output)
        path = output / 'layouts' / (card['slug'] + '.html')
        path.write_text(markup, encoding='utf-8')
        page.goto(path.as_uri(), wait_until='load')
        page.evaluate('document.fonts.ready')
        page.wait_for_function('Array.from(document.images).every(img => img.complete && img.naturalWidth>0)')
        assert page.locator('.copy').bounding_box()['y'] + page.locator('.copy').bounding_box()['height'] < 1100, card['slug']
        assert page.locator('h1').evaluate('el => el.clientHeight <= parseFloat(getComputedStyle(el).lineHeight)*2+1'), card['slug']
        for selector in ('h1', 'h2', 'figcaption'):
            assert page.locator(selector).evaluate_all('els => els.every(el => el.scrollWidth <= el.clientWidth+1)'), (card['slug'], selector)
        png = output / 'images' / (card['slug'] + '.png')
        page.screenshot(path=str(png))
        with Image.open(png) as check:
            assert check.size == (1600,1200)
            check.verify()
        records.append(dict(title=card['title'].replace('\n',''), category=card['category'],
                            image=str(png.relative_to(output)), sources=[s[0] for s in card['screens']]))
        print('Rendered ' + card['slug'], flush=True)
    cards = ''.join(f'<article><p>{html.escape(r["category"])}</p><h2>{html.escape(r["title"])}</h2><a href="{r["image"]}"><img src="{r["image"]}" alt="{html.escape(r["title"])}"></a><a class="download" href="{r["image"]}" download>PNGを保存</a></article>' for r in records)
    gallery = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SP Colle トレードの使い方</title><style>body{{font-family:"Yu Gothic",Meiryo,sans-serif;background:#faf9f7;color:#27272b;margin:32px}}header{{max-width:1500px;margin:auto}}h1{{font-size:28px}}header p{{line-height:1.9;color:#686167}}main{{max-width:1500px;margin:auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:35px 26px}}article p{{font-size:12px;color:#97506a;margin-bottom:5px}}h2{{font-size:18px;margin:0 0 14px}}img{{width:100%;height:auto;display:block;border:1px solid #e1dadd}}a{{color:#9f2a50}}.download{{display:inline-block;margin-top:10px;font-size:13px}}@media(max-width:500px){{body{{margin:18px}}main{{display:block}}article{{margin-bottom:30px}}}}</style></head><body><header><h1>SP Colle トレードの使い方</h1><p>募集の公開、写真の検索、交換案の送信、相談・確定・発送・受取まで。各画像を開くと原寸で見られます。<br>画像に連番は付けていません。画面の写真・名前・取引はすべてサンプルです。</p></header><main>{cards}</main></body></html>'''
    (output / 'index.html').write_text(gallery, encoding='utf-8')
    page.set_viewport_size({'width':1600,'height':1200})
    page.goto((output / 'index.html').as_uri(), wait_until='load')
    page.wait_for_function('Array.from(document.images).every(img => img.complete && img.naturalWidth>0)')
    page.screenshot(path=str(output / 'overview.png'), full_page=True)
    source_paths = ['templates/trade/editor.html','templates/trade/listing.html','templates/trade/search.html',
                    'templates/trade/transaction.html','templates/trade/_nav.html','static/js/trade.js',
                    'static/css/trade-market.css','static/css/style.css']
    manifest = dict(created='2026-10-15', size=[1600,1200], images=records,
        provenance='Real Flask routes and templates; isolated in-memory SQLite; synthetic data and local sample images.',
        source_hashes={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in source_paths})
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    readme = ['# SP Colle トレード機能の宣伝・手順画像','',
              '1600×1200pxのPNG。画像にもファイル名にも連番はありません。',
              '[画像ギャラリー](index.html) / [全体プレビュー](overview.png)','',
              '実際のFlaskルート・テンプレートをメモリ内のテスト用SQLiteで操作し、募集作成から交換完了まで撮影しました。',
              '本番DB・実在の利用者・本番の写真は使っていません。名前・写真・取引はサンプルです。',
              '画面上のローズ色の枠は、押すボタンや確認箇所を示す説明用の注釈です。',
              '2026年10月15日のローカル実装に基づきます。公開中サイトへの反映はこの作業には含みません。','',
              '## 画像','']
    readme += [f'- [{r["title"]}]({r["image"]})' for r in records]
    (output / 'README.md').write_text('\n'.join(readme)+'\n', encoding='utf-8')
    archive = output.parent / (output.name + '-trade-guide.zip')
    with ZipFile(archive, 'w', ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                bundle.write(path, str(Path('trade-guide') / path.relative_to(output)))
    with ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    image_archive = output.parent / (output.name + '-trade-guide-images.zip')
    with ZipFile(image_archive, 'w', ZIP_DEFLATED) as bundle:
        for record in records:
            image_path = output / record['image']
            bundle.write(image_path, image_path.name)
    with ZipFile(image_archive) as bundle:
        assert bundle.testzip() is None and len(bundle.namelist()) == len(CARDS)
    print(json.dumps(dict(images=len(records), archive=str(archive), archive_bytes=archive.stat().st_size,
                         images_archive=str(image_archive), images_archive_bytes=image_archive.stat().st_size), ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/trade-guide/2026-10-15')
    parser.add_argument('--browser', type=Path, default=Path(os.environ['LOCALAPPDATA'])/'ms-playwright/chromium-1208/chrome-win64/chrome.exe')
    parser.add_argument('--port', type=int, default=5198)
    parser.add_argument('--reuse-captures', action='store_true')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    server = None if args.reuse_captures else fixture(args.port)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(args.browser))
            shots = json.loads((args.output/'captures.json').read_text(encoding='utf-8')) if args.reuse_captures else capture(args, browser)
            render(args, browser, shots)
            browser.close()
    finally:
        if server:
            server.shutdown()


if __name__ == '__main__':
    main()
