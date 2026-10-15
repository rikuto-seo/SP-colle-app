"""Collection labels must survive normalized ordering, including AJAX refreshes."""
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('SECRET_KEY','photo-order-test-only')
from flask import g
from extensions import db
from models import Costume, Photo, PhotoType, UserPhoto
from test_trade_marketplace import make_app, seed

MAPPED_COSTUME='2018.winter-01.02.03.04(5thシングルスーツ衣装)'
DECORATED_TYPES=['ヒキ（カンフー）','座り（カンフー）','チュウ（カンフー）','ヨリ（カンフー）','10','02']


class CardParser(HTMLParser):
    def __init__(self,html):
        super().__init__();self.cards=[];self.feed(html)

    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if 'data-card' in values:self.cards.append(json.loads(values['data-card']))


class PhotoTypeOrderTest(unittest.TestCase):
    def setUp(self):
        self.app=make_app()
        self.ctx=self.app.app_context();self.ctx.push()
        seed()
        for index,name in enumerate(DECORATED_TYPES,10):
            db.session.add(PhotoType(id=index,name=name))
        db.session.add(Costume(id=10,name=MAPPED_COSTUME,group_id=1))
        for index,name in enumerate(('01','03','04'),30):
            db.session.add(PhotoType(id=index,name=name))
        db.session.flush()
        for index,name in enumerate(DECORATED_TYPES,10):
            db.session.add(Photo(id=2000+index,member_id=1,costume_id=1,type_id=index))
        for index,type_id in enumerate((30,15,31,32)):
            db.session.add(Photo(id=3000+index,member_id=1,costume_id=10,type_id=type_id))
        db.session.flush()
        for photo_id in list(range(2010,2016))+list(range(3000,3004)):
            db.session.add(UserPhoto(user_id=100,photo_id=photo_id,quantity=1))
        db.session.commit()
        self.client=self.app.test_client()
        g.pop('_login_user',None)
        with self.client.session_transaction() as session:
            session['_user_id']='100';session['_fresh']=True

    def tearDown(self):
        db.session.remove();db.drop_all();db.engine.dispose();self.ctx.pop()

    def collection_html(self):
        response=self.client.get('/index/hinatazaka')
        self.assertEqual(response.status_code,200)
        return response.get_data(as_text=True)

    def test_decorated_types_keep_original_labels_and_classification(self):
        cards=CardParser(self.collection_html()).cards
        card=next(c for c in cards if c['costume']=='2026年 春の制服')
        orders={d['type']:d['type_order'] for d in card['details']}
        self.assertEqual(orders,{'ヨリ':1,'ヨリ（カンフー）':1,'チュウ（カンフー）':2,
            'ヒキ（カンフー）':3,'座り（カンフー）':4,'02':999,'10':999})
        self.assertEqual(card['owned'],7)  # Distinct display types are not collapsed.
        for detail in card['details']:
            response=self.client.get(f'/get_user_photo_detail/hinatazaka/{detail["id"]}')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['detail']['type'],detail['type'])
            self.assertEqual(response.json['detail']['type_order'],detail['type_order'])

    def test_numbered_types_use_costume_mapping_only_for_order(self):
        cards=CardParser(self.collection_html()).cards
        card=next(c for c in cards if c['costume']==MAPPED_COSTUME)
        self.assertEqual({d['type']:d['type_order'] for d in card['details']},{'01':3,'02':2,'03':1,'04':4})
        for detail in card['details']:
            refreshed=self.client.get(f'/get_user_photo_detail/hinatazaka/{detail["id"]}').json['detail']
            self.assertEqual((refreshed['type'],refreshed['type_order']),(detail['type'],detail['type_order']))

    def test_add_type_choices_preserve_labels_and_sort_by_classification(self):
        for costume,expected in [
            ('2026年 春の制服',['ヨリ','ヨリ（カンフー）','チュウ（カンフー）','ヒキ（カンフー）','座り（カンフー）','02','10']),
            (MAPPED_COSTUME,['03','02','01','04'])]:
            with self.subTest(costume=costume):
                query=urlencode(dict(group='hinatazaka',member='メンバーA',costume=costume))
                response=self.client.get('/get_types?'+query)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json['types'],expected)
                # The selected original value must still identify the correct photo.
                chosen=expected[0]
                target=UserPhoto.query.join(Photo).join(Costume).join(PhotoType).filter(
                    UserPhoto.user_id==100,Costume.name==costume,PhotoType.name==chosen).one()
                old_quantity=target.quantity
                added=self.client.post('/add/hinatazaka',data=dict(member='メンバーA',costume=costume,photo_type=chosen,quantity=1))
                self.assertEqual(added.status_code,302)
                self.assertEqual(target.quantity,old_quantity+1)


if __name__=='__main__':unittest.main()
