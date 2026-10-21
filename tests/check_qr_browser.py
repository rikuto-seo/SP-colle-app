"""Read real QR pixels through image and video flows; save no screenshots."""
import argparse
import base64
import io
import json
import logging
from threading import Thread
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import qrcode
from PIL import Image
from flask import redirect, request, session
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_qr_check import QrCheckTest
from extensions import db
from models import User


def png(value=None):
    image=qrcode.make(value) if value else Image.new('RGB',(300,300),'white')
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',default='C:/Users/Teikyo/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe')
    args=parser.parse_args()
    fixture=QrCheckTest();fixture.setUp()
    app=fixture.app
    @app.get('/fixture/login/<int:uid>')
    def login(uid):
        user=db.session.get(User,uid);user.dark_mode=request.args.get('dark')=='1';db.session.commit()
        session['_user_id']=str(uid);session['_fresh']=True
        return redirect('/trade/hinatazaka')
    @app.get('/fixture/logout')
    def logout():session.clear();return 'logged out'
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    real_qr=png(fixture.public_url())
    data_url='data:image/png;base64,'+base64.b64encode(real_qr).decode()
    errors=[];cache={}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=args.browser)
            context=browser.new_context(service_workers='block',reduced_motion='reduce',viewport={'width':390,'height':844})
            def external(route):
                url=route.request.url
                if urlparse(url).hostname not in ('cdn.jsdelivr.net','cdnjs.cloudflare.com'):
                    route.abort();return
                if url not in cache:
                    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as response:
                        cache[url]=(response.read(),response.headers.get('Content-Type'))
                body,typ=cache[url];route.fulfill(body=body,content_type=typ)
            context.route('https://**/*',external)
            context.add_init_script('''
                window.__cameraMode = 'qr';
                window.__cameraTracks = [];
                navigator.mediaDevices.getUserMedia = async () => {
                    if (window.__cameraMode === 'denied') throw new DOMException('Denied','NotAllowedError');
                    const canvas=document.createElement('canvas'); canvas.width=500;canvas.height=500;
                    const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,500,500);
                    if (window.__cameraMode === 'qr') {
                        const image=new Image();image.src=QR_DATA;
                        await image.decode();ctx.drawImage(image,0,0,500,500);
                    }
                    const media=canvas.captureStream(10);
                    window.__cameraTracks.push(...media.getTracks());window.__cameraCanvas=canvas;
                    if (window.__cameraMode === 'delayed') await new Promise(resolve=>window.__resolveCamera=resolve);
                    return media;
                };
            '''.replace('QR_DATA',json.dumps(data_url)))
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            posted=[]
            page.on('request',lambda req:posted.append(req.post_data) if req.method=='POST' and '/qr/' in req.url else None)
            def goto(path):page.goto(origin+path,wait_until='networkidle')
            def reset():goto('/trade/qr/hinatazaka')
            def upload(content):page.locator('#qr-file').set_input_files({'name':'qr.png','mimeType':'image/png','buffer':content})
            goto('/fixture/login/100')
            page.get_by_role('button',name='メニューを開く').click()
            page.get_by_role('link',name='QR交換チェック',exact=True).click()
            page.wait_for_load_state('networkidle')
            assert not errors, errors
            assert page.evaluate('typeof jsQR')=='function'
            expect(page.locator('h1')).to_have_text('QR交換チェック')
            assert page.locator('.trade-nav').count()==0
            assert page.locator('.mobile-nav a[aria-current]').count()==0
            expect(page.locator('#qr-camera')).not_to_be_visible()
            page.get_by_role('button',name='カメラで読み取る',exact=True).click()
            expect(page.locator('#qr-results')).to_be_visible(timeout=15000)
            expect(page.locator('#qr-result-summary')).to_contain_text('お互いの希望')
            expect(page.locator('#qr-pairs .qr-pair')).to_have_count(1)
            assert page.evaluate('window.__cameraTracks.every(track=>track.readyState==="ended")')
            expect(page.locator('#qr-camera')).not_to_be_visible()
            reset();page.evaluate('window.__cameraMode="blank"')
            page.locator('#qr-start').click();expect(page.locator('#qr-video')).to_be_visible()
            page.wait_for_function('document.querySelector("#qr-video").srcObject !== null')
            page.locator('#qr-stop').click()
            assert page.evaluate('window.__cameraTracks.every(track=>track.readyState==="ended")')
            page.locator('#qr-start').click()
            page.wait_for_function('document.querySelector("#qr-video").srcObject !== null')
            page.evaluate('window.dispatchEvent(new Event("pagehide"))')
            assert page.evaluate('window.__cameraTracks.every(track=>track.readyState==="ended")')
            reset();page.evaluate('window.__cameraMode="delayed"')
            page.locator('#qr-start').click()
            page.wait_for_function('typeof window.__resolveCamera === "function"')
            page.locator('#qr-stop').click();page.evaluate('window.__resolveCamera()')
            page.wait_for_function('window.__cameraTracks.every(track=>track.readyState==="ended")')
            expect(page.locator('#qr-camera')).not_to_be_visible()
            reset();page.evaluate('window.__cameraMode="denied"')
            page.locator('#qr-start').click()
            expect(page.locator('#qr-error')).to_contain_text('許可されていません')
            expect(page.locator('#qr-start')).to_be_enabled()
            reset();upload(real_qr)
            expect(page.locator('#qr-results')).to_be_visible()
            expect(page.locator('#qr-result-lists')).to_contain_text('メンバーA')
            expect(page.locator('#qr-result-lists')).to_contain_text('メンバーB')
            assert all(set(json.loads(body))=={'url'} for body in posted)
            reset();upload(png())
            expect(page.locator('#qr-error')).to_contain_text('見つけられませんでした')
            expect(page.locator('#qr-results')).not_to_be_visible()
            upload(png('https://example.com/not-spcolle'))
            expect(page.locator('#qr-error')).to_contain_text('SP Colle')
            assert page.url==origin+'/trade/qr/hinatazaka'
            page.locator('.qr-url-input summary').click()
            page.locator('#qr-url').fill(fixture.public_url())
            page.get_by_role('button',name='判定する',exact=True).click()
            expect(page.locator('#qr-results')).to_be_visible()
            for dark in (False,True):
                goto('/fixture/login/100'+('?dark=1' if dark else ''));reset()
                for width in (320,390,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
                    upload(real_qr);expect(page.locator('#qr-results')).to_be_visible()
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            page.request.get(origin+'/fixture/logout')
            page.locator('.qr-url-input summary').click()
            page.locator('#qr-url').fill(fixture.public_url())
            page.get_by_role('button',name='判定する',exact=True).click()
            expect(page.locator('#qr-login')).to_be_visible()
            expect(page.locator('#qr-error')).to_contain_text('ログインし直して')
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown();fixture.tearDown()
    print('PASS: sidebar entry; real QR pixel decoding from images and simulated camera streams; camera cleanup/late permission/denial; URL fallback; invalid QR; login expiry; mobile/desktop/dark mode. No screenshots saved.')


if __name__=='__main__':main()
