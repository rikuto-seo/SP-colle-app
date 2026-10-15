"""Headless UI checks using synthetic fixtures, without app/DB credentials.

Requires Flask and Playwright (python -m playwright install chromium).
Run: python tests/check_design_browser.py [--output DIRECTORY]
"""
import argparse
import json
import logging
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen

from flask import Flask, jsonify, request
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from test_design_templates import ROOT, render_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(tempfile.gettempdir()) / 'spcolle-design-review')
    parser.add_argument('--browser', type=Path)
    parser.add_argument('--only', help='Comma-separated scenario names for focused checks')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__, static_folder=str(ROOT / 'static'))
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    @app.get('/fixture')
    def fixture():
        return render_fixture(
            request.args.get('template', 'index.html'), dark=request.args.get('dark') == '1',
            authenticated=request.args.get('guest') != '1', empty=request.args.get('empty') == '1',
            group_key=request.args.get('group', 'hinatazaka'),
            with_image=request.args.get('image') == '1',
        )

    @app.route('/<path:path>', methods=['GET', 'POST'])
    def api(path):
        if 'get_owned_members' in path or 'get_members' in path:
            return jsonify(members=['サンプルメンバーA','サンプルメンバーB'])
        if 'get_owned_costumes' in path or 'get_costumes' in path:
            return jsonify(costumes=['2026年 春の衣装'])
        if 'get_types' in path or 'get_owned_types' in path:
            return jsonify(types=['ヨリ','チュウ','ヒキ'])
        return jsonify(success=True, items=[], photos=[], rows=[], has_next=False, page=1)

    server = make_server('127.0.0.1', 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    cache = {}
    failures = []
    results = []

    with sync_playwright() as playwright:
        # An explicitly selected existing browser is useful in offline dev environments.
        launch_options = {'headless': True}
        if args.browser:
            launch_options['executable_path'] = str(args.browser)
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(service_workers='block', reduced_motion='reduce')

        def route_external(route):
            url = route.request.url
            host = urlparse(url).hostname or ''
            if host in ('cdn.jsdelivr.net', 'cdnjs.cloudflare.com'):
                if url not in cache:
                    with urlopen(url, timeout=30) as response:
                        cache[url] = (response.read(), response.headers.get('Content-Type','application/octet-stream'))
                content, content_type = cache[url]
                route.fulfill(body=content, content_type=content_type)
            else:
                # Firebase auth and analytics are deliberately disabled in fixtures.
                route.abort()

        context.route('https://**/*', route_external)
        scenarios = [
            ('collection', 'index.html', {}), ('empty', 'index.html', {'empty':'1'}),
            ('collection-image', 'index.html', {'image':'1'}),
            ('add', 'add.html', {}), ('give', 'give.html', {}), ('stats', 'stats.html', {}),
            ('missing', 'missing.html', {}), ('want', 'want/index.html', {}),
            ('want-add', 'want/add.html', {}), ('trade', 'want/public_base.html', {}),
            ('mypage', 'mypage.html', {}),
            ('db', 'public/index.html', {'guest':'1'}),
            ('db-list', 'public/costume_list.html', {'guest':'1'}),
            ('db-detail', 'public/costume_detail.html', {'guest':'1'}),
            ('lp', 'lp.html', {'guest':'1'}), ('login', 'login.html', {'guest':'1'}),
            ('register', 'register.html', {'guest':'1'}),
            ('setup', 'first-register.html', {'guest':'1'}), ('admin', 'admin/photos.html', {}),
            ('dashboard', 'dashboard.html', {}), ('group', 'group.html', {}),
            ('profile', 'edit_profile.html', {}),
            ('password', 'change_password.html', {}), ('icon', 'icon_setting.html', {}),
            ('shared', 'shared_collection/shared_view.html', {'guest':'1'}),
            ('terms', 'terms.html', {'guest':'1'}), ('privacy', 'privacy.html', {'guest':'1'}),
            ('legal', 'legal.html', {'guest':'1'}),
        ]
        if args.only:
            selected = set(args.only.split(','))
            scenarios = [item for item in scenarios if item[0] in selected]
        for name, template, params in scenarios:
            for width, dark in [(390,False), (1440,False), (390,True)]:
                page = context.new_page()
                page.set_viewport_size({'width':width,'height':900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                query = {'template':template, **params, 'dark':str(int(dark))}
                if dark and template not in ('login.html', 'register.html'):
                    # Public catalog/LP also honor the signed-in user's dark mode.
                    query.pop('guest', None)
                page.goto(origin + '/fixture?' + urlencode(query), wait_until='networkidle')
                page.evaluate('document.fonts.ready')
                overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
                if overflow:
                    failures.append(f'{name} width={width} dark={dark}: horizontal overflow')
                if errors:
                    failures.append(f'{name} width={width} dark={dark}: {errors}')
                screenshot = args.output / f'{name}-{width}{"-dark" if dark else ""}.png'
                page.screenshot(path=str(screenshot), full_page=True)
                if name in ('collection', 'lp', 'db') and width == 390 and not dark:
                    page.screenshot(path=str(args.output / f'{name}-390-viewport.png'))
                results.append({'page':name, 'width':width, 'dark':dark, 'errors':errors, 'overflow':overflow})
                if name in ('collection', 'collection-image'):
                    grid = page.locator('#collection-grid')
                    assert grid.evaluate('element => getComputedStyle(element).gridTemplateColumns.split(" ").length') == 2
                    page.locator('[data-collection-view="images"]').click()
                    assert grid.get_attribute('data-view') == 'images'
                    assert page.locator('[data-collection-view="images"]').get_attribute('aria-pressed') == 'true'
                    assert not page.locator('.collection-card-info').first.is_visible()
                    assert page.locator('.no-image').count() > 0
                    columns = grid.evaluate('element => getComputedStyle(element).gridTemplateColumns.split(" " ).length')
                    assert columns == 3 if width == 390 else columns > 3
                    assert abs(grid.bounding_box()['width'] - page.locator('#main-content').evaluate('e => e.clientWidth - parseFloat(getComputedStyle(e).paddingLeft) - parseFloat(getComputedStyle(e).paddingRight)')) < 2
                    photo_box = page.locator('.collection-card-layout').first.bounding_box()
                    assert abs(photo_box['width'] / photo_box['height'] - 89 / 127) < 0.01
                    assert photo_box['height'] < 185
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
                    page.screenshot(path=str(args.output / f'{name}-images-{width}{"-dark" if dark else ""}.png'), full_page=True)
                    page.reload(wait_until='networkidle')
                    assert grid.get_attribute('data-view') == 'images'
                    if name == 'collection-image':
                        page.locator('.card-image-button').first.click()
                        page.locator('#imagePreviewModal.show').wait_for()
                        assert not page.locator('#detailModal').is_visible()
                        page.keyboard.press('Escape')
                        page.locator('#imagePreviewModal').wait_for(state='hidden')
                    else:
                        page.locator('.card-item').first.click()
                        page.locator('#detailModal.show').wait_for()
                        page.locator('#detailModal .btn-close').click()
                        page.locator('#detailModal').wait_for(state='hidden')
                    page.locator('[data-collection-view="info"]').click()
                    assert grid.get_attribute('data-view') == 'info'
                    assert grid.evaluate('element => getComputedStyle(element).gridTemplateColumns.split(" " ).length') == 2
                    assert page.locator('.card-member').first.is_visible(), (name, width, dark, page.locator('.card-member').first.evaluate('e => ({rect:e.getBoundingClientRect().toJSON(), parent:e.parentElement.parentElement.getBoundingClientRect().toJSON(), html:e.parentElement.parentElement.outerHTML, style:getComputedStyle(e).display})'))
                    card_height = page.locator('.collection-card').first.bounding_box()['height']
                    assert card_height <= 120, f'{name} width={width} dark={dark}: card height {card_height}'
                    assert not page.locator('.collection-search').evaluate('element => element.open')
                    assert page.locator('[data-collection-view="info"]').get_attribute('aria-pressed') == 'true'
                if name == 'collection' and width == 390 and not dark:
                    page.locator('#menu-button').click()
                    assert page.locator('#sidebar').get_attribute('aria-hidden') == 'false'
                    page.keyboard.press('Escape')
                    assert page.locator('#sidebar').get_attribute('aria-hidden') == 'true'
                    assert page.locator('#menu-button').evaluate('element => element === document.activeElement')
                    page.locator('.card-item').first.focus()
                    page.keyboard.press('Enter')
                    page.locator('#detailModal.show').wait_for()
                    page.screenshot(path=str(args.output / 'collection-detail-390.png'), full_page=True)
                    page.locator('#detailModal .btn-close').click()
                    page.locator('.collection-search > summary').click()
                    page.locator('#member-ts-control').fill('サンプル')
                    page.locator('.ts-dropdown .option').first.wait_for()
                    assert page.locator('.mobile-nav a').count() == 4
                if name == 'db-detail' and width == 390 and not dark:
                    page.locator('#member-filter').fill('存在しない名前')
                    assert not page.locator('.member-row').first.is_visible()
                if name == 'lp' and width == 390 and not dark:
                    page.locator('.lp-faq summary').first.click()
                    assert page.locator('.lp-faq details').first.get_attribute('open') is not None
                if name == 'admin' and width == 390 and not dark:
                    assert page.locator('.bg-purple-600').first.evaluate('element => getComputedStyle(element).backgroundColor !== "rgba(0, 0, 0, 0)"')
                if name == 'login' and width == 1440:
                    assert page.locator('#loginForm').bounding_box()['width'] < 600
                if name == 'collection-image' and width == 390 and not dark:
                    page.locator('.card-image-button').first.click()
                    page.locator('#imagePreviewModal.show').wait_for()
                    assert not page.locator('#detailModal').is_visible()
                page.close()
        # Narrow screens and alternate group accents.
        for group in ['nogizaka','sakurazaka','hinatazaka']:
            page = context.new_page()
            page.set_viewport_size({'width':320,'height':800})
            page.goto(origin + '/fixture?' + urlencode({'template':'index.html','group':group}), wait_until='networkidle')
            if page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'):
                failures.append(f'collection group={group} width=320: horizontal overflow')
            assert page.locator('#collection-grid').evaluate('element => getComputedStyle(element).gridTemplateColumns.split(" ").length') == 2
            page.locator('[data-collection-view="images"]').click()
            assert page.locator('#collection-grid').evaluate('element => getComputedStyle(element).gridTemplateColumns.split(" " ).length') == 3
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
            page.locator('[data-collection-view="info"]').click()
            page.screenshot(path=str(args.output / f'collection-{group}-320.png'), full_page=True)
            page.close()
        # Restricted browser storage must not prevent switching views.
        page = context.new_page()
        page.add_init_script('Storage.prototype.getItem = () => { throw new Error("blocked"); }; Storage.prototype.setItem = () => { throw new Error("blocked"); };')
        page.goto(origin + '/fixture?template=index.html', wait_until='networkidle')
        assert page.locator('#collection-grid').get_attribute('data-view') == 'info'
        page.locator('[data-collection-view="images"]').click()
        assert page.locator('#collection-grid').get_attribute('data-view') == 'images'
        page.close()
        browser.close()
    server.shutdown()
    (args.output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Checked {len(results)+3} page/theme/viewport combinations. Screenshots: {args.output}')
    if failures:
        print('\n'.join(failures))
        raise SystemExit(1)
    print('PASS: no page errors or horizontal overflow; navigation, modal, search and DB filter verified.')


if __name__ == '__main__':
    main()
