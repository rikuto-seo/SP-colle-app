from flask import Blueprint, request, jsonify, url_for
from flask_login import login_required, current_user
import stripe
import os
from models import db, User
from extensions import csrf

billing_bp = Blueprint('billing', __name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PRICE_IDS = {
    "lite": "price_1TGViaLpYTfv8wQ04V8pqM8s",
    "standard": "price_1TGVirLpYTfv8wQ0AMd4gfUO",
    "premium": "price_1TFEHqLpYTfv8wQ09O2XSR4O"
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
                    "groups": ",".join(current_user.get_selected_groups())
                }
            },

            metadata={
                "user_id": str(current_user.id),
                "target_plan": plan
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
    if current_user.stripe_subscription_id:
        stripe.Subscription.modify(
            current_user.stripe_subscription_id,
            cancel_at_period_end=True
        )

    # ❌ 消す
    # current_user.plan_type = "free"
    # current_user.stripe_subscription_id = None

    db.session.commit()
    return {"status": "ok"}

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

    current_user.selected_groups = ",".join(groups)
    db.session.commit()

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

    print("🔥 EVENT:", event["type"])

    def find_user(session_obj=None, customer_id=None):
        user = None

        if session_obj:
            metadata = session_obj.get("metadata", {})
            user_id = metadata.get("user_id")

            if user_id:
                user = db.session.get(User, int(user_id))
                if user:
                    print("✅ USER FOUND (metadata):", user.id)
                    return user

        if customer_id:
            user = User.query.filter_by(
                stripe_customer_id=customer_id
            ).first()

            if user:
                print("✅ USER FOUND (customer):", user.id)
                return user

        print("❌ USER NOT FOUND")
        return None

    if event["type"] == "checkout.session.completed":
        try:
            session_obj = event["data"]["object"]
            customer_id = session_obj.get("customer")

            user = find_user(session_obj, customer_id)

            if not user:
                return "user not found", 200

            line_items = stripe.checkout.Session.list_line_items(
                session_obj["id"]
            )

            for item in line_items["data"]:
                price_id = item["price"]["id"]

                if price_id == PRICE_IDS["lite"]:
                    user.plan_type = "lite"
                elif price_id == PRICE_IDS["standard"]:
                    user.plan_type = "standard"
                elif price_id == PRICE_IDS["premium"]:
                    user.plan_type = "premium"

            groups_str = session_obj.get("metadata", {}).get("groups")

            if groups_str:
                user.selected_groups = groups_str

            subscription_id = session_obj.get("subscription")

            if subscription_id:
                user.stripe_subscription_id = subscription_id

            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            print("❌ DB ERROR:", e)
            return "db error", 200

    elif event["type"] == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")

        user = find_user(customer_id=customer_id)

        if user:
            print("💰 RENEWAL SUCCESS:", user.id)

            sub_id = invoice.get("subscription")

            if sub_id:
                sub = stripe.Subscription.retrieve(sub_id)

                price_id = sub["items"]["data"][0]["price"]["id"]

                if price_id == PRICE_IDS["lite"]:
                    user.plan_type = "lite"
                elif price_id == PRICE_IDS["standard"]:
                    user.plan_type = "standard"
                elif price_id == PRICE_IDS["premium"]:
                    user.plan_type = "premium"

                db.session.commit()
                print("✅ PLAN UPDATED AFTER PAYMENT:", user.plan_type)

    elif event["type"] == "customer.subscription.deleted":
        try:
            subscription = event["data"]["object"]
            customer_id = subscription.get("customer")

            print("🔥 SUBSCRIPTION DELETED:", subscription.get("id"))

            user = find_user(customer_id=customer_id)

            if user:
                user.plan_type = "free"
                user.stripe_subscription_id = None
                db.session.commit()
                print("🔻 PLAN DOWNGRADED: free")

        except Exception as e:
            db.session.rollback()
            print("❌ DB ERROR:", e)
            return "db error", 200

    else:
        print("ℹ️ UNHANDLED EVENT:", event["type"])

    return "ok", 200