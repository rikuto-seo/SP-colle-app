from app import app   # あなたのFlaskインスタンス
import stripe
import os
from models import db, User
from datetime import datetime, timezone
import pytz

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
jst = pytz.timezone("Asia/Tokyo")

with app.app_context():

    users = User.query.filter(User.stripe_subscription_id.isnot(None)).all()

    for user in users:
        try:
            sub = stripe.Subscription.retrieve(user.stripe_subscription_id)

            user.subscription_status = sub.get("status")
            user.cancel_at_period_end = sub.get("cancel_at_period_end", False)

            if sub.get("current_period_end"):
                user.current_period_end = datetime.fromtimestamp(
                    sub["current_period_end"], tz=timezone.utc
                ).astimezone(jst)

            print("UPDATED:", user.id)

        except Exception as e:
            print("ERROR:", user.id, e)

    db.session.commit()