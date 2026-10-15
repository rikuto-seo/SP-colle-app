"""Capture GitHub/main and working templates with identical synthetic data.

Run with the project virtualenv; never imports app.py or loads production secrets.
"""
import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from threading import Thread
from types import SimpleNamespace as NS
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen, Request

from flask import Flask, g, jsonify, request, send_from_directory
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from test_design_templates import ROOT, fixture_context
sys.path.insert(0, str(ROOT))


LABELS = {
    'index.html':'コレクション', 'lp.html':'トップ・サービス紹介',
    'add.html':'写真を追加', 'give.html':'写真を減らす', 'stats.html':'統計',
    'missing.html':'未所持の写真', 'mypage.html':'マイページ', 'upgrade.html':'料金プラン',
    'dashboard.html':'ダッシュボード', 'group.html':'グループ',
    'select_group.html':'グループ選択', 'force_select_group.html':'利用グループ設定',
    'login.html':'ログイン', 'register.html':'新規登録', 'first-register.html':'初回登録',
    'finish-login.html':'ログイン処理中', 'edit_profile.html':'プロフィール編集',
    'change_password.html':'パスワード変更', 'icon_setting.html':'アイコン設定',
    'confirm_delete_account.html':'退会確認', 'confirm_delete_final.html':'退会の最終確認',
    'payment_success.html':'決済処理中', 'terms.html':'利用規約', 'privacy.html':'プライバシーポリシー',
    'legal.html':'特定商取引法に基づく表記', 'shared_stats.html':'公開コレクション統計',
    'public/index.html':'生写真DB・グループ一覧', 'public/costume_list.html':'生写真DB・衣装一覧',
    'public/costume_detail.html':'生写真DB・衣装詳細', 'public/member_costumes.html':'生写真DB・メンバー衣装',
    'want/index.html':'欲しい写真', 'want/add.html':'欲しい写真を追加',
    'want/public_base.html':'公開の欲しい写真・マッチング',
    'want/public_private.html':'欲しい写真・非公開', 'want/share_setting.html':'欲しい写真の公開設定',
    'shared_collection/shared_view.html':'公開コレクション',
    'shared_collection/not_shared.html':'コレクション・非公開', 'admin/photos.html':'管理・写真DB',
    'trade/search.html':'トレード・募集一覧', 'trade/mine.html':'トレード・自分の募集',
    'trade/editor.html':'トレード・募集作成', 'trade/listing.html':'トレード・募集詳細',
    'trade/transactions.html':'トレード・取引一覧', 'trade/transaction.html':'トレード・取引詳細',
}
NOTES = {
    'lp.html':['ヒーロー、画面プレビュー、機能紹介を再構成。', '新しい配色・余白・ボタン・カードを確認。'],
    'index.html':['検索・コレクションカード・表示切替を再構成。', '共通ヘッダー、フッター、スマホナビを更新。'],
    'mypage.html':['アカウント情報と設定項目のレイアウトを更新。', '共通ナビゲーションとカード・ボタンを更新。'],
    'want/public_base.html':['公開希望リストとトレード導線を更新。', '共通ナビゲーションと表示スタイルを更新。'],
}


def trade_html():
    """Use real new trade routes with an isolated in-memory DB."""
    from test_trade_marketplace import make_app, seed
    from extensions import db
    from trade.models import TradeListing, TradeProposal
    app = make_app()
    with app.app_context():
        seed()
        client = app.test_client()
        def login(uid):
            g.pop('_login_user', None)
            with client.session_transaction() as session:
                session['_user_id'] = str(uid)
                session['_fresh'] = True
        login(100)
        payload = dict(alias='サンプル募集', method='mail', location='', notes='同種優先・郵送希望です。',
            offers=[dict(photo_id=1001, quantity=1, want_mode='any', share_image=False,
                wants=[dict(photo_id=1002, quantity=1, priority='high')])])
        res = client.post('/trade/hinatazaka/new', data={'payload':json.dumps(payload)})
        assert res.status_code == 302, res.get_data(as_text=True)
        listing = TradeListing.query.first()
        listing_url = f'/trade/listing/{listing.public_id}'
        client.post(listing_url+'/visibility', data={'action':'publish','confirm_public':'1'})
        login(200)
        res = client.post(listing_url+'/propose', data={'payload':json.dumps(dict(
            alias='交換希望者',method='mail',owner_items=[dict(photo_id=1001,quantity=1)],
            applicant_items=[dict(photo_id=1002,quantity=1)],note='郵送で交換をお願いします。'))})
        assert res.status_code == 302, (res.status_code, res.get_data(as_text=True))
        proposal = TradeProposal.query.first()
        login(100)
        paths = {'trade/search.html':'/trade/hinatazaka', 'trade/mine.html':'/trade/hinatazaka/mine',
            'trade/editor.html':'/trade/hinatazaka/new', 'trade/listing.html':listing_url,
            'trade/transactions.html':'/trade/hinatazaka/transactions',
            'trade/transaction.html':f'/trade/transaction/{proposal.public_id}'}
        result = {}
        for template,path in paths.items():
            res=client.get(path)
            assert res.status_code == 200, (path,res.status_code)
            result[template]=res.get_data(as_text=True)
        return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser', default='C:/Program Files/Google/Chrome/Application/chrome.exe')
    parser.add_argument('--screenshots-only', action='store_true', help='Capture raw screens for custom comparison layouts')
    parser.add_argument('--baseline-revision', default='94de73f96b151f2e84a40be528f3db4883522949')
    parser.add_argument('--reuse-after', action='store_true', help='Reuse this run\'s verified after screenshots')
    args=parser.parse_args()
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    for folder in ('before','after','comparisons'):
        (out/folder).mkdir(exist_ok=True)
    roots={'before':args.before.resolve(),'after':ROOT}
    previous = {}
    if args.reuse_after:
        assert args.screenshots_only
        saved=json.loads((out/'capture-results.json').read_text(encoding='utf-8'))
        assert saved['baseline']==args.baseline_revision
        previous={(record['template'],shot['width']):shot for record in saved['pages']
                  for shot in record['shots'] if shot['version']=='after'}
    envs={key:Environment(loader=FileSystemLoader(root/'templates'),autoescape=select_autoescape(['html'])) for key,root in roots.items()}
    for env in envs.values():
        env.filters['normalize_type']=lambda value,*args:value
        env.filters['trade_time']=lambda value:value.strftime('%Y/%m/%d %H:%M')
    trade=trade_html()
    app=Flask(__name__,static_folder=None)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    @app.get('/<version>/static/<path:name>')
    def static(version,name):
        return send_from_directory(roots[version]/'static',name)

    @app.get('/<version>/fixture')
    def fixture(version):
        template=request.args['template']
        if template.startswith('trade/'):
            return trade[template].replace('/static/',f'/{version}/static/')
        guest=template in ('lp.html','login.html','register.html','finish-login.html','first-register.html',
            'terms.html','privacy.html','legal.html') or template.startswith(('public/','shared_collection/')) or template=='shared_stats.html'
        ctx=fixture_context(template, authenticated=not guest)
        ctx['share']=NS(want_public=False)
        ctx['all_photos']=[NS(id=i,member='サンプルメンバー',costume='2026年 春の衣装',photo_type=t) for i,t in enumerate(['ヨリ','チュウ','ヒキ'],1)]
        ctx['owned_photo_ids']={1,2}
        ctx['get_flashed_messages']=lambda **kwargs:[]
        if template=='admin/photos.html':
            ctx['current_user'].id=1
        html=envs[version].get_template(template).render(**ctx)
        return html.replace('/static/',f'/{version}/static/')

    @app.route('/<path:path>',methods=['GET','POST'])
    def api(path):
        if 'get_owned_members' in path or 'get_members' in path:
            return jsonify(members=['サンプルメンバーA','サンプルメンバーB'])
        if 'get_owned_costumes' in path or 'get_costumes' in path:
            return jsonify(costumes=['2026年 春の衣装'])
        if 'get_types' in path or 'get_owned_types' in path:
            return jsonify(types=['ヨリ','チュウ','ヒキ'])
        return jsonify(success=True,ready=False,items=[],photos=[],rows=[],has_next=False,page=1)

    server=make_server('127.0.0.1',0,app,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    cache={}; results=[]; failures=[]
    templates=sorted(LABELS)
    actual={p.relative_to(ROOT/'templates').as_posix() for p in (ROOT/'templates').rglob('*.html') if not p.name.startswith('_') and p.name not in ('base.html','base_public.html')}
    assert set(templates)==actual, (actual-set(templates),set(templates)-actual)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=args.browser)
        def external(route):
            url=route.request.url
            if urlparse(url).hostname in ('cdn.jsdelivr.net','cdnjs.cloudflare.com','cdn.tailwindcss.com',
                                          'fonts.googleapis.com','fonts.gstatic.com','code.jquery.com'):
                try:
                    if url not in cache:
                        with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as response:
                            cache[url]=(response.read(),response.headers.get('Content-Type','application/octet-stream'))
                    body,typ=cache[url]; route.fulfill(body=body,content_type=typ)
                except Exception as exc:
                    failures.append(f'asset {url}: {exc}'); route.abort()
            else:
                route.abort()
        for number,template in enumerate(templates,1):
            slug=template.replace('/','--').replace('.html','')
            record={'template':template,'label':LABELS[template],'slug':slug,'new':not (roots['before']/'templates'/template).exists(),'shots':[]}
            retired = template in ('upgrade.html','payment_success.html','select_group.html','force_select_group.html')
            if args.screenshots_only:
                record['retired'] = retired
            for version in roots:
                if version=='before' and record['new']:continue
                if args.screenshots_only and version=='after' and retired:continue
                for width,height in ((390,844),(1440,900)):
                    if version=='after' and args.reuse_after:
                        shot=previous[(template,width)]
                        with Image.open(out/shot['path']) as check:check.verify()
                        record['shots'].append(shot)
                        continue
                    context=browser.new_context(viewport={'width':width,'height':height},service_workers='block',reduced_motion='reduce',locale='ja-JP',timezone_id='Asia/Tokyo')
                    context.route('https://**/*',external)
                    page=context.new_page(); errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    url=origin+f'/{version}/fixture?'+urlencode({'template':template})
                    if args.screenshots_only:
                        print(f'Capturing {version}: {template} ({width}px)',flush=True)
                    response=page.goto(url,wait_until='networkidle',timeout=60000)
                    if response.status!=200:
                        failures.append(f'{version} {template}: HTTP {response.status}')
                        context.close();continue
                    page.evaluate('document.fonts.ready')
                    page.add_style_tag(content='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}')
                    page.evaluate('document.activeElement?.blur();window.scrollTo(0,0)')
                    path=out/version/f'{slug}-{width}.png'
                    page.screenshot(path=str(path),full_page=True,timeout=90000,animations='disabled')
                    record['shots'].append({'version':version,'width':width,'path':str(path.relative_to(out)),
                        'errors':errors,'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth+1')})
                    context.close()
            results.append(record)
            print(f'Captured {template}' if args.screenshots_only else f'{number}/{len(templates)} captured {template}',flush=True)
        browser.close()
    server.shutdown()
    (out/'capture-results.json').write_text(json.dumps({'baseline':args.baseline_revision,
        'method':'Real templates + identical synthetic fixtures; trade uses isolated in-memory SQLite and real routes. Auth, analytics and billing disabled. Light theme, default initial state.',
        'failures':failures,'pages':results},ensure_ascii=False,indent=2),encoding='utf-8')
    if failures:
        raise RuntimeError(failures)
    if args.screenshots_only:
        source={}
        for key,root in roots.items():
            source[key]={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ('templates','static') for p in (root/folder).rglob('*') if p.is_file()}
        (out/'source-hashes.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'DONE: raw captures in {out}',flush=True)
        return
    fontpath='C:/Windows/Fonts/meiryo.ttc'
    def font(size):return ImageFont.truetype(fontpath,size)
    def txt(canvas,xy,value,size=22,color='#273245'):
        ImageDraw.Draw(canvas).text(xy,value,font=font(size),fill=color)
    for number,record in enumerate(results,1):
        slug=record['slug']; rows=[]
        for width in (390,1440):
            after=Image.open(out/'after'/f'{slug}-{width}.png').convert('RGB')
            before=None if record['new'] else Image.open(out/'before'/f'{slug}-{width}.png').convert('RGB')
            h=max(after.height,before.height if before else 844)
            a=Image.new('RGB',(width,h),'white');a.paste(after)
            b=Image.new('RGB',(width,h),'white')
            if before:b.paste(before)
            else:
                txt(b,(30,80),'修正前には存在しないページ',18)
                txt(b,(30,120),'GitHub main: 94de73f',16)
            if before:
                raw=ImageChops.difference(a,b).convert('L')
                mask=raw.point(lambda v:255 if v>25 else 0).filter(ImageFilter.MaxFilter(3))
                diff=Image.blend(a,Image.new('RGB',a.size,'white'),.65)
                diff.paste('#ff7c32',(0,0,width,h),mask)
            else:
                diff=Image.blend(a,Image.new('RGB',a.size,'#d9f7e8'),.35)
            target=390 if width==390 else 720
            ratio=target/width
            panels=[im.resize((target,round(h*ratio)),Image.Resampling.LANCZOS) for im in (b,a,diff)]
            rows.append((width,panels))
        canvas=Image.new('RGB',(2240,260+sum(panels[0].height+86 for _,panels in rows)),'#edf1f6')
        txt(canvas,(40,20),f'{number:02}  {record["label"]}',34)
        txt(canvas,(40,75),record['template'],20)
        notes=['新規追加：GitHubの修正前には対応ページがありません。'] if record['new'] else NOTES.get(record['template'],['共通CSS・ヘッダー・フッターの変更を含む画面比較。','内容は両版で同一のサンプルデータを使用。'])
        for i,note in enumerate(notes):txt(canvas,(40,115+i*33),note,22)
        txt(canvas,(40,205),'左：GitHub main（94de73f）  /  中央：修正後のローカル  /  右：橙色が描画差分（位置のずれも含む）',20)
        y=260
        for width,panels in rows:
            txt(canvas,(40,y),'スマホ 390 × 844' if width==390 else 'PC 1440 × 900（表示は50%縮小）',22)
            x=40
            for label,panel in zip(('修正前','修正後','新規ページ' if record['new'] else '差分'),panels):
                txt(canvas,(x,y+34),label,18)
                canvas.paste(panel,(x,y+72));x+=panel.width+20
            y+=panels[0].height+86
        dest=out/'comparisons'/f'{number:02}-{slug}.png'
        canvas.save(dest)
        record['comparison']=str(dest.relative_to(out))
    (out/'capture-results.json').write_text(json.dumps({'baseline':'94de73f96b151f2e84a40be528f3db4883522949','failures':failures,'pages':results},ensure_ascii=False,indent=2),encoding='utf-8')
    readme=['# 各ページの修正前・修正後比較','',
        '修正前：GitHub origin/main `94de73f96b151f2e84a40be528f3db4883522949`。修正後：撮影時のローカルのテンプレート・静的ファイル。',
        '','各比較PNGにはスマホとPCの全ページ撮影を収録。左が修正前、中央が修正後、右が差分です。橙色は描画差分で、要素の移動や高さの変化も含みます。PC欄は50%縮小、元スクリーンショットはbefore/afterに原寸保存。',
        '','実テンプレートに同一サンプルデータを渡して撮影しています。本番サイト・本番データの撮影ではありません。新しいトレードページは実ルートとメモリ内SQLiteを使用。認証・分析・決済の外部通信を停止。ライトモードの初期表示を対象とし、モーダルや各操作後の状態は含みません。',
        '','処理中ページは外部認証・決済を実行せず初期状態で撮影。共通レイアウトと部品テンプレートは個別ページとして撮影せず各ページ内に含めます。',
        '',f'全{len(results)}ページ、比較画像{len(results)}枚。新規{sum(r["new"] for r in results)}ページ。','']
    for r in results:readme.append(f'- [{r["label"]}](comparisons/{Path(r["comparison"]).name})'+('（新規）' if r['new'] else ''))
    (out/'README.md').write_text('\n'.join(readme),encoding='utf-8')
    source={}
    for key,root in roots.items():
        source[key]={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('templates','static') for p in (root/folder).rglob('*') if p.is_file()}
    (out/'source-hashes.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'DONE: {len(results)} comparison images in {out}',flush=True)


if __name__=='__main__':main()
