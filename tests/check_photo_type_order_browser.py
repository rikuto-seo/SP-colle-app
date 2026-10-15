"""Exercise real collection data and AJAX refresh in the browser, without accounts."""
import argparse
import logging
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import Flask, jsonify, request
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from test_photo_type_order import ROOT, PhotoTypeOrderTest, CardParser, MAPPED_COSTUME


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',default='C:/Program Files/Google/Chrome/Application/chrome.exe')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/photo-type-order-review')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    fixture=PhotoTypeOrderTest();fixture.setUp()
    try:
        html=fixture.collection_html()
        cards=CardParser(html).cards
        add_response=fixture.client.get('/add/hinatazaka')
        assert add_response.status_code==200
        add_html=add_response.get_data(as_text=True)
        members=fixture.client.get('/get_members?group=hinatazaka').json
        costumes=fixture.client.get('/get_costumes?'+urlencode(dict(group='hinatazaka',member='メンバーA'))).json
        options={costume:fixture.client.get('/get_types?'+urlencode(dict(group='hinatazaka',member='メンバーA',costume=costume))).json
            for costume in costumes['costumes']}
        details={str(detail['id']):fixture.client.get(f'/get_user_photo_detail/hinatazaka/{detail["id"]}').json
            for card in cards for detail in card['details']}
    finally:fixture.tearDown()
    app=Flask(__name__,static_folder=str(ROOT/'static'))
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.add_url_rule('/','collection',lambda:html)
    app.add_url_rule('/add/hinatazaka','add',lambda:add_html)
    @app.get('/get_user_photo_detail/<group>/<photo_id>')
    def detail(group,photo_id):return jsonify(details[photo_id])
    @app.route('/<path:path>')
    def api(path):
        if path=='get_members':return jsonify(members)
        if path=='get_costumes':return jsonify(costumes)
        if path=='get_types':return jsonify(options[request.args['costume']])
        return jsonify(members=[],costumes=[],types=[],success=True)
    server=make_server('127.0.0.1',0,app,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    cache={}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=args.browser)
            def external(route):
                url=route.request.url
                if urlparse(url).hostname in ('cdn.jsdelivr.net','cdnjs.cloudflare.com'):
                    if url not in cache:
                        with urlopen(url,timeout=30) as response:
                            cache[url]=(response.read(),response.headers.get('Content-Type'))
                    body,typ=cache[url];route.fulfill(body=body,content_type=typ)
                else:route.abort()
            for width in (390,1440):
                context=browser.new_context(viewport={'width':width,'height':900},service_workers='block',reduced_motion='reduce')
                context.route('https://**/*',external)
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='networkidle')
                for costume,expected,name in [
                    ('2026年 春の制服',['ヨリ','ヨリ（カンフー）','チュウ（カンフー）','ヒキ（カンフー）','座り（カンフー）','02','10'],'decorated'),
                    (MAPPED_COSTUME,['03','02','01','04'],'numbered')]:
                    card=page.locator('.card-item').filter(has=page.locator('.costume-name',has_text=costume))
                    card.click();page.locator('#detailModal.show').wait_for()
                    actual=page.locator('#detailList .detail-photo strong').all_text_contents()
                    assert actual==expected,(width,costume,actual)
                    first_id=page.evaluate('activeCard.details[0].id')
                    # The existing update flow replaces a detail then re-sorts and renders.
                    page.evaluate('(id) => refreshActiveDetail(id)',first_id)
                    assert page.locator('#detailList .detail-photo strong').all_text_contents()==expected
                    page.screenshot(path=str(args.output/f'{name}-{width}.png'),full_page=True)
                    page.locator('#detailModal .btn-close').click()
                    page.locator('#detailModal').wait_for(state='hidden')
                # Old payloads lacking the new server sort field still retain their labels.
                old=page.evaluate('sortPhotoDetails([{type:"ヒキ（カンフー）"},{type:"ヨリ（カンフー）"},{type:"座り（カンフー）"},{type:"チュウ（カンフー）"}]).map(d=>d.type)')
                assert old==['ヨリ（カンフー）','チュウ（カンフー）','ヒキ（カンフー）','座り（カンフー）']

                page.goto(f'http://127.0.0.1:{server.server_port}/add/hinatazaka',wait_until='networkidle')
                page.evaluate('document.querySelector("#member").tomselect.setValue("メンバーA")')
                page.wait_for_function('(costume) => !!document.querySelector("#costume").tomselect.options[costume]',arg=MAPPED_COSTUME)
                for costume,expected,name in [
                    ('2026年 春の制服',['ヨリ','ヨリ（カンフー）','チュウ（カンフー）','ヒキ（カンフー）','座り（カンフー）','02','10'],'decorated'),
                    (MAPPED_COSTUME,['03','02','01','04'],'numbered')]:
                    page.evaluate('(costume) => document.querySelector("#costume").tomselect.setValue(costume)',costume)
                    page.wait_for_function('(count) => Object.keys(document.querySelector("#photo_type").tomselect.options).length===count',arg=len(expected))
                    page.locator('#photo_type-ts-control').click()
                    actual=page.locator('#photo_type-ts-dropdown .option').all_text_contents()
                    assert actual==expected,(width,costume,actual)
                    page.screenshot(path=str(args.output/f'add-{name}-{width}.png'),full_page=True)
                    page.locator('#photo_type-ts-dropdown .option').filter(has_text=expected[0]).first.click()
                    selected=page.locator('#photo_type').input_value()
                    assert selected==expected[0],(selected,expected[0])
                assert not errors,errors
                context.close()
            browser.close()
    finally:server.shutdown()
    print('PASS: collection/AJAX and add-page dropdown preserve original labels/values and normalized order at 390/1440px.')


if __name__=='__main__':main()
