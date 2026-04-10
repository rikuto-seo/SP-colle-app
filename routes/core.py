from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db

core_bp = Blueprint('core', __name__)

@core_bp.route('/group/<group_key>')
def group(group_key):
    info = {
        'nogizaka': {'name': '乃木坂46', 'color': '#800080', 'description': '清楚で可憐な乃木坂46。', 'image': 'nogizaka_banner.jpg'},
        'sakurazaka': {'name': '櫻坂46', 'color': '#FF69B4', 'description': '強さと儚さを併せ持つ櫻坂46。', 'image': 'sakurazaka_banner.jpg'},
        'hinatazaka': {'name': '日向坂46', 'color': '#87CEFA', 'description': '笑顔とハッピーオーラの日向坂46！', 'image': 'hinatazaka_banner.jpg'}
    }
    if group_key not in info:
        return 'グループが見つかりません', 404

    return render_template(
        'group.html',
        group_key=group_key,
        **info[group_key]
    )

@core_bp.route('/<group_key>/dashboard')
def dashboard(group_key):
    group_names = {
        'nogizaka': '乃木坂46',
        'sakurazaka': '櫻坂46',
        'hinatazaka': '日向坂46'
    }
    return render_template(
        'dashboard.html',
        group_key=group_key,
        group_name=group_names.get(group_key, '不明')
    )

@core_bp.route('/terms')
def terms():
    return render_template('terms.html')

@core_bp.route('/legal')
def legal():
    return render_template('legal.html')

@core_bp.route('/switch/<group_key>')
@login_required
def group_switch(group_key):

    if not current_user.can_access_group(group_key):
        flash("このグループは有料プランで利用できます", "warning")
        return redirect(url_for("user.upgrade"))

    current_user.primary_group = group_key
    db.session.commit()

    return redirect(url_for('photo.index', group_key=group_key))

@core_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')