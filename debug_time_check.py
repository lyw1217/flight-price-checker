#!/usr/bin/env python3
"""
시간 제한 조건 체크 디버깅 스크립트
"""

import sys
import os
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from selenium_manager import check_time_restrictions

def test_your_case():
    """사용자의 실제 케이스 테스트"""
    
    # 사용자 설정: 가는 편 11시 이전, 오는 편 14시 이후
    config = {
        'time_type': 'exact',
        'outbound_exact_hour': 11,  # 11시 이전
        'inbound_exact_hour': 14    # 14시 이후
    }
    
    # 실제 검색된 항공편
    dep_time = "07:15"  # 가는 편 출발시간
    ret_time = "13:45"  # 오는 편 출발시간
    
    print("=== 시간 제한 조건 체크 테스트 ===")
    print(f"설정: 가는 편 {config['outbound_exact_hour']}시 이전, 오는 편 {config['inbound_exact_hour']}시 이후")
    print(f"항공편: 가는 편 {dep_time} 출발, 오는 편 {ret_time} 출발")
    
    result = check_time_restrictions(dep_time, ret_time, config)
    
    print(f"결과: {result}")
    print()
      # 예상 결과 분석
    print("=== 분석 ===")
    outbound_limit = f"{config['outbound_exact_hour']:02d}:00"
    inbound_limit = f"{config['inbound_exact_hour']:02d}:00"
    
    print(f"가는 편 {dep_time} < {outbound_limit} ? {'YES' if dep_time < outbound_limit else 'NO'}")
    print(f"오는 편 {ret_time} >= {inbound_limit} ? {'YES' if ret_time >= inbound_limit else 'NO'}")
    print(f"예상 결과: {dep_time < outbound_limit and ret_time >= inbound_limit}")
    
    return result

def test_other_cases():
    """다른 케이스들도 테스트"""
    
    config = {
        'time_type': 'exact',
        'outbound_exact_hour': 11,
        'inbound_exact_hour': 14
    }
    
    test_cases = [
        ("07:15", "13:45", False),  # 사용자 케이스 - 오는 편이 14시 이전
        ("07:15", "14:15", True),   # 정상 케이스 - 둘 다 조건 만족
        ("11:15", "14:15", False),  # 가는 편이 11시 이후
        ("07:15", "14:00", True),   # 경계값 - 14:00은 14시 이후로 간주
        ("11:00", "14:15", True),   # 경계값 - 11:00은 11시 이하에 포함
    ]
    
    print("=== 추가 테스트 케이스 ===")
    for dep, ret, expected in test_cases:
        result = check_time_restrictions(dep, ret, config)
        status = "✅" if result == expected else "❌"
        print(f"{status} 가는편={dep}, 오는편={ret} → 결과={result} (예상={expected})")

if __name__ == "__main__":
    test_your_case()
    print()
    test_other_cases()
