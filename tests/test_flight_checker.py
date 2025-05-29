#!/usr/bin/env python3
import unittest
from datetime import datetime, timedelta, time
import sys
from pathlib import Path

# 프로젝트 루트 디렉토리를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from flight_checker import (
    validate_url,
    parse_flight_info,
    check_time_restrictions,
    valid_date,
    valid_airport
)

class TestFlightChecker(unittest.TestCase):
    def test_validate_url(self):
        """URL 검증 테스트"""
        valid_urls = [
            "http://localhost:4444/wd/hub",
            "https://example.com/path",
            "http://127.0.0.1:8080"
        ]
        invalid_urls = [
            "ftp://example.com",
            "not_a_url",
            "http:/missing-slash",
            ""
        ]
        
        for url in valid_urls:
            is_valid, _ = validate_url(url)
            self.assertTrue(is_valid, f"URL should be valid: {url}")
            
        for url in invalid_urls:
            is_valid, _ = validate_url(url)
            self.assertFalse(is_valid, f"URL should be invalid: {url}")
            
    def test_parse_flight_info(self):
        """항공편 정보 파싱 테스트"""
        # 유효한 항공편 정보
        valid_text = """
        07:00ICN 09:00FUK
        15:00FUK 17:00ICN
        왕복 374,524원
        """
        result = parse_flight_info(valid_text, "ICN", "FUK")
        self.assertIsNotNone(result)
        dep_time, dep_arr, ret_time, ret_arr, price = result
        self.assertEqual(dep_time, "07:00")
        self.assertEqual(ret_time, "15:00")
        self.assertEqual(price, 374524)
        
        # 잘못된 형식
        invalid_text = "Invalid flight info"
        result = parse_flight_info(invalid_text, "ICN", "FUK")
        self.assertIsNone(result)
        
    def test_check_time_restrictions(self):
        """시간 제한 체크 테스트"""
        # 시간대 설정 테스트
        period_config = {
            "time_type": "time_period",
            "outbound_periods": ["오전1"],  # 06:00-09:00
            "inbound_periods": ["오후1"]    # 12:00-15:00
        }
        
        # 유효한 시간
        self.assertTrue(
            check_time_restrictions("07:00", "13:00", period_config),
            "Valid time period should be accepted"
        )
        
        # 유효하지 않은 시간
        self.assertFalse(
            check_time_restrictions("10:00", "13:00", period_config),
            "Invalid outbound time should be rejected"
        )
        self.assertFalse(
            check_time_restrictions("07:00", "16:00", period_config),
            "Invalid inbound time should be rejected"
        )
        
        # 시각 설정 테스트
        exact_config = {
            "time_type": "exact",
            "outbound_exact_hour": 9,
            "inbound_exact_hour": 15
        }
        
        # 유효한 시간
        self.assertTrue(
            check_time_restrictions("08:00", "16:00", exact_config),
            "Valid exact time should be accepted"
        )
        
        # 유효하지 않은 시간
        self.assertFalse(
            check_time_restrictions("10:00", "16:00", exact_config),
            "Invalid outbound time should be rejected"
        )
        self.assertFalse(
            check_time_restrictions("08:00", "14:00", exact_config),
            "Invalid inbound time should be rejected"
        )
        
    def test_valid_date(self):
        """날짜 유효성 검사 테스트"""
        today = datetime.now()
        future_date = (today + timedelta(days=30)).strftime("%Y%m%d")
        past_date = (today - timedelta(days=1)).strftime("%Y%m%d")
        far_future = (today + timedelta(days=400)).strftime("%Y%m%d")
        
        # 유효한 날짜
        is_valid, _ = valid_date(future_date)
        self.assertTrue(is_valid, "Future date should be valid")
        
        # 과거 날짜
        is_valid, _ = valid_date(past_date)
        self.assertFalse(is_valid, "Past date should be invalid")
        
        # 1년 이상 미래
        is_valid, _ = valid_date(far_future)
        self.assertFalse(is_valid, "Far future date should be invalid")
        
        # 잘못된 형식
        is_valid, _ = valid_date("invalid")
        self.assertFalse(is_valid, "Invalid format should be rejected")
        
    def test_valid_airport(self):
        """공항 코드 유효성 검사 테스트"""
        # 유효한 공항 코드
        is_valid, _ = valid_airport("ICN")
        self.assertTrue(is_valid, "Valid airport code should be accepted")
        
        # 잘못된 형식
        is_valid, _ = valid_airport("INVALID")
        self.assertFalse(is_valid, "Invalid airport code should be rejected")
        is_valid, _ = valid_airport("12")
        self.assertFalse(is_valid, "Invalid airport code should be rejected")

if __name__ == "__main__":
    unittest.main() 