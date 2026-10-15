"""Exercise actual trade routes/forms against serve_trade_fixture.py."""
import argparse
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from playwright.sync_api import sync_playwright

parser=argparse.ArgumentParser()
parser.add_argument('--origin',default='http://127.0.0.1:5197')
parser.add_argument('--browser',type=Path,required=True)
parser.add_argument('--output',type=Path,default=Path(tempfile.gettempdir())/'spcolle-trade-marketplace')
args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
assert urlparse(args.origin).hostname in ('127.0.0.1','localhost')
urlopen(Request(args.origin+'/fixture/reset',data=b'',method='POST')).close()
cache={}; errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=str(args.browser))
    context=browser.new_context(service_workers='block',reduced_motion='reduce',viewport={'width':390,'height':900})
    def external(route):
        url=route.request.url
        if urlparse(url).hostname in ('cdn.jsdelivr.net','cdnjs.cloudflare.com'):
            if url not in cache:
                with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as response: cache[url]=(response.read(),response.headers.get('Content-Type'))
            body,typ=cache[url]; route.fulfill(body=body,content_type=typ)
        else: route.abort()
    context.route('https://**/*',external)
    page=context.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('dialog',lambda dialog:dialog.accept())
    def goto(path): page.goto(args.origin+path,wait_until='networkidle')
    def shot(name):
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), name
        page.evaluate('document.activeElement?.blur(); window.scrollTo(0, 0)')
        page.screenshot(path=str(args.output/(name+'.png')),full_page=True)
    def post_click(locator):
        locator.click(); page.wait_for_load_state('networkidle')
    goto('/fixture/login/100')
    goto('/trade/hinatazaka/new')
    assert not errors, errors
    page.get_by_role('button',name='譲る写真を追加',exact=True).click()
    page.locator('.trade-picker-photo').first.wait_for()
    page.locator('.trade-picker-photo').first.click()
    page.get_by_role('button',name='欲しい写真を追加',exact=True).click()
    page.locator('#picker-q').fill('メンバーB 春')
    page.locator('#picker-search').click()
    page.locator('.trade-picker-photo').filter(has_text='チュウ').first.click()
    page.locator('#listing-alias').fill('写真交換の募集者')
    page.locator('#listing-notes').fill('郵送希望。同種優先です。')
    shot('editor-390')
    for width in (320,1440):
        page.set_viewport_size({'width':width,'height':900}); shot(f'editor-{width}')
    page.set_viewport_size({'width':390,'height':900})
    post_click(page.get_by_role('button',name='下書きを保存して公開内容を確認'))
    listing_path=urlparse(page.url).path
    assert '/listing/' in listing_path
    shot('draft-preview-390')
    page.locator('#confirm-public').check()
    post_click(page.get_by_role('button',name='確認した内容を公開'))
    goto('/fixture/logout')
    assert 'PRIVATE-NAME' not in page.locator('body').inner_text()
    shot('public-search-390')
    assert not page.locator('#trade-filters').evaluate('element => element.open')
    page.locator('#trade-filters summary').click()
    page.locator('#trade-side').select_option('want')
    page.locator('#trade-member-ts-control').fill('メンバーB')
    page.locator('#trade-member-ts-dropdown .option[data-value="2"]').click()
    post_click(page.get_by_role('button', name='この条件で見る'))
    assert page.locator('.trade-listing-card').count()==1
    shot('reverse-search-390')
    goto('/fixture/login/200')
    goto(listing_path)
    page.locator('#request-1001').fill('1')
    page.get_by_role('button',name='渡す写真を追加',exact=True).click()
    page.locator('.trade-picker-photo').filter(has_text='チュウ').first.click()
    page.locator('#proposal-note').fill('写真の状態を確認して郵送交換を希望します。')
    shot('proposal-390')
    post_click(page.get_by_role('button',name='選んだ交換案を送る'))
    transaction_path=urlparse(page.url).path
    assert '/transaction/' in transaction_path
    page.locator('#trade-message').fill('梱包は硬質ケースと防水袋を予定しています。')
    post_click(page.get_by_role('button',name='送信',exact=True))
    shot('conversation-390')
    goto('/fixture/login/100'); goto(transaction_path)
    post_click(page.get_by_role('button',name='この内容で交換を確定'))
    assert '交換確定' in page.locator('h1 + p').inner_text()
    shot('accepted-390')
    post_click(page.get_by_role('button',name='発送を連絡'))
    goto('/fixture/login/200'); goto(transaction_path)
    post_click(page.get_by_role('button',name='発送を連絡'))
    post_click(page.get_by_role('button',name='受取を確認'))
    goto('/fixture/login/100'); goto(transaction_path)
    post_click(page.get_by_role('button',name='受取を確認'))
    assert '完了' in page.locator('h1 + p').inner_text()
    shot('completed-390')
    for width in (320,1440):
        page.set_viewport_size({'width':width,'height':900}); shot(f'completed-{width}')
    page.set_viewport_size({'width':390,'height':900})
    goto('/fixture/login/100?dark=1')
    for path,name in [('/trade/hinatazaka','search'),('/trade/hinatazaka/mine','mine'),
        ('/trade/hinatazaka/transactions','transactions'),('/trade/hinatazaka/new','editor'),(transaction_path,'completed')]:
        goto(path); shot(name+'-dark-390')
    goto('/fixture/login/300'); goto(transaction_path)
    assert page.title()=='404 Not Found'

    # A populated gallery uses synthetic data and local image fixtures only.
    urlopen(Request(args.origin+'/fixture/gallery',data=b'',method='POST')).close()
    goto('/fixture/logout')
    assert page.locator('.trade-listing-card').count()==20
    assert not page.locator('#trade-filters').evaluate('element => element.open')
    assert 'PRIVATE-NAME' not in page.locator('body').inner_text()
    for width, columns in ((320,2),(390,2),(768,3),(1440,4)):
        page.set_viewport_size({'width':width,'height':844})
        assert page.locator('#trade-feed').evaluate('element => getComputedStyle(element).gridTemplateColumns.split(" ").length')==columns
        shot(f'gallery-{width}')
        page.screenshot(path=str(args.output/f'gallery-{width}-viewport.png'))
    page.set_viewport_size({'width':390,'height':844})
    first_image=page.locator('.trade-market-media img').first
    assert first_image.evaluate('image => image.complete && image.naturalWidth > 0')
    assert page.locator('.trade-pair-arrow').first.inner_text()=='⇄'
    before_url=page.url
    context.route('**/trade/hinatazaka?page=2',lambda route:route.abort())
    page.locator('[data-trade-more]').click()
    page.get_by_role('status').filter(has_text='読み込めませんでした').wait_for()
    assert page.locator('.trade-listing-card').count()==20
    context.unroute('**/trade/hinatazaka?page=2')
    page.locator('[data-trade-more]').click()
    page.wait_for_function('document.querySelectorAll(".trade-listing-card").length === 24')
    assert page.url==before_url and page.locator('[data-trade-more]').count()==0
    assert len(set(page.locator('.trade-listing-card').evaluate_all('cards => cards.map(card => card.href)')))==24
    goto('/trade/hinatazaka')
    post_click(page.locator('.trade-member-chips').get_by_role('link',name='朝日 花音',exact=True))
    assert set(page.locator('.trade-market-offer .trade-market-caption strong').all_text_contents())=={'朝日 花音'}
    page.locator('#trade-filters summary').click()
    page.locator('#trade-side').select_option('want')
    post_click(page.get_by_role('button',name='この条件で見る'))
    assert set(page.locator('.trade-market-want .trade-market-caption strong').all_text_contents())=={'朝日 花音'}
    post_click(page.locator('.trade-active-filters').get_by_role('link',name='朝日 花音の条件を解除'))
    assert 'member=' not in page.url and 'side=want' in page.url
    post_click(page.locator('.trade-browse-tabs').get_by_role('link',name='セット',exact=True))
    assert page.locator('.trade-listing-card').count()==5
    assert all('セット' in label for label in page.locator('.trade-card-method').all_text_contents())
    goto('/fixture/login/100?dark=1')
    shot('gallery-dark-390')
    page.screenshot(path=str(args.output/'gallery-dark-390-viewport.png'))
    assert not errors,errors
    browser.close()
print(f'PASS: trade lifecycle; responsive gallery, collapsed filters, matched pairs, browse tabs and load-more retry. Screenshots: {args.output}')
