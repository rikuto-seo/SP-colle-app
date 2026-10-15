"""Compose genuine UI captures as unnumbered, browser-rendered comparison PNGs."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image
from playwright.sync_api import sync_playwright


RETIRED = {
    'upgrade.html': 'すべての機能が無料になったため、料金プラン画面は廃止しました。旧URLはマイページへ移動します。',
    'payment_success.html': '決済が不要になったため、決済処理画面は廃止しました。旧URLはマイページへ移動します。',
    'select_group.html': '3グループすべて利用できるため、この選択画面は廃止しました。',
    'force_select_group.html': '3グループすべて利用できるため、この設定画面は廃止しました。',
}


def data_image(path):
    return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def layout(record, root, width):
    mobile = width == 390
    canvas_width, canvas_height = (1000, 1080) if mobile else (1600, 690)
    frame_width, frame_height = (390, 844) if mobile else (720, 450)
    margin, gap = (70, 80) if mobile else (40, 80)
    label = record['label']
    if record['template'] == 'legal.html':
        label = '運営・利用料金（旧：特商法表記）'
    panels = []
    for version, heading in [('before', '変更前 · GitHub'), ('after', '変更後 · 現在のUI')]:
        path = root / version / f"{record['slug']}-{width}.png"
        if path.exists():
            body = f'<img src="{data_image(path)}" alt="{html.escape(heading)}の画面">'
        else:
            retired = version == 'after' and record.get('retired')
            title = 'この画面は廃止しました' if retired else '変更前にはない画面です'
            note = RETIRED[record['template']] if retired else '新しく追加されたページです。'
            body = f'<div class="notice"><h2>{title}</h2><p>{html.escape(note)}</p></div>'
        panels.append(f'<section><h2 class="panel-label">{heading}</h2><div class="frame">{body}</div></section>')
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>{html.escape(label)}</title>
<style>
*{{box-sizing:border-box}}html,body{{margin:0;width:{canvas_width}px;height:{canvas_height}px;overflow:hidden}}
body{{font-family:Meiryo,"Yu Gothic",sans-serif;background:#fff;color:#26262a}}
header{{position:absolute;top:27px;left:{margin}px;right:{margin}px;display:flex;align-items:center;justify-content:space-between}}
.brand{{font-size:18px;font-weight:700}}.device{{font-size:16px;color:#73737b}}
h1{{position:absolute;left:{margin}px;top:61px;margin:0;font-size:28px;line-height:1.5;font-weight:700}}
.compare{{position:absolute;left:{margin}px;top:122px;display:grid;grid-template-columns:repeat(2,{frame_width}px);gap:{gap}px}}
.panel-label{{margin:0 0 14px;font-size:18px;line-height:26px;font-weight:600}}
.frame{{width:{frame_width}px;height:{frame_height}px;overflow:hidden;outline:1px solid #e4e4e9;background:#fff}}
.frame img{{display:block;width:100%;height:auto}}
.notice{{height:100%;display:flex;flex-direction:column;justify-content:center;gap:20px;padding:35px;color:#73737b;background:#f7f7f9}}
.notice h2{{font-size:22px;line-height:1.6;color:#36363c;margin:0}}.notice p{{font-size:17px;line-height:1.9;margin:0}}
footer{{position:absolute;left:{margin}px;bottom:22px;color:#73737b;font-size:13px;line-height:1.6}}
</style></head><body><header><span class="brand">SP Colle</span><span class="device">{'スマホ' if mobile else 'PC'}</span></header>
<h1>{html.escape(label)}</h1><div class="compare">{''.join(panels)}</div>
<footer>同じサンプルデータで撮影 · 画面の先頭部分 · 2026-10-14</footer></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser', required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    records = json.loads((source / 'capture-results.json').read_text(encoding='utf-8'))
    assert not records['failures'], records['failures']
    output.mkdir(parents=True, exist_ok=True)
    for name in ('mobile', 'desktop', 'layouts'):
        (output/name).mkdir(exist_ok=True)
    manifest = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=args.browser)
        page = browser.new_page()
        page.route('http://**/*', lambda route:route.abort())
        page.route('https://**/*', lambda route:route.abort())
        for record in records['pages']:
            images = {}
            for width, folder, size in [(390,'mobile',(1000,1080)),(1440,'desktop',(1600,690))]:
                filename = f"{record['slug']}.png"
                markup = layout(record, source, width)
                assert not any(token in markup for token in ('番号', '枚目', ' / 44', '01 /'))
                html_path = output/'layouts'/f"{folder}-{record['slug']}.html"
                html_path.write_text(markup, encoding='utf-8')
                page.set_viewport_size({'width':size[0],'height':size[1]})
                page.goto(html_path.as_uri(), wait_until='load')
                page.evaluate('document.fonts.ready')
                page.wait_for_function('Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)')
                assert page.locator('h1').evaluate('element => element.scrollWidth <= element.clientWidth + 1')
                png = output/folder/filename
                page.screenshot(path=str(png))
                with Image.open(png) as check:
                    assert check.size == size
                    check.verify()
                images[folder] = str(png.relative_to(output))
            inputs = {shot['path']:hashlib.sha256((source/shot['path']).read_bytes()).hexdigest() for shot in record['shots']}
            manifest.append(dict(page=record['label'], template=record['template'], slug=record['slug'],
                                 new=record['new'], retired=record.get('retired',False), images=images, source_hashes=inputs))
            print('Composed '+record['template'],flush=True)
        cards = []
        for record in manifest:
            suffix = ' · 新規' if record['new'] else ' · 廃止された画面' if record['retired'] else ''
            cards.append(f'<article><h2>{html.escape(record["page"]+suffix)}</h2><a class="preview" href="{record["images"]["mobile"]}"><img loading="eager" src="{record["images"]["mobile"]}" alt="{html.escape(record["page"])}の比較"></a><p><a href="{record["images"]["mobile"]}">スマホ画像</a><a href="{record["images"]["desktop"]}">PC画像</a></p></article>')
        index = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SP Colle UI比較</title><style>
body{{font-family:Meiryo,sans-serif;color:#26262a;background:#fff;margin:30px}}h1{{font-size:25px}}p{{font-size:13px;color:#73737b;line-height:1.8}}a{{color:#a12b51}}.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}}article{{min-width:0}}h2{{font-size:13px;line-height:1.6}}.preview{{display:block;border:1px solid #e4e4e9}}img{{display:block;width:100%;height:auto}}article p{{display:flex;gap:18px}}
</style></head><body><h1>SP Colle · UI比較</h1><p>左：GitHubの変更前 / 右：現在のUI。画像のナンバリングは付けていません。<br>同じサンプルデータで撮影。新規・廃止ページは画像内で区別しています。</p><div class="gallery">{''.join(cards)}</div></body></html>'''
        (output/'index.html').write_text(index,encoding='utf-8')
        page.set_viewport_size({'width':1700,'height':1200})
        page.goto((output/'index.html').as_uri(),wait_until='load')
        page.wait_for_function('Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)')
        page.screenshot(path=str(output/'overview.png'),full_page=True)
        browser.close()
    metadata = {'baseline':records['baseline'],'captured_date':'2026-10-14',
                'repository':'https://github.com/rikuto-seo/SP-colle-app','pages':manifest}
    (output/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    readme = ['# SP Colle 新UI・GitHub版の比較','',
              '左：GitHub origin/main `'+records['baseline']+'`。右：2026年10月14日の作業中UI。',
              '画像にもファイル名にも連番を付けていません。スマホ画像は1000×1080px、PC画像は1600×690px。',
              'スマホは幅390pxの先頭844px、PCは幅1440pxの先頭900pxを掲載。全体の原寸スクリーンショットはraw/before・raw/afterに保存しています。',
              '実テンプレートを同じサンプルデータで描画。本番アカウントや本番DBは使わず、認証・広告・分析・決済の外部通信を停止しています。新しいトレードはメモリ内SQLiteと実ルートで表示しています。',
              '旧版にはないページは「変更前にはない画面」、廃止された料金・グループ設定ページは「この画面は廃止しました」と表示しています。',
              '旧版で発生するJavaScriptエラー・横幅超過はraw/capture-results.jsonに記録し、旧コードを書き換えずに撮影しています。',
              '', '[比較画像の一覧](index.html) / [一覧画像](overview.png)', '', '## 各ページ', '']
    readme.extend(f'- [{record["page"]}]({record["images"]["mobile"]}) / [PC]({record["images"]["desktop"]})' for record in manifest)
    (output/'README.md').write_text('\n'.join(readme)+'\n',encoding='utf-8')
    archive = output.parent / (output.name+'-ui-comparisons.zip')
    with ZipFile(archive,'w',ZIP_DEFLATED) as bundle:
        for path in output.rglob('*'):
            if path.is_file():
                bundle.write(path,str(Path(output.name)/path.relative_to(output)))
    print(json.dumps({'pages':len(manifest),'comparison_images':len(manifest)*2,'archive':str(archive),
                      'archive_bytes':archive.stat().st_size},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
