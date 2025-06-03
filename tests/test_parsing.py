#!/usr/bin/env python3
from .test_base import BaseTestCase


class TestParsing(BaseTestCase):
    """파싱 기능 테스트"""

    def test_parse_flight_info(self):
        """항공편 정보 파싱 테스트"""
        valid_text = "07:00ICN 09:00FUK\n15:00FUK 17:00ICN\n왕복 374,524원"
        result = self.parse_flight_info(valid_text, "ICN", "FUK")
        self.assertIsNotNone(result)
        
        dep_time, dep_arr, ret_time, ret_arr, price = result
        self.assertEqual(dep_time, "07:00")
        self.assertEqual(ret_time, "15:00")
        self.assertEqual(price, 374524)
        
        invalid_text = "Invalid flight info"
        result = self.parse_flight_info(invalid_text, "ICN", "FUK")
        self.assertIsNone(result)


if __name__ == "__main__":
    import unittest
    unittest.main()
