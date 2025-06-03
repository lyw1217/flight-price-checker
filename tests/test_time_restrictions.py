#!/usr/bin/env python3
from .test_base import BaseTestCase


class TestTimeRestrictions(BaseTestCase):
    """시간 제한 체크 테스트"""

    def test_check_time_restrictions_basic(self):
        """기본 시간 제한 체크 테스트"""
        period_config = {"time_type": "time_period", "outbound_periods": ["오전1"], "inbound_periods": ["오후1"]}
        self.assertTrue(self.check_time_restrictions("07:00", "13:00", period_config))
        self.assertFalse(self.check_time_restrictions("10:00", "13:00", period_config))
        self.assertFalse(self.check_time_restrictions("07:00", "16:00", period_config))
        
        exact_config = {"time_type": "exact", "outbound_exact_hour": 9, "inbound_exact_hour": 15}
        self.assertTrue(self.check_time_restrictions("08:00", "16:00", exact_config))
        self.assertTrue(self.check_time_restrictions("09:00", "15:00", exact_config))  # 경계값 포함
        self.assertFalse(self.check_time_restrictions("10:00", "16:00", exact_config))
        self.assertFalse(self.check_time_restrictions("08:00", "14:00", exact_config))

    def test_time_period_restrictions_comprehensive(self):
        """시간대 설정 종합 테스트"""
        # 새벽(0-6), 오전1(6-9), 오전2(9-12), 오후1(12-15), 오후2(15-18), 밤1(18-21), 밤2(21-24)
        
        # 단일 시간대 테스트
        config = {"time_type": "time_period", "outbound_periods": ["오전1"], "inbound_periods": ["오후2"]}
        
        # 가는 편 시간대 테스트 (오전1: 6-9시)
        self.assertTrue(self.check_time_restrictions("06:00", "15:30", config))   # 6시 정각 (경계값)
        self.assertTrue(self.check_time_restrictions("07:30", "16:00", config))   # 중간값
        self.assertTrue(self.check_time_restrictions("08:59", "17:30", config))   # 8:59 (경계값)
        self.assertFalse(self.check_time_restrictions("05:59", "16:00", config))  # 6시 이전
        self.assertFalse(self.check_time_restrictions("09:00", "16:00", config))  # 9시 이후
        
        # 오는 편 시간대 테스트 (오후2: 15-18시)
        self.assertTrue(self.check_time_restrictions("07:00", "15:00", config))   # 15시 정각 (경계값)
        self.assertTrue(self.check_time_restrictions("07:00", "16:30", config))   # 중간값
        self.assertTrue(self.check_time_restrictions("07:00", "17:59", config))   # 17:59 (경계값)
        self.assertFalse(self.check_time_restrictions("07:00", "14:59", config))  # 15시 이전
        self.assertFalse(self.check_time_restrictions("07:00", "18:00", config))  # 18시 이후
        
        # 복수 시간대 테스트
        multi_config = {
            "time_type": "time_period", 
            "outbound_periods": ["새벽", "오전1", "오전2"], 
            "inbound_periods": ["오후1", "오후2", "밤1"]
        }
        
        # 가는 편: 새벽(0-6) + 오전1(6-9) + 오전2(9-12) = 0-12시
        self.assertTrue(self.check_time_restrictions("00:00", "13:00", multi_config))  # 자정
        self.assertTrue(self.check_time_restrictions("05:59", "13:00", multi_config))  # 새벽 끝
        self.assertTrue(self.check_time_restrictions("06:00", "13:00", multi_config))  # 오전1 시작
        self.assertTrue(self.check_time_restrictions("08:59", "13:00", multi_config))  # 오전1 끝
        self.assertTrue(self.check_time_restrictions("09:00", "13:00", multi_config))  # 오전2 시작
        self.assertTrue(self.check_time_restrictions("11:59", "13:00", multi_config))  # 오전2 끝
        self.assertFalse(self.check_time_restrictions("12:00", "13:00", multi_config)) # 오전2 이후
        
        # 오는 편: 오후1(12-15) + 오후2(15-18) + 밤1(18-21) = 12-21시
        self.assertTrue(self.check_time_restrictions("07:00", "12:00", multi_config))  # 오후1 시작
        self.assertTrue(self.check_time_restrictions("07:00", "14:59", multi_config))  # 오후1 끝
        self.assertTrue(self.check_time_restrictions("07:00", "15:00", multi_config))  # 오후2 시작
        self.assertTrue(self.check_time_restrictions("07:00", "17:59", multi_config))  # 오후2 끝
        self.assertTrue(self.check_time_restrictions("07:00", "18:00", multi_config))  # 밤1 시작
        self.assertTrue(self.check_time_restrictions("07:00", "20:59", multi_config))  # 밤1 끝
        self.assertFalse(self.check_time_restrictions("07:00", "11:59", multi_config)) # 오후1 이전
        self.assertFalse(self.check_time_restrictions("07:00", "21:00", multi_config)) # 밤1 이후

    def test_exact_time_restrictions_comprehensive(self):
        """시각 설정 종합 테스트"""
        
        # 기본 케이스: 가는 편 11시 이전, 오는 편 14시 이후
        config = {"time_type": "exact", "outbound_exact_hour": 11, "inbound_exact_hour": 14}
        
        # 가는 편 테스트 (11시 이하)
        self.assertTrue(self.check_time_restrictions("10:59", "14:00", config))   # 경계값 - 11시 직전
        self.assertTrue(self.check_time_restrictions("00:00", "15:00", config))   # 자정
        self.assertTrue(self.check_time_restrictions("06:30", "16:00", config))   # 일반적인 아침 시간
        self.assertTrue(self.check_time_restrictions("11:00", "15:00", config))   # 경계값 - 11시 정각 (포함)
        self.assertFalse(self.check_time_restrictions("11:01", "15:00", config))  # 11시 이후
        self.assertFalse(self.check_time_restrictions("23:59", "15:00", config))  # 밤 늦은 시간
        
        # 오는 편 테스트 (14시 이상)
        self.assertTrue(self.check_time_restrictions("08:00", "14:00", config))   # 경계값 - 14시 정각
        self.assertTrue(self.check_time_restrictions("08:00", "14:01", config))   # 14시 직후
        self.assertTrue(self.check_time_restrictions("08:00", "23:59", config))   # 밤 늦은 시간
        self.assertFalse(self.check_time_restrictions("08:00", "13:59", config))  # 경계값 - 14시 직전
        self.assertFalse(self.check_time_restrictions("08:00", "00:00", config))  # 자정
        self.assertFalse(self.check_time_restrictions("08:00", "12:30", config))  # 일반적인 점심 시간
        
        # 극단적인 설정 테스트
        early_config = {"time_type": "exact", "outbound_exact_hour": 6, "inbound_exact_hour": 22}
        self.assertTrue(self.check_time_restrictions("05:59", "22:00", early_config))   # 매우 이른 출발, 늦은 복귀
        self.assertTrue(self.check_time_restrictions("06:00", "22:00", early_config))   # 경계값 (6시 포함)
        self.assertFalse(self.check_time_restrictions("06:01", "22:00", early_config))  # 6시 이후
        self.assertFalse(self.check_time_restrictions("05:59", "21:59", early_config))  # 22시 이전
        
        # 같은 시간 설정
        same_config = {"time_type": "exact", "outbound_exact_hour": 12, "inbound_exact_hour": 12}
        self.assertTrue(self.check_time_restrictions("11:59", "12:00", same_config))    # 둘 다 12시
        self.assertTrue(self.check_time_restrictions("12:00", "12:00", same_config))    # 가는 편도 12시 (포함)
        self.assertFalse(self.check_time_restrictions("12:01", "12:00", same_config))   # 가는 편이 12시 이후
        self.assertFalse(self.check_time_restrictions("11:59", "11:59", same_config))   # 오는 편이 12시 이전

    def test_edge_cases_time_restrictions(self):
        """시간 제한 체크 엣지 케이스 테스트"""
        
        # 자정 시간 처리
        midnight_config = {"time_type": "exact", "outbound_exact_hour": 1, "inbound_exact_hour": 23}
        self.assertTrue(self.check_time_restrictions("00:00", "23:00", midnight_config))   # 자정 출발
        self.assertTrue(self.check_time_restrictions("00:59", "23:59", midnight_config))   # 1시 직전, 23:59 복귀
        self.assertTrue(self.check_time_restrictions("01:00", "23:00", midnight_config))   # 1시 정각 (포함)
        self.assertFalse(self.check_time_restrictions("01:01", "23:00", midnight_config))  # 1시 이후
        
        # 시간대별 경계값 테스트 (새벽 시간대)
        dawn_config = {"time_type": "time_period", "outbound_periods": ["새벽"], "inbound_periods": ["새벽"]}
        self.assertTrue(self.check_time_restrictions("00:00", "05:59", dawn_config))   # 새벽 시간대 (0-6시)
        self.assertTrue(self.check_time_restrictions("05:59", "05:59", dawn_config))   # 경계값
        self.assertFalse(self.check_time_restrictions("06:00", "05:59", dawn_config))  # 새벽 이후
        self.assertFalse(self.check_time_restrictions("00:00", "06:00", dawn_config))  # 새벽 이후

    def test_real_world_scenarios(self):
        """실제 사용 시나리오 테스트"""
        
        # 시나리오 1: 직장인 - 오전 일찍 출발, 오후 늦게 복귀
        worker_config = {
            "time_type": "time_period", 
            "outbound_periods": ["새벽", "오전1"], 
            "inbound_periods": ["오후2", "밤1", "밤2"]
        }
        self.assertTrue(self.check_time_restrictions("05:30", "19:30", worker_config))   # 이른 출발, 저녁 복귀
        self.assertFalse(self.check_time_restrictions("10:30", "19:30", worker_config))  # 늦은 출발
        self.assertFalse(self.check_time_restrictions("05:30", "14:30", worker_config))  # 이른 복귀
        
        # 시나리오 2: 학생 - 오전 중간, 오후 일찍 복귀
        student_config = {
            "time_type": "time_period", 
            "outbound_periods": ["오전2"], 
            "inbound_periods": ["오후1"]
        }
        self.assertTrue(self.check_time_restrictions("10:30", "13:30", student_config))  # 오전 늦게, 오후 일찍
        self.assertFalse(self.check_time_restrictions("07:30", "13:30", student_config)) # 너무 이른 출발
        self.assertFalse(self.check_time_restrictions("10:30", "16:30", student_config)) # 너무 늦은 복귀
        
        # 시나리오 3: 여유 있는 일정 - 정확한 시간 설정
        leisure_config = {"time_type": "exact", "outbound_exact_hour": 10, "inbound_exact_hour": 16}
        self.assertTrue(self.check_time_restrictions("08:30", "18:30", leisure_config))  # 여유 있는 시간
        self.assertTrue(self.check_time_restrictions("10:00", "16:00", leisure_config))  # 경계값 정확히
        self.assertFalse(self.check_time_restrictions("11:30", "18:30", leisure_config)) # 늦은 출발
        self.assertFalse(self.check_time_restrictions("08:30", "15:30", leisure_config)) # 이른 복귀


if __name__ == "__main__":
    import unittest
    unittest.main()
