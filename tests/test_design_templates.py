"""UI regression checks that never load app.py, credentials or a database.

Run: python -m unittest discover -s tests -p 'test_design_templates.py'
The fixture renderer also supports local screenshot checks with synthetic data.
"""
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import urlencode
import unittest

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape


ROOT = Path(__file__).resolve().parents[1]
GROUPS = [NS(id=i, key=key, name=name) for i, (key, name) in enumerate([
    ('nogizaka', '乃木坂46'), ('sakurazaka', '櫻坂46'), ('hinatazaka', '日向坂46')
], 1)]


def fixture_url(endpoint, **values):
    if endpoint == 'static':
        return '/static/' + values['filename']
    return '/fixture-link/' + endpoint + ('?' + urlencode(values) if values else '')


class Field:
    def __init__(self, name):
        self.name = name
        self.label = Label(name)

    def __call__(self, **attrs):
        attrs.setdefault('id', self.name)
        attrs.setdefault('name', self.name)
        options = ' '.join(f'{escape(k.rstrip("_"))}="{escape(v)}"' for k, v in attrs.items())
        if self.name in ('member', 'costume', 'photo_type'):
            return Markup(f'<select {options}></select>')
        if self.name == 'memo':
            return Markup(f'<textarea {options}></textarea>')
        if self.name == 'submit':
            return Markup(f'<button type="submit" {options}>へらす</button>')
        kind = 'number' if self.name == 'quantity' else 'date' if self.name == 'date_acquired' else 'text'
        value = '1' if kind == 'number' else ''
        return Markup(f'<input type="{kind}" {options} value="{value}">')


class Label:
    def __init__(self, name):
        self.name = name

    def __call__(self, **attrs):
        options = ' '.join(f'{escape(k.rstrip("_"))}="{escape(v)}"' for k, v in attrs.items())
        text = {'member':'メンバー','costume':'衣装','photo_type':'種類','quantity':'枚数','date_acquired':'入手日','memo':'メモ'}.get(self.name, self.name)
        return Markup(f'<label for="{self.name}" {options}>{text}</label>')


class FixtureForm:
    def __getattr__(self, name):
        return Field(name)

    def hidden_tag(self):
        return Markup('<input type="hidden" name="csrf_token" value="fixture-csrf">')


class Pagination:
    page = 1
    pages = 3
    has_prev = False
    has_next = True
    prev_num = 0
    next_num = 2

    def iter_pages(self, **kwargs):
        return [1, 2, 3]


def fixture_context(template, *, dark=False, authenticated=True, group_key='hinatazaka', empty=False, with_image=False):
    member = NS(id=1, name='サンプルメンバー')
    costume = NS(id=1, name='2026年 春の衣装')
    photo = NS(id=1, member=member, costume=costume, photo_type=NS(name='ヨリ'))
    user = NS(
        id=2, username='コレクター', is_authenticated=authenticated, dark_mode=dark,
        email='fixture@example.invalid', show_twitter=False, show_instagram=False,
        primary_group=group_key, plan_type='free', public_uuid='fixture-user',
        twitter_id='', instagram_id='', is_public=True,
        can_access_group=lambda key: key in [group.key for group in GROUPS],
        is_premium=lambda: False, is_standard=lambda: False, is_lite=lambda: False,
        get_selected_groups=lambda: [group.key for group in GROUPS],
    )
    cards = [] if empty else [dict(
        member=name, costume=outfit, owned=owned, total=3, rate=round(owned/3*100),
        is_complete=owned == 3, has_favorite=i == 0,
        details=[dict(id=i+1, type='ヨリ', quantity=1, tradeable=0, is_favorite=i == 0, memo='', images=[])],
    ) for i, (name, outfit, owned) in enumerate([
        ('サンプルメンバーA', '2026年 春の衣装', 3),
        ('サンプルメンバーB', 'ライブ衣装（長い衣装名がある場合の表示確認）', 2),
        ('サンプルメンバーC', '夏の制服', 1),
        ('サンプルメンバーD', 'ジャケット写真衣装', 2),
        ('サンプルメンバーE', '2025年 クリスマス衣装', 1),
        ('サンプルメンバーF', '2026年 浴衣', 3),
    ])]
    wants = [] if empty else [NS(id=i, photo=photo, is_infinite=False) for i in range(1, 5)]
    ctx = dict(
        current_user=user, user=user, owner=user, group_key=group_key,
        group=next(g for g in GROUPS if g.key == group_key), group_list=GROUPS,
        group_name=next(g.name for g in GROUPS if g.key == group_key),
        group_color='', force_select_mode=False, icon_url='/static/images/default_icon.png',
        request=NS(endpoint='photo.index', full_path='/fixture'), csrf_token=lambda: 'fixture-csrf',
        url_for=fixture_url, cards=cards, wants=wants, qr_base64='',
        query='', selected_member='', selected_costume='', selected_sort='comp', favorite_only=False,
        pagination=Pagination(), args={}, current_url='/fixture', form=FixtureForm(),
        member_list=['サンプルメンバー'], costume_list=['2026年 春の衣装'],
        search_member='', search_costume='', grouped_missing={1: [NS(costume=costume.name, type='sample', photo_id=1, costume_id=1, normalized_type='sample')]},
        member_names={1: member.name}, member_options=[dict(id=1, name=member.name)],
        costume_options=[dict(id=1, name=costume.name)], selected_member_id=None,
        stats_owned=42, total_complete=6, comp_ranking=[NS(member=member.name, complete_count=6)],
        member_stats=[(member.name, 42)], member_stats_sorted=[(member.name, 42)],
        ordered_members=[dict(id=1, name=member.name)], type_stats=[('ヨリ', 12), ('チュウ', 14), ('ヒキ', 16)],
        progress_list=[], is_shared=False, stats=NS(owned_count=42, total_count=60, percent=70),
        all_photos=[], owned_photo_ids=set(), photocards=[], share_uuid='fixture-share',
        costume=costume, member=member, keyword='', costumes=[costume],
        stats_map={1: NS(member_count=3, type_count=3)},
        member_rows=[NS(member=member, types=['ヨリ', 'チュウ'])], all_types=['ヨリ', 'チュウ', 'ヒキ'],
        total_photos=3, costume_rows=[NS(costume=costume, types=['ヨリ'])],
        next_billing='', current_plan='free', cancel_at_period_end=False,
        image_storage_usage_percent=12, image_storage_limit_gb=1,
        image_storage_used_display='120 MB', image_storage_remaining_display='880 MB',
        total_owned_count=42, total_owned=42, group_totals={g.key: 14 for g in GROUPS},
        possession_total=42, possession_group_totals=[NS(name=g.name, total=14) for g in GROUPS],
        qr_codes={}, share_statuses={g.key: False for g in GROUPS},
        group_counts={g.key: 14 for g in GROUPS}, selected_groups=[g.key for g in GROUPS], qr_images={},
        selected_group=next(g for g in GROUPS if g.key == group_key),
        members=[member], photo_types=[NS(id=1, name='ヨリ')], costumes_json=[], normalized_types=['ヨリ','チュウ','ヒキ'],
        selected_costume_id=None, current_selected=[group_key], allowed=1,
        name=next(g.name for g in GROUPS if g.key == group_key),
    )
    endpoints = {'index.html':'photo.index', 'add.html':'photo.add', 'give.html':'photo.give', 'want/index.html':'want.index', 'mypage.html':'user.mypage'}
    ctx['request'].endpoint = endpoints.get(template, 'fixture')
    if with_image and cards:
        cards[0]['details'][0]['images'] = [dict(id=1, image_url='/static/images/default_icon.png', thumbnail_url='/static/images/default_icon.png')]
    if template in ('lp.html', 'public/index.html'):
        ctx['group'] = None
    if template in ('login.html', 'register.html'):
        ctx['group_key'] = ''
    if template == 'want/public_base.html':
        ctx['wants'] = [NS(want=w, is_owned=True) for w in wants]
    if template == 'force_select_group.html':
        ctx['force_select_mode'] = True
    if template == 'mypage.html':
        ctx['selected_group'] = group_key
    if empty:
        ctx['pagination'].pages = 1
    return ctx


ENV = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape(['html']))
ENV.filters['normalize_type'] = lambda value, *args: value
ENV.filters['trade_time'] = lambda value: value.strftime('%Y/%m/%d %H:%M')


def render_fixture(template, **kwargs):
    return ENV.get_template(template).render(**fixture_context(template, **kwargs))


class DesignTemplatesTest(unittest.TestCase):
    def test_all_templates_compile(self):
        for path in (ROOT / 'templates').rglob('*.html'):
            with self.subTest(template=path.name):
                ENV.get_template(path.relative_to(ROOT / 'templates').as_posix())

    def test_surfaces_render_in_both_themes(self):
        for template in ['index.html','add.html','give.html','stats.html','missing.html','want/index.html',
                         'want/add.html','want/public_base.html','mypage.html','upgrade.html',
                         'public/index.html','public/costume_list.html','public/costume_detail.html',
                         'public/member_costumes.html','lp.html','admin/photos.html','force_select_group.html',
                         'dashboard.html','group.html','select_group.html','shared_stats.html',
                         'shared_collection/shared_view.html','shared_collection/not_shared.html',
                         'edit_profile.html','change_password.html','icon_setting.html',
                         'terms.html','privacy.html','legal.html','confirm_delete_account.html','confirm_delete_final.html']:
            for dark in (False, True):
                with self.subTest(template=template, dark=dark):
                    html = render_fixture(template, dark=dark)
                    self.assertIn('css/style.css', html)
                    self.assertIn('SP Colle', html)
                    self.assertIn('id="main-content"', html)
                    self.assertNotIn('cdn.tailwindcss.com', html)
                    self.assertIn('data-bs-theme="dark"' if dark else 'data-bs-theme="light"', html)

    def test_guest_authentication_and_public_surfaces(self):
        for template in ['login.html','register.html','lp.html','public/index.html','want/public_base.html']:
            with self.subTest(template=template):
                html = render_fixture(template, authenticated=False)
                self.assertNotIn('id="sidebar"', html)
                self.assertNotIn('class="mobile-nav"', html)

    def test_search_contract_and_empty_state(self):
        html = render_fixture('index.html', empty=True)
        for field in ['searchForm','member-hidden','costume-hidden','favorite-hidden','favorite-btn','sort']:
            self.assertIn(f'id="{field}"', html)
        self.assertIn('最初の一枚を登録しましょう', html)
        self.assertNotIn('id="pageJumpForm"', html)

    def test_setup_without_navigation_and_landing_styles(self):
        html = render_fixture('force_select_group.html')
        self.assertNotIn('id="menu-button"', html)
        self.assertNotIn('class="mobile-nav"', html)
        landing = render_fixture('lp.html', authenticated=False)
        self.assertIn('class="landing-shell', landing)
        self.assertIn('css/landing.css', landing)
        self.assertIn('画面イメージ', landing)

    def test_image_preview_and_qr_share_contract(self):
        html = render_fixture('index.html', with_image=True)
        self.assertIn('data-image-url="/static/images/default_icon.png"', html)
        self.assertIn('card-image-button', html)
        ctx = fixture_context('want/index.html')
        ctx['qr_base64'] = 'fixture-qr'
        shared = ENV.get_template('want/index.html').render(**ctx)
        self.assertIn('data:image/png;base64,fixture-qr', shared)
        self.assertIn('公開中', shared)
        self.assertIn('公開停止', shared)
        self.assertIn('method="POST"', shared)
        self.assertIn('/fixture-link/want.toggle_want_share', shared)


if __name__ == '__main__':
    unittest.main()
