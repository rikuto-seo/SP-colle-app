"""DB-aware normalization against memory-only SQLite, without production services."""
import unittest
import sys
import os
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SECRET_KEY', 'normalization-isolated-test-only')

from flask import g, template_rendered
from sqlalchemy import event, text

from extensions import db
from models import Costume, CostumeTypeNormalization, Photo, PhotoType, UserPhoto, WantShare
from routes.share import share_bp
from routes.stats import stats_bp
from services.stats_service import build_stats_data, build_member_comp_data
from services.type_normalizer import get_type_resolver
from test_photo_type_order import CardParser, MAPPED_COSTUME
from test_trade_marketplace import make_app, seed


class TypeNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.app.register_blueprint(stats_bp)
        self.app.register_blueprint(share_bp)
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

    def test_stats_quantities_and_completion_preserve_photo_identity(self):
        data = build_stats_data(100, 'hinatazaka')
        self.assertEqual(data['type_stats'], {'ヨリ': 4, 'チュウ': 14, 'ヒキ': 0, '座り': 0})
        self.assertEqual(data['unclassified_quantity'], 5)
        self.assertEqual(sum(data['type_stats'].values()) + data['unclassified_quantity'],
                         sum(data['member_stats'].values()))
        costume = next(c for c in data['comp_stats']['メンバーA'] if c['costume'] == MAPPED_COSTUME)
        # 01, 03 and canonical ヨリ are independent Photos even with one classification.
        self.assertEqual((costume['owned'], costume['total'], costume['is_complete']), (3, 5, False))
        detail = build_member_comp_data(100, 'hinatazaka', 'メンバーA')
        self.assertEqual(next(c for c in detail if c['costume'] == MAPPED_COSTUME), costume)
        self.assertEqual(build_stats_data(100, 'nogizaka')['type_stats'],
                         {'ヨリ': 0, 'チュウ': 0, 'ヒキ': 0, '座り': 7})
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
        row = next(row for row in rows if row['photo_id'] == 2003)
        self.assertEqual((row['costume_id'], row['type'], row['normalized_type']), (10, '03', '座り'))

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

    def render_context(self, path):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response, contexts[-1]

    def assert_collection_matches_stats(self):
        response = self.client.get('/index/hinatazaka?per_page=100')
        self.assertEqual(response.status_code, 200)
        cards = CardParser(response.get_data(as_text=True)).cards
        stats = build_stats_data(100, 'hinatazaka')
        expected = {(member, item['costume_id']): item
                    for member, items in stats['comp_stats'].items() for item in items}
        for card in cards:
            item = expected[(card['member'], card['costume_id'])]
            self.assertEqual(tuple(card[k] for k in ('owned', 'total', 'is_complete')),
                             tuple(item[k] for k in ('owned', 'total', 'is_complete')))
        self.assertEqual(sum(card['is_complete'] for card in cards),
                         sum(row['complete_count'] for row in stats['comp_ranking']))
        return stats

    def test_partial_same_classification_is_incomplete_in_every_view(self):
        data = self.assert_collection_matches_stats()
        response = self.client.get('/stats/member/hinatazaka/メンバーA')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, data['comp_stats']['メンバーA'])
        progress = next(row for row in data['progress_list'] if row['costume_id'] == 10)
        self.assertEqual((progress['owned'], progress['total'], progress['rate']), (3, 5, 60))

    def test_missing_each_photo_then_complete_only_after_every_photo_is_owned(self):
        _, context = self.render_context('/missing/hinatazaka')
        rows = [row for row in context['grouped_missing']['メンバーA'] if row['costume_id'] == 10]
        self.assertEqual({(row['photo_id'], row['type']) for row in rows}, {(2003, '03'), (2007, 'ヨリ')})
        self.assertEqual({row['normalized_type'] for row in rows}, {'ヨリ'})
        db.session.add(UserPhoto(user_id=100, photo_id=2003, quantity=1))
        db.session.commit()
        data = self.assert_collection_matches_stats()
        item = next(row for row in data['comp_stats']['メンバーA'] if row['costume_id'] == 10)
        self.assertEqual((item['owned'], item['total'], item['is_complete']), (4, 5, False))
        db.session.add(UserPhoto(user_id=100, photo_id=2007, quantity=1))
        db.session.commit()
        data = self.assert_collection_matches_stats()
        item = next(row for row in data['comp_stats']['メンバーA'] if row['costume_id'] == 10)
        self.assertEqual((item['owned'], item['total'], item['is_complete']), (5, 5, True))
        self.assertEqual(next(row['rate'] for row in data['progress_list'] if row['costume_id'] == 10), 100)

    def test_zero_quantity_is_missing_and_cannot_contribute_to_completion(self):
        UserPhoto.query.filter_by(user_id=100, photo_id=2001).one().quantity = 0
        db.session.add(UserPhoto(user_id=100, photo_id=2003, quantity=0))
        db.session.commit()
        data = self.assert_collection_matches_stats()
        item = next(row for row in data['comp_stats']['メンバーA'] if row['costume_id'] == 10)
        self.assertEqual((item['owned'], item['total'], item['is_complete']), (2, 5, False))
        response, context = self.render_context('/missing/hinatazaka')
        missing_ids = {row['photo_id'] for rows in context['grouped_missing'].values() for row in rows}
        self.assertTrue({2001, 2003, 2007} <= missing_ids)
        self.assertIn('data-photo-id="2001"', response.get_data(as_text=True))
        self.assertIn('写真ID: 2003', response.get_data(as_text=True))
        self.assertEqual(sum(data['member_stats'].values()), 21)

    def test_duplicate_quantities_and_ajax_refresh_do_not_change_completion(self):
        before = build_stats_data(100, 'hinatazaka')
        original = [(p.id, p.member_id, p.costume_id, p.type_id) for p in Photo.query.order_by(Photo.id)]
        names = [(t.id, t.name) for t in PhotoType.query.order_by(PhotoType.id)]
        owned = UserPhoto.query.filter_by(user_id=100, photo_id=2001).one()
        response = self.client.post(f'/update_user_photo/hinatazaka/{owned.id}',
                                   data={'quantity': '100'}, headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        refreshed = self.client.get(f'/get_user_photo_detail/hinatazaka/{owned.id}').json['detail']
        self.assertEqual((refreshed['type'], refreshed['type_order'], refreshed['quantity']), ('01', 1, 100))
        after = self.assert_collection_matches_stats()
        for key in ('comp_stats', 'comp_ranking', 'progress_list'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(sum(after['member_stats'].values()), sum(before['member_stats'].values()) + 98)
        self.assertTrue(all(0 <= row['rate'] <= 100 for row in after['progress_list']))
        self.assertEqual(original, [(p.id, p.member_id, p.costume_id, p.type_id) for p in Photo.query.order_by(Photo.id)])
        self.assertEqual(names, [(t.id, t.name) for t in PhotoType.query.order_by(PhotoType.id)])

    def test_unclassified_numeric_and_nonnumeric_quantities_are_visible_and_reconcile(self):
        db.session.add(PhotoType(id=14, name='特殊'))
        db.session.flush()
        db.session.add(Photo(id=2014, member_id=1, costume_id=10, type_id=14))
        db.session.flush()
        db.session.add(UserPhoto(user_id=100, photo_id=2014, quantity=4))
        db.session.commit()
        response, context = self.render_context('/stats/hinatazaka')
        self.assertEqual(context['type_stats'], [('ヨリ', 4), ('チュウ', 14), ('ヒキ', 0), ('座り', 0)])
        self.assertEqual(context['unclassified_quantity'], 9)
        self.assertEqual({(r['costume_id'], r['type'], r['quantity']) for r in context['unclassified_stats']},
                         {(10, '99', 5), (10, '特殊', 4)})
        self.assertEqual(sum(qty for _, qty in context['type_stats']) + context['unclassified_quantity'],
                         context['stats_owned'])
        html = response.get_data(as_text=True)
        self.assertIn('data-unclassified-stats', html)
        self.assertIn('9枚', html)
        self.assertIn('99', html)
        self.assertIn('特殊', html)

    def test_same_named_costumes_use_ids_for_completion_progress_and_unclassified(self):
        db.session.add(Costume(id=12, name=MAPPED_COSTUME, group_id=1))
        db.session.flush()
        db.session.add_all([Photo(id=2012, member_id=1, costume_id=12, type_id=13),
                            Photo(id=2013, member_id=1, costume_id=12, type_id=10)])
        db.session.flush()
        db.session.add(UserPhoto(user_id=100, photo_id=2012, quantity=8))
        db.session.commit()
        data = self.assert_collection_matches_stats()
        items = {row['costume_id']: row for row in data['comp_stats']['メンバーA']}
        self.assertEqual((items[10]['owned'], items[10]['total']), (3, 5))
        self.assertEqual((items[12]['owned'], items[12]['total']), (1, 2))
        self.assertNotEqual(items[10]['costume_label'], items[12]['costume_label'])
        progress = {row['costume_id']: row for row in data['progress_list']}
        self.assertEqual((progress[10]['rate'], progress[12]['rate']), (60, 50))
        self.assertEqual({(row['costume_id'], row['quantity']) for row in data['unclassified_stats']},
                         {(10, 5), (12, 8)})
        detail = build_member_comp_data(100, 'hinatazaka', 'メンバーA')
        self.assertEqual({row['costume_id']: row for row in detail}, items)

    def test_empty_group_has_four_zero_classifications_and_no_completion(self):
        UserPhoto.query.filter_by(user_id=100).delete()
        db.session.commit()
        data = self.assert_collection_matches_stats()
        self.assertEqual(list(data['type_stats'].values()), [0, 0, 0, 0])
        self.assertEqual(data['unclassified_quantity'], 0)
        self.assertEqual(data['unclassified_stats'], [])
        self.assertTrue(all(row['owned'] == 0 and row['rate'] == 0 for row in data['progress_list']))

    def test_shared_pages_preserve_photo_identity_quantity_and_privacy(self):
        db.session.add(UserPhoto(user_id=100, photo_id=2003, quantity=0))
        share = WantShare(user_id=100, group_key='hinatazaka', public_uuid='stats-fixture', is_public=True)
        db.session.add(share)
        db.session.commit()
        with self.client.session_transaction() as session:
            session.clear()
        g.pop('_login_user', None)
        response, context = self.render_context('/shared/hinatazaka/stats-fixture')
        private = build_stats_data(100, 'hinatazaka')
        self.assertEqual(context['type_stats'], list(private['type_stats'].items()))
        self.assertEqual(context['unclassified_quantity'], 5)
        self.assertEqual(context['stats']['quantity'], 23)
        self.assertEqual((context['stats']['owned_count'], context['stats']['total_count']), (5, 9))
        self.assertLessEqual(context['stats']['percent'], 100)
        self.assertNotIn(2003, context['owned_photo_ids'])
        self.assertEqual({row['photo_type'] for row in context['all_photos'] if row['costume_id'] == 10},
                         {'01', '02', '03', '99', 'ヨリ'})
        self.assertIn('総所持枚数: 23枚', response.get_data(as_text=True))
        _, collection = self.render_context('/share/hinatazaka/stats-fixture')
        self.assertEqual({row['type'] for row in collection['photocards']}, {'01', '02', '99', 'ヨリ'})
        self.assertTrue(all(row['quantity'] > 0 for row in collection['photocards']))
        self.assertEqual(sum(row['quantity'] for row in collection['photocards']), 23)
        self.assertEqual(self.client.get('/shared/nogizaka/stats-fixture').status_code, 404)
        share.is_public = False
        db.session.commit()
        for path in ('/shared/hinatazaka/stats-fixture', '/share/hinatazaka/stats-fixture'):
            response, context = self.render_context(path)
            self.assertNotIn('stats', context)
            self.assertNotIn('photocards', context)
            self.assertNotIn('all_photos', context)

    def test_no_photo_catalog_has_no_progress_or_division_by_zero(self):
        db.session.add(Costume(id=12, name='写真未登録', group_id=2))
        UserPhoto.query.filter_by(photo_id=2005).delete()
        db.session.delete(db.session.get(Photo, 2005))
        db.session.delete(db.session.get(Photo, 1004))
        db.session.commit()
        data = build_stats_data(100, 'nogizaka')
        self.assertEqual(data['progress_list'], [])
        self.assertTrue(all(row['complete_count'] == 0 for row in data['comp_ranking']))
        self.assertEqual(list(data['type_stats'].values()), [0, 0, 0, 0])

    def test_negative_legacy_quantity_is_not_owned_or_counted(self):
        # Production constraints reject negatives. Emulate a legacy invalid row
        # only in this memory-only SQLite fixture to exercise the <= 0 boundary.
        db.session.execute(text('PRAGMA ignore_check_constraints = ON'))
        try:
            UserPhoto.query.filter_by(user_id=100, photo_id=2001).one().quantity = -3
            db.session.commit()
            data = self.assert_collection_matches_stats()
            item = next(row for row in data['comp_stats']['メンバーA'] if row['costume_id'] == 10)
            self.assertEqual(item['owned'], 2)
            self.assertEqual(sum(data['member_stats'].values()), 21)
            _, context = self.render_context('/missing/hinatazaka')
            self.assertIn(2001, {r['photo_id'] for r in context['grouped_missing']['メンバーA']})
        finally:
            db.session.execute(text('PRAGMA ignore_check_constraints = OFF'))

    def test_decorated_type_is_classified_but_keeps_original_label_and_photo(self):
        name = 'ヨリ（カンフー）'
        db.session.add(PhotoType(id=14, name=name))
        db.session.flush()
        db.session.add(Photo(id=2014, member_id=1, costume_id=10, type_id=14))
        db.session.flush()
        db.session.add(UserPhoto(user_id=100, photo_id=2014, quantity=4))
        db.session.commit()
        response = self.client.post('/add/hinatazaka', data=dict(
            member='メンバーA', costume=MAPPED_COSTUME, photo_type=name, quantity=1))
        self.assertEqual(response.status_code, 302)
        data = self.assert_collection_matches_stats()
        self.assertEqual(data['type_stats']['ヨリ'], 9)
        self.assertEqual(data['unclassified_quantity'], 5)
        item = next(row for row in data['comp_stats']['メンバーA'] if row['costume_id'] == 10)
        self.assertEqual((item['owned'], item['total'], item['is_complete']), (4, 6, False))
        owned = UserPhoto.query.filter_by(user_id=100, photo_id=2014).one()
        detail = self.client.get(f'/get_user_photo_detail/hinatazaka/{owned.id}').json['detail']
        self.assertEqual((detail['type'], detail['type_order'], detail['quantity']), (name, 1, 5))
        query = urlencode(dict(group='hinatazaka', member='メンバーA', costume=MAPPED_COSTUME))
        self.assertIn(name, self.client.get('/get_types?' + query).json['types'])
        self.assertEqual(db.session.get(PhotoType, 14).name, name)


if __name__ == '__main__':
    unittest.main()
