#!/usr/bin/env python3
from datetime import time
from .test_base import BaseTestCase


class TestUtils(BaseTestCase):
    """유틸리티 함수 테스트"""

    def test_format_time_range(self):
        """시간 설정 문자열 변환 테스트"""
        period_config = {"time_type": "time_period", "outbound_periods": ["오전1"], "inbound_periods": ["오후1"]}
        start_time, end_time = self.get_time_range(period_config, 'outbound')
        self.assertIsNone(start_time)
        self.assertIsNone(end_time)
        
        start_time, end_time = self.get_time_range(period_config, 'inbound')
        self.assertIsNone(start_time)
        self.assertIsNone(end_time)

    def test_get_time_range(self):
        """시간 범위 반환 테스트"""
        exact_config = {"time_type": "exact", "outbound_exact_hour": 10, "inbound_exact_hour": 14}
        
        start_time, end_time = self.get_time_range(exact_config, 'outbound')
        self.assertEqual(start_time, time(hour=0, minute=0))
        self.assertEqual(end_time, time(hour=10, minute=0))
        
        start_time, end_time = self.get_time_range(exact_config, 'inbound')
        self.assertEqual(start_time, time(hour=14, minute=0))
        self.assertEqual(end_time, time(hour=23, minute=59))


if __name__ == "__main__":
    import unittest
    unittest.main()
