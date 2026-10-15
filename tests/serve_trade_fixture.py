"""Local-only browser fixture. Uses an in-memory database and synthetic users."""
import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import request, session, redirect, jsonify, Response
from extensions import db, csrf
from test_trade_marketplace import make_app, seed
from trade.models import TradeListing, TradeOffer, TradeWant, TradeProposal
from models import User, UserPhoto, UserPhotoImage, Member, Photo, Costume

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=5197)
args=parser.parse_args()
app=make_app()
app.jinja_env.auto_reload=True
app.config['WTF_CSRF_ENABLED']=True
os.environ['R2_PUBLIC_BASE_URL'] = f'http://127.0.0.1:{args.port}/fixture/image'


@app.post('/fixture/reset')
@csrf.exempt
def reset():
    assert app.testing and app.config['SQLALCHEMY_DATABASE_URI']=='sqlite://'
    db.session.remove(); db.drop_all(); seed()
    return jsonify(ok=True)


@app.post('/fixture/gallery')
@csrf.exempt
def gallery():
    assert app.testing and app.config['SQLALCHEMY_DATABASE_URI']=='sqlite://'
    db.session.remove(); db.drop_all(); seed()
    names = ['朝日 花音','小川 芽衣','青山 凛','白井 日菜','森 結衣','花宮 すず','西園寺 美咲','橘 紗月']
    for index, name in enumerate(names):
        db.session.add(Member(id=10+index, name=name, group_id=1, display_order=index))
    for index, name in enumerate(['2026年 夏制服','ライブTシャツ','浴衣','周年記念のスペシャル衣装']):
        db.session.add(Costume(id=10+index, name=name, group_id=1))
    db.session.flush()
    for index in range(8):
        db.session.add(Photo(id=2000+index, member_id=10+index, costume_id=10+index%4, type_id=1+index%3))
    db.session.flush()
    stock = {}
    for index in range(8):
        stock[index] = UserPhoto(user_id=100, photo_id=2000+index, quantity=100)
        db.session.add(stock[index])
    db.session.flush()
    images = {}
    for index in range(8):
        image = UserPhotoImage(user_id=100,user_photo_id=stock[index].id,
                              image_key=f'{index}.svg',thumbnail_key=f'{index}.svg')
        db.session.add(image); images[index] = image
    db.session.flush()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for index in range(24):
        source = index%8; desired = (index+3)%8
        listing = TradeListing(user_id=100,group_id=1,alias=f'サンプル募集 {index+1:02}',
            method=['mail','meet','either'][index%3],status='open',bundle=index%5==0,
            created_at=now-timedelta(minutes=index),updated_at=now-timedelta(minutes=index))
        offer = TradeOffer(photo_id=2000+source,quantity=1,want_mode='any',
                           image_id=images[source].id if index%3!=1 else None)
        offer.wants.append(TradeWant(photo_id=2000+desired,quantity=1,priority='high' if index%2 else 'normal'))
        if index%4==0:
            offer.wants.append(TradeWant(photo_id=2000+(desired+1)%8,quantity=1,priority='normal'))
        listing.offers.append(offer)
        if listing.bundle:
            listing.offers.append(TradeOffer(photo_id=2000+(source+1)%8,quantity=1,want_mode='all'))
        db.session.add(listing)
    db.session.commit()
    return jsonify(ok=True)


@app.get('/fixture/image/<int:index>.svg')
def image(index):
    colors = ['#c9d7df','#dfcdd4','#c9d7c9','#dfd8c4']
    color = colors[index%4]
    # Synthetic image fixture; no R2 or real user's images are accessed.
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="89" height="127" viewBox="0 0 89 127"><rect width="89" height="127" fill="#fff"/><rect x="4" y="4" width="81" height="113" fill="{color}"/><circle cx="44" cy="41" r="14" fill="#f3e8dd"/><path d="M29 37c-2-24 34-24 30 5-6-12-20-13-30-5z" fill="#62626b"/><path d="M16 111V77c0-24 57-24 57 0v34z" fill="#fff" opacity=".65"/><path d="m36 62 8 15 8-15" fill="#f3e8dd"/><path d="M44 77v34" stroke="{color}"/><text x="44" y="124" fill="#777" font-family="sans-serif" font-size="4" text-anchor="middle">SAMPLE IMAGE</text></svg>'
    return Response(svg,mimetype='image/svg+xml')


@app.get('/fixture/login/<int:uid>')
def login(uid):
    user=db.session.get(User,uid)
    if user is None: return 'invalid fixture user',404
    user.dark_mode=request.args.get('dark')=='1'; db.session.commit()
    session['_user_id']=str(uid); session['_fresh']=True
    return redirect('/trade/hinatazaka')


@app.get('/fixture/logout')
def logout():
    session.clear()
    return redirect('/trade/hinatazaka')


@app.get('/fixture/state')
def state():
    return jsonify(listings=TradeListing.query.count(),proposals=TradeProposal.query.count(),
        statuses=[p.status for p in TradeProposal.query.all()],
        stock=[dict(user=p.user_id,photo=p.photo_id,quantity=p.quantity) for p in UserPhoto.query.all()])


with app.app_context(): seed()
print(f'Trade fixture at http://127.0.0.1:{args.port} (memory-only, no app.py)',flush=True)
app.run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False)
