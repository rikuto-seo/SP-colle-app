"""Browser regression with rendered synthetic snapshots, never production data."""
import argparse
import json
import logging
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import urlparse
from urllib.request import urlopen

from flask import Flask, jsonify, request
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from test_type_normalization import TypeNormalizationTest
from extensions import db
from models import Member, Photo, Costume, UserPhoto, WantShare

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', default='C:/Program Files/Google/Chrome/Application/chrome.exe')
    parser.add_argument('--output', type=Path, default=Path(tempfile.gettempdir()) / 'spcolle-stats-review')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = TypeNormalizationTest()
    fixture.setUp()
    try:
        db.session.get(Member, 2).name = db.session.get(Member, 1).name
        db.session.add(UserPhoto(user_id=100, photo_id=1002, quantity=4))
        db.session.add_all([Costume(id=1000+i, name=f'Bulk {i}', group_id=1) for i in range(120)])
        db.session.flush()
        db.session.add_all([Photo(id=3000+i, member_id=1, costume_id=1000+i, type_id=1) for i in range(120)])
        db.session.add(WantShare(user_id=100, group_key='hinatazaka', public_uuid='browser', is_public=True))
        db.session.commit()
        paths = ['/stats/hinatazaka', '/missing/hinatazaka',
                 '/missing/hinatazaka?member_id=2&costume_id=2',
                 '/shared/hinatazaka/browser', '/shared/hinatazaka/browser?page=2',
                 '/share/hinatazaka/browser']
        snapshots = {}
        for path in paths:
            response = fixture.client.get(path)
            assert response.status_code == 200, path
            snapshots[path] = response.get_data(as_text=True)
        details = {i: fixture.client.get(f'/stats/member/hinatazaka/id/{i}').json for i in (1, 2)}
    finally:
        fixture.tearDown()

    app = Flask(__name__, static_folder=str(ROOT / 'static'))
    calls = []
    @app.get('/stats/member/<group>/id/<int:member_id>')
    def detail(group, member_id):
        calls.append(member_id)
        return jsonify(details[member_id])
    @app.get('/<path:path>')
    def snapshot(path):
        return snapshots[request.full_path.rstrip('?')]
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    cache = {}
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=args.browser)
            def external(route):
                url = route.request.url
                if urlparse(url).hostname in ('cdn.jsdelivr.net', 'cdnjs.cloudflare.com'):
                    if url not in cache:
                        with urlopen(url, timeout=30) as response:
                            cache[url] = (response.read(), response.headers.get('Content-Type'))
                    body, content_type = cache[url]
                    route.fulfill(body=body, content_type=content_type)
                else:
                    route.abort()
            for width in (390, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 900},
                                              service_workers='block', reduced_motion='reduce')
                context.route('https://**/*', external)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin + '/stats/hinatazaka', wait_until='networkidle')
                page.locator('[data-bs-target="#compStats"]').click()
                page.locator('#compStats.show').wait_for()
                for member_id in (1, 2):
                    page.locator(f'.member-button[data-member-id="{member_id}"]').click()
                    page.wait_for_function('(id) => document.querySelector(`#member-${id} .member-content`).textContent.includes("/")', arg=member_id)
                assert '3/5' in page.locator('#member-1 .member-content').inner_text()
                assert '1/1' in page.locator('#member-2 .member-content').inner_text()
                assert 1 in calls and 2 in calls
                page.locator('[data-bs-target="#typeStats"]').click()
                page.locator('#typeStats.show').wait_for()
                assert page.locator('[data-unclassified-stats]').is_visible()
                assert '5枚' in page.locator('[data-unclassified-stats]').inner_text()
                page.screenshot(path=str(args.output / f'stats-{width}.png'), full_page=True)

                page.goto(origin + '/missing/hinatazaka', wait_until='networkidle')
                page.evaluate('document.querySelector("#member").tomselect.setValue("2")')
                page.evaluate('document.querySelector("#costume").tomselect.setValue("2")')
                page.locator('form button[type="submit"]').click()
                page.wait_for_url('**/missing/hinatazaka?member_id=2&costume_id=2')
                assert page.locator('[data-photo-id="1003"]').count() == 1
                assert page.locator('[data-photo-id="2003"]').count() == 0

                page.goto(origin + '/shared/hinatazaka/browser', wait_until='networkidle')
                assert page.locator('[data-photo-id]').count() == 100
                page.get_by_role('link', name='次のページ').click()
                page.wait_for_url('**/shared/hinatazaka/browser?page=2')
                assert page.locator('[data-photo-id]').count() == 29
                assert '総所持枚数: 27枚' in page.locator('body').inner_text()
                page.screenshot(path=str(args.output / f'shared-{width}.png'), full_page=True)
                page.goto(origin + '/share/hinatazaka/browser', wait_until='networkidle')
                assert '01' in page.locator('body').inner_text()
                assert not errors, errors
                results.append(dict(width=width, passed=True, page_errors=errors))
                context.close()
            browser.close()
    finally:
        server.shutdown()
    (args.output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print('PASS: stats member-ID AJAX, missing ID filters, shared pagination and shared labels at 390/1440px.')


if __name__ == '__main__':
    main()
