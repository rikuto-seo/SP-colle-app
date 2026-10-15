"""Exercise the plus/arrow editor, linked choices and centered feedback in Chromium."""
import argparse
import logging
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import redirect, request, session
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_trade_picker import ROOT, TradePickerTest
from extensions import db
from models import User


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',default='C:/Users/Teikyo/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/trade-picker-review')
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    fixture=TradePickerTest(); fixture.setUp()
    app=fixture.app
    @app.get('/fixture-login/<int:uid>')
    def login(uid):
        user=db.session.get(User,uid); user.dark_mode=request.args.get('dark')=='1';db.session.commit()
        session['_user_id']=str(uid);session['_fresh']=True
        return redirect('/trade/hinatazaka/new')
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    cache={}; errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=args.browser)
            context=browser.new_context(viewport={'width':390,'height':844},service_workers='block',reduced_motion='reduce')
            def external(route):
                url=route.request.url
                if urlparse(url).hostname not in ('cdn.jsdelivr.net','cdnjs.cloudflare.com'):
                    route.abort();return
                if url not in cache:
                    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as response:
                        cache[url]=(response.read(),response.headers.get('Content-Type'))
                body,typ=cache[url];route.fulfill(body=body,content_type=typ)
            context.route('https://**/*',external)
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            def goto(path): page.goto(origin+path,wait_until='networkidle')
            def ready(): page.wait_for_function('document.querySelector("#picker-results").getAttribute("aria-busy") !== "true"')
            def open_picker(name,index=0):
                page.get_by_role('button',name=name,exact=True).nth(index).click();ready()
                expect(page.locator('#trade-photo-dialog')).to_be_visible()
            def choose(text):
                page.locator('.trade-picker-photo').filter(has_text=text).first.click()
                expect(page.locator('#trade-photo-dialog')).not_to_be_visible()
                expect(page.locator('#trade-feedback')).to_have_text('追加しました')
                expect(page.locator('#trade-feedback')).to_be_visible()
                box=page.locator('#trade-feedback').bounding_box(); view=page.viewport_size
                assert abs(box['x']+box['width']/2-view['width']/2)<2
                assert abs(box['y']+box['height']/2-view['height']/2)<2
            def selected(key,value):
                page.locator(f'#picker-{key}').evaluate('(el,value)=>el.tomselect.setValue(value)',value);ready()
            def options(key):
                return page.locator(f'#picker-{key}').evaluate('el=>Object.values(el.tomselect.options).sort((a,b)=>a.$order-b.$order).map(x=>String(x.value)).filter(Boolean)')
            def shot(name):
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1'),name
                if page.locator('#trade-photo-dialog').is_visible():
                    page.screenshot(path=str(args.output/(name+'.png')))
                else:
                    expect(page.locator('#trade-feedback')).not_to_be_visible(timeout=2400)
                    page.evaluate('document.activeElement?.blur();window.scrollTo(0,0)')
                    page.wait_for_timeout(80)
                    page.screenshot(path=str(args.output/(name+'.png')),full_page=True)
                    if name.startswith('editor-'):
                        page.locator('#editor-offers').screenshot(path=str(args.output/(name+'-rows.png')),
                            style='.site-header,.mobile-nav,.skip-link,.scroll-top-btn,.back-to-top {visibility:hidden!important}')
            goto('/fixture-login/100')
            assert page.locator('#picker-target').count()==0
            open_picker('譲る写真を追加')
            assert options('member')==['10','2','1']
            page.locator('#picker-member').evaluate('el=>el.tomselect.open()')
            assert page.locator('#picker-member-ts-dropdown .option[data-value]').evaluate_all('els=>els.map(el=>el.dataset.value).filter(Boolean)')==['10','2','1']
            page.keyboard.press('Escape')
            choose('松田好花 / 2026年 春の制服 / ヨリ')
            assert page.locator('#trade-offer-0').count()==1
            page.screenshot(path=str(args.output/'added-feedback.png'))
            expect(page.locator('#trade-feedback')).not_to_be_visible(timeout=2400)
            open_picker('欲しい写真を追加')
            assert options('member')==['10','11','2','1','12']
            selected('member','1');assert set(options('costume'))=={'1','10','11'}
            selected('costume','10');assert options('type')==['10']
            assert 'ヨリ（カンフー）' not in page.locator('#picker-type').inner_text()
            shot('dependent-choices')
            choose('松田好花 / 2018.winter / 01')
            assert page.locator('#trade-want-0-0 .trade-cell-type').inner_text()=='01'
            page.locator('#trade-want-0-0 .trade-remove-photo').click()
            open_picker('欲しい写真を追加');choose('メンバーB / 2026年 春の制服 / チュウ')
            page.locator('#trade-want-0-0 .trade-priority').select_option('high')
            page.locator('#trade-offer-0 .trade-quantity').fill('2')
            page.locator('#offer-mode-0').select_option('all')
            open_picker('譲る写真を追加');choose('メンバーB / ライブ衣装 / ヒキ')
            open_picker('欲しい写真を追加',1);choose('メンバーB / 2026年 春の制服 / チュウ')
            assert page.locator('.trade-edit-pair').count()==2
            assert page.locator('#offer-mode-0').input_value()=='all'
            assert page.locator('#trade-want-0-0 .trade-priority').input_value()=='high'
            assert page.locator('#trade-offer-0 .trade-quantity').input_value()=='2'
            page.locator('#listing-bundle').check()
            assert page.locator('.trade-want-mode').count()==0
            page.locator('#listing-bundle').uncheck()
            for width,label in [(320,'small'),(390,'mobile'),(1440,'desktop')]:
                page.set_viewport_size({'width':width,'height':900});shot('editor-'+label)
                assert page.locator('.trade-swap-arrow').all_text_contents()==['⇅','⇅']
                assert 'この提供写真1枚と交換したい内容' not in page.locator('body').inner_text()
            page.set_viewport_size({'width':390,'height':844})
            open_picker('譲る写真を追加')
            page.locator('.trade-picker-photo').filter(has_text='松田好花 / 2026年 春の制服 / ヨリ').click()
            expect(page.locator('#picker-error')).to_have_text('登録済みです。枚数を調整してください。')
            expect(page.locator('#trade-photo-dialog')).to_be_visible()
            page.get_by_role('button',name='写真の選択を閉じる').click()
            page.locator('#listing-alias').fill('行形式の交換募集')
            page.get_by_role('button',name='下書きを保存して公開内容を確認').click();page.wait_for_load_state('networkidle')
            listing=urlparse(page.url).path;assert '/listing/' in listing
            page.locator('#confirm-public').check()
            page.get_by_role('button',name='確認した内容を公開').click();page.wait_for_load_state('networkidle')
            for dark in (False,True):
                goto('/fixture-login/100'+('?dark=1' if dark else ''))
                goto(listing+'/edit')
                assert page.locator('.trade-edit-pair').count()==2
                assert page.locator('#trade-offer-0 .trade-cell-member').inner_text()=='松田好花'
                shot('edit-dark' if dark else 'edit-light')
            goto('/fixture-login/200');goto(listing)
            page.locator('#request-1001').fill('1')
            open_picker('渡す写真を追加');choose('メンバーB / 2026年 春の制服 / チュウ')
            assert page.locator('#trade-provide-0 .trade-cell-type').inner_text()=='チュウ'
            shot('proposal')
            page.get_by_role('button',name='選んだ交換案を送る').click();page.wait_for_load_state('networkidle')
            assert '/transaction/' in page.url,page.locator('body').inner_text()
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown();fixture.tearDown()
    print('PASS: plus-based offers/wants, real dependent choices, member order, centered 1.5s feedback, duplicates, edit, proposal, responsive layouts and dark mode.')


if __name__=='__main__':main()
