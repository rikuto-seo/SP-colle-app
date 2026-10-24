"""DB-aware normalization against memory-only SQLite, without production services."""
import unittest
import sys
import os
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SECRET_KEY', 'normalization-isolated-test-only')

from flask import g, template_rendered
from sqlalchemy import event

from extensions import db
from models import Costume, CostumeTypeNormalization, Photo, PhotoType, UserPhoto
from routes.stats import stats_bp
from services.stats_service import build_stats_data, build_member_comp_data
from services.type_normalizer import get_type_resolver
from test_photo_type_order import CardParser, MAPPED_COSTUME
from test_trade_marketplace import make_app, seed


class TypeNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.app.register_blueprint(stats_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        seed()
        db.session.add_all([
            PhotoType(id=10, name='01'), PhotoType(id=11, name='02'),
            PhotoType(id=12, name='03'), PhotoType(id=13, name='99'),
            Costume(id=10, name=MAPPED_COSTUME, group_id=1),
            Costume(id=11, name=MAPPED_COSTUME, group_id=2),
        ])
        db.session.flush()
        for photo_id, member_id, costume_id, type_id in [
            (2001, 1, 10, 10), (2002, 1, 10, 11), (2003, 1, 10, 12),
            (2004, 1, 10, 13), (2005, 3, 11, 10), (2006, 1, 1, 10),
            (2007, 1, 10, 1),
        ]:
            db.session.add(Photo(id=photo_id, member_id=member_id,
                                 costume_id=costume_id, type_id=type_id))
        db.session.flush()
        db.session.add_all([
            CostumeTypeNormalization(costume_id=10, photo_type_id=10, normalized_type='ヨリ'),
            CostumeTypeNormalization(costume_id=11, photo_type_id=10, normalized_type='座り'),
            CostumeTypeNormalization(costume_id=1, photo_type_id=10, normalized_type='チュウ'),
        ])
        for photo_id, qty in [(2001, 2), (2002, 3), (2004, 5), (2005, 7), (2006, 11)]:
            db.session.add(UserPhoto(user_id=100, photo_id=photo_id, quantity=qty))
        db.session.commit()
        self.client = self.app.test_client()
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = '100'
            session['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()

    def test_db_priority_fallback_and_group_costume_identity(self):
        resolver = get_type_resolver(1)
        self.assertEqual(resolver.resolve(10, 10, MAPPED_COSTUME, '01'), 'ヨリ')
        self.assertEqual(resolver.resolve(10, 11, MAPPED_COSTUME, '02'), 'チュウ')
        self.assertEqual(resolver.resolve(1, 10, '2026年 春の制服', '01'), 'チュウ')
        self.assertEqual(get_type_resolver(2).resolve(11, 10, MAPPED_COSTUME, '01'), '座り')

    def test_unknown_numeric_values_remain_and_are_detected_once_per_batch(self):
        resolver = get_type_resolver(1)
        with self.assertLogs('services.type_normalizer', level='WARNING') as logs:
            for _ in range(2):
                self.assertEqual(resolver.resolve(10, 13, MAPPED_COSTUME, '99'), '99')
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(resolver.unresolved, {(10, 13)})
        self.assertEqual(resolver.resolve(1, 13, 'unknown', '特殊'), '特殊')

    def test_stats_quantities_and_both_completion_paths_use_same_resolution(self):
        data = build_stats_data(100, 'hinatazaka')
        self.assertEqual(data['type_stats'], {'ヨリ': 4, 'チュウ': 14, '99': 5})
        self.assertEqual(list(data['type_stats']), ['ヨリ', 'チュウ', '99'])
        costume = next(c for c in data['comp_stats']['メンバーA'] if c['costume'] == MAPPED_COSTUME)
        # 01, 03 and canonical ヨリ collapse to the same required classification.
        self.assertEqual((costume['owned'], costume['total'], costume['is_complete']), (3, 3, True))
        detail = build_member_comp_data(100, 'hinatazaka', 'メンバーA')
        self.assertEqual(next(c for c in detail if c['costume'] == MAPPED_COSTUME), costume)
        self.assertEqual(build_stats_data(100, 'nogizaka')['type_stats'], {'座り': 7})
        self.assertEqual(self.client.get('/stats/hinatazaka').status_code, 200)

    def test_collection_ajax_and_add_preserve_original_numeric_values(self):
        response = self.client.get('/index/hinatazaka')
        self.assertEqual(response.status_code, 200)
        card = next(c for c in CardParser(response.get_data(as_text=True)).cards
                    if c['costume'] == MAPPED_COSTUME)
        self.assertEqual({d['type']: d['type_order'] for d in card['details']},
                         {'01': 1, '02': 2, '99': 999})
        for detail in card['details']:
            refreshed = self.client.get(f'/get_user_photo_detail/hinatazaka/{detail["id"]}').json['detail']
            self.assertEqual((refreshed['type'], refreshed['type_order']),
                             (detail['type'], detail['type_order']))
        query = urlencode(dict(group='hinatazaka', member='メンバーA', costume=MAPPED_COSTUME))
        self.assertEqual(self.client.get('/get_types?' + query).json['types'],
                         ['01', '03', 'ヨリ', '02', '99'])
        response = self.client.post('/add/hinatazaka', data=dict(
            member='メンバーA', costume=MAPPED_COSTUME, photo_type='01', quantity=1))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserPhoto.query.filter_by(user_id=100, photo_id=2001).one().quantity, 3)
        self.assertEqual(db.session.get(PhotoType, 10).name, '01')

    def test_missing_page_uses_db_priority(self):
        db.session.add(CostumeTypeNormalization(
            costume_id=10, photo_type_id=12, normalized_type='座り'))
        db.session.commit()
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            self.assertEqual(self.client.get('/missing/hinatazaka').status_code, 200)
        rows = contexts[-1]['grouped_missing']['メンバーA']
        self.assertIn({'costume': MAPPED_COSTUME, 'type': '座り'}, rows)

    def test_request_cache_batches_queries_and_refreshes_next_request(self):
        selects = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if 'FROM costume_type_normalizations' in statement:
                selects.append(statement)
        event.listen(db.engine, 'before_cursor_execute', capture)
        try:
            with self.app.test_request_context():
                resolver = get_type_resolver(1)
                self.assertIs(get_type_resolver(1), resolver)
                for _ in range(10):
                    self.assertEqual(resolver.resolve(10, 10, MAPPED_COSTUME, '01'), 'ヨリ')
            self.assertEqual(len(selects), 1)
            row = CostumeTypeNormalization.query.filter_by(costume_id=10, photo_type_id=10).one()
            row.normalized_type = 'ヒキ'
            db.session.commit()
            with self.app.test_request_context():
                self.assertEqual(get_type_resolver(1).resolve(10, 10, MAPPED_COSTUME, '01'), 'ヒキ')
        finally:
            event.remove(db.engine, 'before_cursor_execute', capture)


if __name__ == '__main__':
    unittest.main()
