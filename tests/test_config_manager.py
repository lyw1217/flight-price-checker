#!/usr/bin/env python3
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, mock_open
from .test_base import BaseTestCase


class TestConfigManager(BaseTestCase):
    """설정 관리 관련 테스트"""

    @patch('flight_checker.config_manager.load_json_data')
    @patch('flight_checker.config_manager.save_json_data')
    def test_get_and_save_user_config(self, mock_save_json_data, mock_load_json_data):
        """사용자 설정 로드 및 저장 테스트"""
        mock_load_json_data.side_effect = FileNotFoundError
        
        with patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'read_text', side_effect=FileNotFoundError), \
             patch('builtins.open', new_callable=mock_open):
            config = self.get_user_config(self.test_user_id)
            self.assertIsNotNone(config)
            self.assertEqual(config['time_type'], self.DEFAULT_USER_CONFIG['time_type'])
            self.assertIsNotNone(config.get('created_at'))
            self.assertIsNotNone(config.get('last_activity'))

        saved_config_data = self.DEFAULT_USER_CONFIG.copy()
        saved_config_data['outbound_periods'] = ["오후1"]
        saved_config_data['created_at'] = self.format_datetime(datetime.now() - timedelta(days=1))
        saved_config_data['last_activity'] = self.format_datetime(datetime.now() - timedelta(hours=1))
        
        mock_load_json_data.side_effect = None
        mock_load_json_data.return_value = saved_config_data
        
        # get_user_config 내부의 파일 읽기/쓰기를 보다 정교하게 모킹
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'read_text', return_value=json.dumps(saved_config_data)), \
             patch.object(Path, 'write_text') as mock_user_config_write_text:
            loaded_config = self.get_user_config(self.test_user_id)

        self.assertEqual(loaded_config['time_type'], 'time_period')
        self.assertEqual(loaded_config['outbound_periods'], ["오후1"])
        self.assertIsNotNone(loaded_config.get('last_activity'))
        
        # get_user_config 내부에서 last_activity 업데이트 후 저장이 한 번 일어남을 확인
        mock_user_config_write_text.assert_called_once()
        
        new_config = loaded_config.copy()
        new_config['time_type'] = 'exact'
        new_config['outbound_exact_hour'] = 10
        self.save_user_config(self.test_user_id, new_config)
        mock_save_json_data.assert_called_once()
        args, _ = mock_save_json_data.call_args
        saved_file_path, saved_data_to_file = args
        
        self.assertEqual(saved_file_path, self.user_configs_path / f"config_{self.test_user_id}.json")
        self.assertEqual(saved_data_to_file['time_type'], 'exact')
        self.assertEqual(saved_data_to_file['outbound_exact_hour'], 10)
        self.assertIsNotNone(saved_data_to_file.get('last_activity'))
        self.assertIsNotNone(saved_data_to_file.get('created_at'))

    def test_config_manager_integration_time_type_exact(self):
        """config_manager를 사용한 통합 테스트 - time_type이 exact인 경우"""
        user_id = 98765
        
        # 1. exact 설정 저장
        exact_config = {
            "time_type": "exact",
            "outbound_exact_hour": 8,
            "inbound_exact_hour": 17,
            "outbound_periods": ["오전1"],
            "inbound_periods": ["오후2"]
        }
        self.save_user_config(user_id, exact_config)
        
        # 2. 설정 로드
        loaded_config = self.get_user_config(user_id)
        
        # 3. 로드된 설정 검증
        self.assertEqual(loaded_config['time_type'], 'exact')
        self.assertEqual(loaded_config['outbound_exact_hour'], 8)
        self.assertEqual(loaded_config['inbound_exact_hour'], 17)
        
        # 4. exact 모드에서 시간 체크 테스트
        # time_type이 exact이므로 exact_hour 설정이 적용되어야 함
        self.assertTrue(self.check_time_restrictions("07:30", "18:00", loaded_config))   # 8시 이전, 17시 이후
        self.assertTrue(self.check_time_restrictions("08:00", "17:00", loaded_config))   # 경계값들
        
        self.assertFalse(self.check_time_restrictions("08:30", "18:00", loaded_config))  # 8시 이후
        self.assertFalse(self.check_time_restrictions("07:30", "16:30", loaded_config))  # 17시 이전

    def test_config_manager_integration_time_type_time_period(self):
        """config_manager를 사용한 통합 테스트 - time_type이 time_period인 경우"""
        user_id = 54321
        
        # 1. time_period 설정 저장
        period_config = {
            "time_type": "time_period",
            "outbound_periods": ["오전1", "오전2"],  # 6-12시
            "inbound_periods": ["오후1", "오후2"],   # 12-18시
            "outbound_exact_hour": 9,   # time_period 모드에서는 사용되지 않음
            "inbound_exact_hour": 15    # time_period 모드에서는 사용되지 않음
        }
        self.save_user_config(user_id, period_config)
        
        # 2. 설정 로드
        loaded_config = self.get_user_config(user_id)
        
        # 3. 로드된 설정 검증
        self.assertEqual(loaded_config['time_type'], 'time_period')
        self.assertEqual(loaded_config['outbound_periods'], ["오전1", "오전2"])
        self.assertEqual(loaded_config['inbound_periods'], ["오후1", "오후2"])
        
        # 4. time_period 모드에서 시간 체크 테스트
        # time_type이 time_period이므로 periods 설정이 적용되어야 함
        self.assertTrue(self.check_time_restrictions("06:00", "12:00", loaded_config))   # 경계값들
        self.assertTrue(self.check_time_restrictions("11:59", "17:59", loaded_config))   # 경계값들
        
        self.assertFalse(self.check_time_restrictions("05:30", "13:00", loaded_config))  # 가는 편이 6시 이전
        self.assertFalse(self.check_time_restrictions("12:30", "13:00", loaded_config))  # 가는 편이 12시 이후
        self.assertFalse(self.check_time_restrictions("07:00", "11:30", loaded_config))  # 오는 편이 12시 이전
        self.assertFalse(self.check_time_restrictions("07:00", "18:30", loaded_config))  # 오는 편이 18시 이후

    def test_config_manager_integration_config_persistence(self):
        """config_manager를 사용한 설정 영속성 테스트"""
        user_id = 11111
        
        # 1. 초기 설정 저장
        initial_config = {
            "time_type": "exact",
            "outbound_exact_hour": 8,
            "inbound_exact_hour": 18,
            "outbound_periods": ["새벽"],
            "inbound_periods": ["밤2"]
        }
        self.save_user_config(user_id, initial_config)
        
        # 2. 첫 번째 로드 및 검증
        config_1 = self.get_user_config(user_id)
        self.assertEqual(config_1['time_type'], 'exact')
        self.assertEqual(config_1['outbound_exact_hour'], 8)
        self.assertEqual(config_1['inbound_exact_hour'], 18)
        
        # 3. 설정 변경 및 재저장
        modified_config = config_1.copy()
        modified_config['time_type'] = 'time_period'
        modified_config['outbound_periods'] = ['오전2', '오후1']
        modified_config['inbound_periods'] = ['오후2', '밤1']
        self.save_user_config(user_id, modified_config)
        
        # 4. 두 번째 로드 및 변경사항 검증
        config_2 = self.get_user_config(user_id)
        self.assertEqual(config_2['time_type'], 'time_period')
        self.assertEqual(config_2['outbound_periods'], ['오전2', '오후1'])
        self.assertEqual(config_2['inbound_periods'], ['오후2', '밤1'])
        
        # 5. 시간 체크로 실제 동작 검증
        # time_period 모드로 변경되었으므로 period 설정이 적용되어야 함
        self.assertTrue(self.check_time_restrictions("10:00", "16:00", config_2))   # 오전2(9-12) + 오후2(15-18)
        self.assertTrue(self.check_time_restrictions("13:30", "19:30", config_2))   # 오후1(12-15) + 밤1(18-21)
        self.assertFalse(self.check_time_restrictions("07:30", "16:00", config_2))  # 가는 편이 설정 범위 밖
        
        # 6. 메타데이터 검증
        self.assertIn('created_at', config_2)
        self.assertIn('last_activity', config_2)
        self.assertIsNotNone(config_2['created_at'])
        self.assertIsNotNone(config_2['last_activity'])

    def test_config_manager_integration_default_config_handling(self):
        """config_manager를 사용한 기본 설정 처리 테스트"""
        user_id = 22222
        
        # 1. 존재하지 않는 사용자의 설정 로드 (기본 설정 반환)
        config = self.get_user_config(user_id)
        
        # 2. 기본 설정 검증
        self.assertEqual(config['time_type'], self.DEFAULT_USER_CONFIG['time_type'])
        self.assertEqual(config['outbound_periods'], self.DEFAULT_USER_CONFIG['outbound_periods'])
        self.assertEqual(config['inbound_periods'], self.DEFAULT_USER_CONFIG['inbound_periods'])
        self.assertEqual(config['outbound_exact_hour'], self.DEFAULT_USER_CONFIG['outbound_exact_hour'])
        self.assertEqual(config['inbound_exact_hour'], self.DEFAULT_USER_CONFIG['inbound_exact_hour'])
        
        # 3. 메타데이터가 자동 생성되었는지 확인
        self.assertIn('created_at', config)
        self.assertIn('last_activity', config)
        
        # 4. 기본 설정으로 시간 체크 테스트
        # DEFAULT_USER_CONFIG의 time_type에 따라 테스트
        if self.DEFAULT_USER_CONFIG['time_type'] == 'time_period':
            # 기본 periods 설정을 확인
            default_outbound = self.DEFAULT_USER_CONFIG['outbound_periods']
            default_inbound = self.DEFAULT_USER_CONFIG['inbound_periods']
            
            # 각 시간대의 실제 시간 범위를 확인하여 테스트
            valid_outbound_time = "07:00" if "오전1" in default_outbound else "10:00"
            valid_inbound_time = "13:00" if "오후1" in default_inbound else "16:00"
            
            # 기본 설정에 맞는 시간으로 테스트
            result = self.check_time_restrictions(valid_outbound_time, valid_inbound_time, config)
            # 결과가 True 또는 False든 상관없이, 에러 없이 실행되어야 함
            self.assertIsInstance(result, bool)
        
        elif self.DEFAULT_USER_CONFIG['time_type'] == 'exact':
            # 기본 exact 설정으로 테스트
            default_out_hour = self.DEFAULT_USER_CONFIG['outbound_exact_hour']
            default_in_hour = self.DEFAULT_USER_CONFIG['inbound_exact_hour']
            
            # 조건을 만족하는 시간으로 테스트
            valid_out_time = f"{default_out_hour-1:02d}:00"
            valid_in_time = f"{default_in_hour+1:02d}:00"
            
            result = self.check_time_restrictions(valid_out_time, valid_in_time, config)
            self.assertTrue(result)

    def test_config_manager_integration_user_id_none_handling(self):
        """config_manager를 사용한 user_id가 None인 경우 처리 테스트"""
        
        # 1. user_id가 None인 경우 설정 로드
        config = self.get_user_config(None)
        
        # 2. 기본 설정이 반환되는지 확인
        self.assertEqual(config['time_type'], self.DEFAULT_USER_CONFIG['time_type'])
        self.assertEqual(config['outbound_periods'], self.DEFAULT_USER_CONFIG['outbound_periods'])
        self.assertEqual(config['inbound_periods'], self.DEFAULT_USER_CONFIG['inbound_periods'])
        
        # 3. None user_id로 시간 체크 테스트
        # 기본 설정이 정상적으로 동작하는지 확인
        result = self.check_time_restrictions("08:00", "15:00", config)
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    import unittest
    unittest.main()
