import unittest
from continuity.engine import Job, Rejected, digest


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.job = Job(clock=lambda: self.now)

    def frozen(self):
        self.job.start()
        self.job.fail()

    def test_clean_completion_and_receipt(self):
        self.frozen()
        self.job.evaluate('clean')
        self.job.resume()
        self.assertEqual(self.job.spent, 100_000)
        self.assertEqual(len({r['record_id'] for r in self.job.rows}), 30)
        self.assertIsNone(self.job.agent)
        for index, event in enumerate(self.job.events):
            payload = {k: v for k, v in event.items() if k != 'hash'}
            self.assertEqual(event['hash'], digest(payload))
            self.assertEqual(event['previous_hash'], self.job.events[index-1]['hash'] if index else None)

    def test_old_worker_cannot_commit_after_freeze(self):
        self.frozen()
        with self.assertRaises(Rejected):
            self.job.commit_batch('primary.local', 0, 0, 17, 60_000)
        self.assertEqual(self.job.spent, 60_000)

    def test_no_repeated_batch_or_resume(self):
        self.job.start()
        with self.assertRaises(Rejected):
            self.job.commit_batch('primary.local', 0, 0, 17, 60_000)
        self.job.fail()
        self.job.evaluate('clean')
        self.job.resume()
        with self.assertRaises(Rejected):
            self.job.resume()
        self.assertEqual(self.job.spent, 100_000)

    def test_hard_denial_and_unavailable_cannot_be_approved(self):
        for scenario in ('blocked', 'unavailable'):
            self.setUp()
            self.frozen()
            self.job.evaluate(scenario)
            with self.assertRaises(Rejected):
                self.job.decide(True, None)
            with self.assertRaises(Rejected):
                self.job.resume()
            self.assertEqual(self.job.spent, 60_000)
            self.assertIsNone(self.job.agent)

    def test_cancel_is_terminal(self):
        self.frozen()
        self.job.evaluate('changed_address')
        token = digest(self.job.approval)
        self.job.decide(False, token)
        with self.assertRaises(Rejected):
            self.job.decide(True, token)
        self.assertEqual(self.job.state, 'cancelled')
        self.assertIsNone(self.job.agent)

    def test_approval_bound_and_single_use(self):
        self.frozen()
        self.job.evaluate('changed_address')
        with self.assertRaises(Rejected):
            self.job.decide(True, 'wrong-action')
        with self.assertRaises(Rejected):
            self.job.resume()
        token = digest(self.job.approval)
        self.job.decide(True, token, {'binding': token, 'expires_at': self.now + 120})
        with self.assertRaises(Rejected):
            self.job.decide(True, token)
        self.job.resume()
        self.assertEqual(self.job.state, 'completed')

    def test_approval_expires(self):
        self.frozen()
        self.job.evaluate('changed_address')
        self.now += 120
        self.job.decide(True, digest(self.job.approval))
        self.assertEqual(self.job.state, 'expired')
        self.assertIsNone(self.job.agent)

    def test_job_expiry_blocks_handoff_and_spending(self):
        self.frozen()
        self.now += 600
        self.job.evaluate('clean')
        self.assertEqual(self.job.state, 'expired')
        self.setUp()
        self.frozen()
        self.job.evaluate('clean')
        self.now += 600
        with self.assertRaises(Rejected):
            self.job.resume()
        self.assertEqual(self.job.spent, 60_000)

    def test_budget_and_batch_scope(self):
        self.frozen()
        self.job.evaluate('clean')
        with self.assertRaises(Rejected):
            self.job.commit_batch('backup.local', 1, 17, 30, 50_000)
        self.job.budget = 90_000
        with self.assertRaises(Rejected):
            self.job.resume()
        self.assertEqual(len(self.job.rows), 17)

    def test_checkpoint_and_snapshot_are_copies(self):
        self.frozen()
        snapshot = self.job.snapshot()
        snapshot['capsule']['completed'].clear()
        snapshot['events'].clear()
        self.assertEqual(len(self.job.capsule['completed']), 17)
        self.assertTrue(self.job.events)


if __name__ == '__main__':
    unittest.main()
