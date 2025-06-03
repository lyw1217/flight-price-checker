#!/usr/bin/env python3
"""
통합된 테스트 스위트
모든 개별 테스트 모듈을 임포트하고 실행합니다.
"""
import unittest
import sys
from pathlib import Path

# 테스트 모듈들 임포트
from .test_validation import TestValidation
from .test_parsing import TestParsing
from .test_utils import TestUtils
from .test_time_restrictions import TestTimeRestrictions
from .test_message_manager import TestMessageManager
from .test_config_manager import TestConfigManager


def create_test_suite():
    """모든 테스트를 포함하는 테스트 스위트 생성"""
    suite = unittest.TestSuite()
    
    # 각 테스트 클래스의 모든 테스트 메서드 추가
    test_classes = [
        TestValidation,
        TestParsing,
        TestUtils,
        TestTimeRestrictions,
        TestMessageManager,
        TestConfigManager
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    return suite


def main():
    """메인 테스트 실행 함수"""
    # 테스트 스위트 생성
    suite = create_test_suite()
    
    # 테스트 실행
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 결과 반환
    return result.wasSuccessful()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
