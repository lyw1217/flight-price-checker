#!/usr/bin/env python3
from datetime import datetime, timedelta
from .test_base import BaseTestCase


class TestValidation(BaseTestCase):
    """기본 검증 기능 테스트"""

    def test_valid_airport(self):
        """공항 코드 유효성 검사 테스트 (패치 및 reload된 AIRPORTS 사용)"""
        self.assertIsNotNone(self.AIRPORTS, "AIRPORTS should be loaded")
        self.assertIn("KOR", self.AIRPORTS, "Test KOR data should be in AIRPORTS")
        self.assertIn("ICN", self.AIRPORTS["KOR"]["airports"], "ICN should be in KOR airports")
        
        is_valid, _ = self.valid_airport("ICN")
        self.assertTrue(is_valid, "Valid airport code (ICN) should be accepted")
        
        is_valid, _ = self.valid_airport("FUK")
        self.assertTrue(is_valid, "Valid airport code (FUK) should be accepted")
        
        is_valid, _ = self.valid_airport("ZZZ")
        self.assertTrue(is_valid, "Unknown but valid format airport code (ZZZ) should be True by current logic")
        
        is_valid, _ = self.valid_airport("INVALID")
        self.assertFalse(is_valid, "Invalid airport code (INVALID) should be rejected")
        
        is_valid, _ = self.valid_airport("12")
        self.assertFalse(is_valid, "Invalid airport code (12) should be rejected")

    def test_validate_url(self):
        """URL 검증 테스트"""
        valid_urls = ["http://localhost:4444/wd/hub", "https://example.com/path", "http://127.0.0.1:8080"]
        invalid_urls = ["ftp://example.com", "not_a_url", "http:/missing-slash", ""]
        
        for url in valid_urls:
            is_valid, _ = self.validate_url(url)
            self.assertTrue(is_valid, f"URL should be valid: {url}")
            
        for url in invalid_urls:
            is_valid, _ = self.validate_url(url)
            self.assertFalse(is_valid, f"URL should be invalid: {url}")

    def test_valid_date(self):
        """날짜 유효성 검사 테스트"""
        today = datetime.now()
        future_date = (today + timedelta(days=30)).strftime("%Y%m%d")
        past_date = (today - timedelta(days=1)).strftime("%Y%m%d")
        far_future = (today + timedelta(days=400)).strftime("%Y%m%d")
        
        is_valid, _ = self.valid_date(future_date)
        self.assertTrue(is_valid)
        
        is_valid, _ = self.valid_date(past_date)
        self.assertFalse(is_valid)
        
        is_valid, _ = self.valid_date(far_future)
        self.assertFalse(is_valid)
        
        is_valid, _ = self.valid_date("invalid")
        self.assertFalse(is_valid)


if __name__ == "__main__":
    import unittest
    unittest.main()
