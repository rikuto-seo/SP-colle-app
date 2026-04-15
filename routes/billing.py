from flask import Blueprint, request, jsonify, url_for
from flask_login import login_required, current_user
import stripe
import os
from models import db, User
from extensions import csrf

billing_bp = Blueprint('billing', __name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PRICE_IDS = {
    "lite": "price_1TLO7KPvnGX55ydCcJxWWRlb",
    "standard": "price_1TLO81PvnGX55ydCr2hBb63p",
    "premium": "price_1TLO8dPvnGX55ydClrsqTyea"
}

@billing_bp.route("/api/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():

    data = request.get_json()

    if not data:
        return jsonify({"error": "invalid request"}), 400

    plan = data.get("plan")

    if plan not in PRICE_IDS:
        return jsonify({"error": "invalid plan"}), 400

    try:
        if current_user.stripe_customer_id:
            customer_id = current_user.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                email=current_user.email
            )
            customer_id = customer.id
            current_user.stripe_customer_id = customer_id
            db.session.commit()

        domain = request.host_url.rstrip("/")

        groups = current_user.get_selected_groups() or []
        groups_str = ",".join(map(str, groups)) if groups else ""

        session = stripe.checkout.Session.create(
            customer=customer_id,
            line_items=[{
                "price": PRICE_IDS[plan],
                "quantity": 1,
            }],
            mode="subscription",

            subscription_data={
                "metadata": {
                    "user_id": str(current_user.id),
                    "target_plan": plan,
                    "groups": groups_str
                }
            },

            metadata={
                "user_id": str(current_user.id),
                "target_plan": plan,
                "groups": groups_str
            },

            success_url=f"{domain}/payment-success?plan={plan}",
            cancel_url=f"{domain}/upgrade",
        )

        return jsonify({"url": session.url})

    except Exception as e:
        print("❌ STRIPE ERROR:", e)
        return jsonify({"error": str(e)}), 500

@billing_bp.route("/api/check-plan")
@login_required
def check_plan():
    db.session.refresh(current_user)

    expected_plan = request.args.get("plan")

    return {
        "ready": current_user.plan_type == expected_plan
    }

@billing_bp.route("/api/downgrade", methods=["POST"])
@login_required
def downgrade():
    try:
        if current_user.stripe_subscription_id:

            sub = stripe.Subscription.modify(
                current_user.stripe_subscription_id,
                cancel_at_period_end=True
            )

            print("🔻 CANCEL SCHEDULED:", sub.get("current_period_end"))

        db.session.commit()
        return {"status": "ok"}

    except Exception as e:
        print("❌ DOWNGRADE ERROR:", e)
        return {"error": "failed"}, 500
    
@billing_bp.route("/api/save-groups", methods=["POST"])
@login_required
def save_groups():

    data = request.get_json()
    groups = data.get("groups", [])

    PLAN_LIMITS = {
        "free": 1,
        "lite": 1,
        "standard": 2,
        "premium": 3
    }

    plan = current_user.plan_type or "free"

    if len(groups) != PLAN_LIMITS[plan]:
        return {"error": "invalid group count"}, 400

    current_user.set_selected_groups(groups)

    if groups:
        current_user.primary_group = groups[0]

    db.session.commit()

    return {"status": "ok"}

@billing_bp.route("/api/resume-subscription", methods=["POST"])
@login_required
def resume_subscription():

    if current_user.stripe_subscription_id:
        stripe.Subscription.modify(
            current_user.stripe_subscription_id,
            cancel_at_period_end=False
        )

    return {"status": "ok"}

@csrf.exempt
@billing_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except Exception as e:
        print("❌ Webhook signature error:", e)
        return "invalid signature", 400

    event_type = event["type"]
    data = event["data"]["object"]

    print("🔥 EVENT:", event_type)

    from datetime import datetime, timezone
    import pytz

    jst = pytz.timezone("Asia/Tokyo")

    def to_jst_datetime(ts):
        if not ts:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(jst)

    def find_user(session_obj=None, customer_id=None, subscription_id=None):

        if session_obj:
            metadata = session_obj.get("metadata", {})
            user_id = metadata.get("user_id")
            if user_id:
                user = db.session.get(User, int(user_id))
                if user:
                    return user

        if subscription_id:
            user = User.query.filter_by(
                stripe_subscription_id=subscription_id
            ).first()
            if user:
                return user

        if customer_id:
            return User.query.filter_by(
                stripe_customer_id=customer_id
            ).first()

        return None

    try:

        # =========================
        # checkout.session.completed
        # =========================
        if event_type == "checkout.session.completed":

            user = find_user(
                session_obj=data,
                customer_id=data.get("customer")
            )

            print("👤 USER (checkout):", user)

            if user:
                plan = data.get("metadata", {}).get("target_plan")
                if plan in ["lite", "standard", "premium"]:
                    user.plan_type = plan

                groups_str = data.get("metadata", {}).get("groups")
                if groups_str:
                    user.selected_groups = groups_str

                subscription_id = data.get("subscription")
                if subscription_id:
                    user.stripe_subscription_id = subscription_id

        # =========================
        # subscription created / updated
        # =========================
        elif event_type in [
            "customer.subscription.created",
            "customer.subscription.updated"
        ]:

            sub = data

            user = find_user(
                customer_id=sub.get("customer"),
                subscription_id=sub.get("id")
            )

            if user:
                user.subscription_status = sub.get("status")
                user.cancel_at_period_end = sub.get("cancel_at_period_end", False)

                # ❌ ここで current_period_end は触らない
                # （ズレの原因になる）

        # =========================
        # 💥 唯一の正解イベント
        # =========================
        elif event_type == "invoice.payment_succeeded":

            invoice = data

            user = find_user(
                customer_id=invoice.get("customer"),
                subscription_id=invoice.get("subscription")
            )

            print("👤 USER (invoice):", user)

            if user:
                user.subscription_status = "active"

                try:
                    period_end = invoice.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")

                    if period_end:
                        user.current_period_end = to_jst_datetime(period_end)

                    # 👇 ここは invoice には無いので触らない or 既存維持
                    # user.cancel_at_period_end はここで更新しない

                    print("✅ FINAL current_period_end:", user.current_period_end)

                except Exception as e:
                    print("❌ INVOICE PARSE ERROR:", e)
                    
        # =========================
        # subscription deleted
        # =========================
        elif event_type == "customer.subscription.deleted":

            sub = data

            user = find_user(
                customer_id=sub.get("customer"),
                subscription_id=sub.get("id")
            )

            if user:
                user.plan_type = "free"
                user.stripe_subscription_id = None
                user.subscription_status = "canceled"
                user.cancel_at_period_end = False
                user.current_period_end = None

        else:
            print("ℹ️ UNHANDLED EVENT:", event_type)

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print("❌ WEBHOOK ERROR:", e)
        return "error", 500

    return "ok", 200