"""Create overview sheets and a shareable archive after page capture."""
import argparse
import json
import math
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from PIL import Image, ImageDraw, ImageFont


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    root=args.directory.resolve()
    data=json.loads((root/'capture-results.json').read_text(encoding='utf-8'))
    pages=data['pages']
    for page in pages:
        expected=2 if page['new'] else 4
        assert len(page['shots'])==expected,(page['template'],page['shots'])
        assert (root/page['comparison']).exists()
        for shot in page['shots']:
            with Image.open(root/shot['path']) as image:
                image.verify()
    font=lambda size:ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc',size)
    for version,title in [('before','修正前：GitHub main 94de73f'),('after','修正後：ローカル')]:
        sheet=Image.new('RGB',(1460,140+math.ceil(len(pages)/6)*510),'#edf1f6')
        draw=ImageDraw.Draw(sheet)
        draw.text((25,20),title,font=font(36),fill='#263346')
        draw.text((25,78),'全44ページ / スマホ幅390px / 各画面の先頭844pxを縮小 / 全体はページ別比較PNGを参照',font=font(19),fill='#4f6174')
        for index,page in enumerate(pages):
            x=25+(index%6)*240;y=140+(index//6)*510
            draw.text((x,y),f'{index+1:02} '+page['label'][:12],font=font(14),fill='#263346')
            path=root/version/f'{page["slug"]}-390.png'
            if path.exists():
                with Image.open(path) as image:
                    panel=Image.new('RGB',(390,844),'white')
                    panel.paste(image.crop((0,0,390,min(844,image.height))))
                    sheet.paste(panel.resize((215,465),Image.Resampling.LANCZOS),(x,y+27))
            else:
                draw.rectangle((x,y+27,x+215,y+492),fill='white')
                draw.text((x+12,y+180),'修正前には存在しない',font=font(16),fill='#4f6174')
                draw.text((x+12,y+212),'新規追加ページ',font=font(16),fill='#4f6174')
        sheet.save(root/f'overview-{version}.png')
    # Keep recorded limitations alongside the binary artifacts.
    data['method']='Actual templates rendered with identical synthetic fixtures. New trade pages use real routes with an isolated SQLite DB. Auth/analytics/billing disabled. Light theme and initial state only; not production screenshots.'
    data['verification']={'pages':len(pages),'comparisons':len(pages),
        'raw_screenshots':sum(len(page['shots']) for page in pages),'new_pages':sum(page['new'] for page in pages),
        'render_failures':len(data['failures']),
        'browser_errors':[{ 'template':p['template'],**s} for p in pages for s in p['shots'] if s['errors']],
        'overflow':[{ 'template':p['template'],'version':s['version'],'width':s['width']} for p in pages for s in p['shots'] if s['overflow']]}
    (root/'capture-results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    readme=root/'README.md'
    text=readme.read_text(encoding='utf-8')
    if 'overview-before.png' not in text:
        text=text.replace('全44ページ、比較画像44枚。','[修正前の全ページ一覧](overview-before.png) / [修正後の全ページ一覧](overview-after.png)\n\n全44ページ、比較画像44枚。')
    verification_note='検証：全ページのHTML描画と画像ファイルの読取を確認。修正前の利用グループ設定ページでは既存JavaScriptのnull参照エラーを記録しています（画面撮影は完了）。詳細はcapture-results.json。'
    if verification_note not in text:
        text+='\n\n'+verification_note+'\n'
    readme.write_text(text,encoding='utf-8')
    archive=root.parent/f'{root.name}-page-comparisons.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED) as zipfile:
        for path in root.rglob('*'):
            if path.is_file():zipfile.write(path,str(Path(root.name)/path.relative_to(root)))
    print(json.dumps({'verification':data['verification'],'archive':str(archive),'archive_bytes':archive.stat().st_size},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
