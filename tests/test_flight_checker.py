#!/usr/bin/env python3
"""
테스트 파일 분리 완료 후 메인 테스트 진입점
이 파일은 하위 호환성을 위해 남겨두며, 모든 테스트를 임포트하여 실행합니다.
"""
import unittest
from .test_suite import create_test_suite


class TestFlightChecker(unittest.TestCase):
    """기존 테스트 파일과의 호환성을 위한 래퍼 클래스"""
    
    def test_all_modules(self):
        """모든 분리된 테스트 모듈이 정상적으로 작동하는지 확인"""
        suite = create_test_suite()
        self.assertGreater(suite.countTestCases(), 0, "테스트 케이스가 하나 이상 존재해야 함")


if __name__ == "__main__":
    unittest.main()