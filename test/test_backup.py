from djevops.backup import as_cron, parse_sync_interval
from unittest import TestCase


class ParseSyncIntervalTest(TestCase):

    def test_second(self):
        self.assertEqual(1, parse_sync_interval('1s'))

    def test_minute(self):
        self.assertEqual(120, parse_sync_interval('2m'))

    def test_hour(self):
        self.assertEqual(10800, parse_sync_interval('3h'))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_sync_interval('1')
        with self.assertRaises(ValueError):
            parse_sync_interval('s1')
        with self.assertRaises(ValueError):
            parse_sync_interval('1m1')
        with self.assertRaises(ValueError):
            parse_sync_interval('1h1')

class AsCronTest(TestCase):

    def test_minutes(self):
        self.assertEqual('*/1 * * * *', as_cron(60))
        self.assertEqual('*/30 * * * *', as_cron(1800))

    def test_hour(self):
        self.assertEqual('0 */1 * * *', as_cron(3600))

    def test_hours(self):
        self.assertEqual('0 */6 * * *', as_cron(21600))

    def test_day(self):
        self.assertEqual('0 0 * * *', as_cron(86400))

    def test_sub_minute(self):
        with self.assertRaises(ValueError):
            as_cron(30)

    def test_above_a_day(self):
        with self.assertRaises(ValueError):
            as_cron(48 * 3600)

    def test_non_whole_hour(self):
        with self.assertRaises(ValueError):
            as_cron(90 * 60)
