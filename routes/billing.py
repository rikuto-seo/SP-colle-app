"""Retired billing endpoints: never create, resume, or update paid contracts."""
from flask import Blueprint, jsonify
from flask_login import login_required
from extensions import csrf

billing_bp = Blueprint('billing', __name__)


@billing_bp.route('/api/create-checkout-session', methods=['POST'])
@billing_bp.route('/api/resume-subscription', methods=['POST'])
@billing_bp.route('/api/downgrade', methods=['POST'])
@login_required
def billing_retired():
    return jsonify(error='billing_retired', message='本サービスは完全無料です。料金の支払いは不要です。'), 410


@billing_bp.route('/api/check-plan')
@login_required
def check_plan():
    return jsonify(ready=True, plan='free')


@billing_bp.route('/api/save-groups', methods=['POST'])
@login_required
def save_groups():
    # Old clients can complete setup, but cannot restrict the available groups.
    from models import GROUP_KEYS
    return jsonify(status='ok', groups=GROUP_KEYS)


@billing_bp.route('/stripe/webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    # Retired events cannot restore paid entitlements or change user preferences.
    return jsonify(error='billing_retired'), 410
