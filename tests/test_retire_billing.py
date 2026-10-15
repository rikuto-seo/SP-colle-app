"""No network calls: verify the billing migration's ownership and dry-run guards."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.retire_legacy_subscriptions import retire_subscription


class RetireBillingTest(unittest.TestCase):
    def setUp(self):
        self.row = dict(id=100,stripe_customer_id='cus_fixture',stripe_subscription_id='sub_fixture')
        self.sub = dict(id='sub_fixture',customer='cus_fixture',status='active',metadata={'user_id':'100'},
            items={'data':[{'price':{'id':'price_1TLO7KPvnGX55ydCcJxWWRlb'}}]})
        self.api = Mock()
        self.api.Subscription.retrieve.return_value=self.sub
        self.api.Subscription.cancel.return_value={'status':'canceled'}

    def test_default_only_inspects(self):
        self.assertEqual(retire_subscription(self.row,self.api),'would_cancel')
        self.api.Subscription.cancel.assert_not_called()

    def test_apply_cancels_without_new_invoice_and_repeated_run_is_safe(self):
        self.assertEqual(retire_subscription(self.row,self.api,apply=True),'canceled')
        self.api.Subscription.cancel.assert_called_once_with('sub_fixture',invoice_now=False,prorate=False)
        self.api.Subscription.cancel.reset_mock()
        self.sub['status']='canceled'
        self.assertEqual(retire_subscription(self.row,self.api,apply=True),'already_ended')
        self.api.Subscription.cancel.assert_not_called()

    def test_unrelated_contracts_are_not_canceled(self):
        for field,value in [('customer','cus_other'),('metadata',{'user_id':'999'}),('items',{'data':[{'price':{'id':'price_other'}}]})]:
            with self.subTest(field=field):
                sub=self.sub.copy();sub[field]=value
                self.api.Subscription.retrieve.return_value=sub
                with self.assertRaises(ValueError):retire_subscription(self.row,self.api,apply=True)
                self.api.Subscription.cancel.assert_not_called()

    def test_remote_cancellation_must_be_confirmed(self):
        self.api.Subscription.cancel.return_value={'status':'active'}
        with self.assertRaises(RuntimeError):retire_subscription(self.row,self.api,apply=True)


if __name__=='__main__':unittest.main()
