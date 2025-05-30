#!/usr/bin/env python3
import unittest
from unittest.mock import patch, mock_open, MagicMock, AsyncMock
import asyncio
from datetime import datetime, timedelta, time
import sys
import os
import json
from pathlib import Path
import shutil
import importlib

# --- 테스트 환경 설정 시작 ---
_test_data_root_for_env = (Path(__file__).parent / 'test_temp_data_flight_checker_env').resolve()
os.environ['FLIGHT_CHECKER_TEST_DATA_DIR'] = str(_test_data_root_for_env)
os.environ['BOT_TOKEN'] = 'test_bot_token'
os.environ['ADMIN_IDS'] = '12345'
# --- 테스트 환경 설정 종료 ---

# 프로젝트 루트 디렉토리를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# flight_checker 모듈 및 해당 심볼들은 setUpClass에서 import 및 할당

# @patch('flight_checker.logger', MagicMock()) # 클래스 데코레이터 제거
class TestFlightChecker(unittest.TestCase):
    _airports_patcher = None
    logger_patcher = None # 로거 패처를 위한 클래스 변수
    flight_checker_module = None
    MessageManager = None
    validate_url = None
    parse_flight_info = None
    check_time_restrictions = None
    valid_date = None
    valid_airport = None
    get_user_config = None
    save_user_config = None
    format_time_range = None
    get_time_range = None
    DEFAULT_USER_CONFIG = None
    TIME_PERIODS = None
    format_datetime = None
    AIRPORTS_loaded = None
    user_configs_path_class = None
    logs_path_class = None

    @classmethod
    def setUpClass(cls):
        cls.test_data_root = _test_data_root_for_env
        cls.test_airports_json_target_path = cls.test_data_root / "airports.json"

        # AIRPORTS_JSON_PATH 패치 시작
        cls._airports_patcher = patch('flight_checker.AIRPORTS_JSON_PATH', cls.test_airports_json_target_path)
        cls._airports_patcher.start()

        # 테스트용 임시 airports.json 파일 생성
        cls.test_data_root.mkdir(parents=True, exist_ok=True)
        test_airport_data = {
            "KOR": {"name": "한국", "airports": {"ICN": ["인천", "서울/인천국제공항"], "GMP": ["김포", "서울/김포국제공항"]}},
            "JPN": {"name": "일본", "airports": {"NRT": ["나리타", "도쿄/나리타국제공항"], "FUK": ["후쿠오카", "후쿠오카국제공항"]}}
        }
        with open(cls.test_airports_json_target_path, 'w', encoding='utf-8') as f:
            json.dump(test_airport_data, f, ensure_ascii=False, indent=2)

        # flight_checker 모듈 로드 (패치 이후)
        if "flight_checker" in sys.modules:
            cls.flight_checker_module = importlib.reload(sys.modules["flight_checker"])
        else:
            import flight_checker as fc_module
            cls.flight_checker_module = fc_module
        
        # 로거 패치 시작 (모듈 로드 이후)
        cls.logger_patcher = patch.object(cls.flight_checker_module, 'logger', MagicMock())
        cls.logger_patcher.start()
        
        # 필요한 심볼들을 클래스 변수에 할당
        cls.MessageManager = cls.flight_checker_module.MessageManager
        cls.validate_url = cls.flight_checker_module.validate_url
        cls.parse_flight_info = cls.flight_checker_module.parse_flight_info
        cls.check_time_restrictions = cls.flight_checker_module.check_time_restrictions
        cls.valid_date = cls.flight_checker_module.valid_date
        cls.valid_airport = cls.flight_checker_module.valid_airport
        cls.get_user_config = cls.flight_checker_module.get_user_config
        cls.save_user_config = cls.flight_checker_module.save_user_config
        cls.format_time_range = cls.flight_checker_module.format_time_range
        cls.get_time_range = cls.flight_checker_module.get_time_range
        cls.DEFAULT_USER_CONFIG = cls.flight_checker_module.DEFAULT_USER_CONFIG
        cls.TIME_PERIODS = cls.flight_checker_module.TIME_PERIODS
        cls.format_datetime = cls.flight_checker_module.format_datetime
        cls.AIRPORTS_loaded = cls.flight_checker_module.AIRPORTS
        cls.user_configs_path_class = cls.flight_checker_module.USER_CONFIG_DIR
        cls.logs_path_class = cls.flight_checker_module.LOG_DIR

    @classmethod
    def tearDownClass(cls):
        if cls.logger_patcher: # 로거 패처 중지
            cls.logger_patcher.stop()
        if cls._airports_patcher:
            cls._airports_patcher.stop()
        
        # patch.stopall() # 또는 모든 패치를 한 번에 중지

        if cls.test_data_root.exists():
            shutil.rmtree(cls.test_data_root)
        if 'FLIGHT_CHECKER_TEST_DATA_DIR' in os.environ:
            del os.environ['FLIGHT_CHECKER_TEST_DATA_DIR']
        if 'BOT_TOKEN' in os.environ:
            del os.environ['BOT_TOKEN']
        if 'ADMIN_IDS' in os.environ:
            del os.environ['ADMIN_IDS']

    def setUp(self):
        self.test_user_id = 12345
        self.message_manager = self.__class__.MessageManager()
        self.validate_url = self.__class__.validate_url
        self.parse_flight_info = self.__class__.parse_flight_info
        self.check_time_restrictions = self.__class__.check_time_restrictions
        self.valid_date = self.__class__.valid_date
        self.valid_airport = self.__class__.valid_airport
        self.get_user_config = self.__class__.get_user_config
        self.save_user_config = self.__class__.save_user_config
        self.format_time_range = self.__class__.format_time_range
        self.get_time_range = self.__class__.get_time_range
        self.DEFAULT_USER_CONFIG = self.__class__.DEFAULT_USER_CONFIG
        self.TIME_PERIODS = self.__class__.TIME_PERIODS
        self.format_datetime = self.__class__.format_datetime
        self.AIRPORTS = self.__class__.AIRPORTS_loaded
        self.user_configs_path = self.__class__.user_configs_path_class
        self.logs_path = self.__class__.logs_path_class

    def tearDown(self):
        pass

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
        
    def test_check_time_restrictions(self):
        """시간 제한 체크 테스트"""
        period_config = {"time_type": "time_period", "outbound_periods": ["오전1"], "inbound_periods": ["오후1"]}
        self.assertTrue(self.check_time_restrictions("07:00", "13:00", period_config))
        self.assertFalse(self.check_time_restrictions("10:00", "13:00", period_config))
        self.assertFalse(self.check_time_restrictions("07:00", "16:00", period_config))
        exact_config = {"time_type": "exact", "outbound_exact_hour": 9, "inbound_exact_hour": 15}
        self.assertTrue(self.check_time_restrictions("08:00", "16:00", exact_config))
        self.assertFalse(self.check_time_restrictions("10:00", "16:00", exact_config))
        self.assertFalse(self.check_time_restrictions("08:00", "14:00", exact_config))
        
    def test_valid_date(self):
        """날짜 유효성 검사 테스트"""
        today = datetime.now()
        future_date = (today + timedelta(days=30)).strftime("%Y%m%d")
        past_date = (today - timedelta(days=1)).strftime("%Y%m%d")
        far_future = (today + timedelta(days=400)).strftime("%Y%m%d")
        is_valid, _ = self.valid_date(future_date); self.assertTrue(is_valid)
        is_valid, _ = self.valid_date(past_date); self.assertFalse(is_valid)
        is_valid, _ = self.valid_date(far_future); self.assertFalse(is_valid)
        is_valid, _ = self.valid_date("invalid"); self.assertFalse(is_valid)

    @patch('flight_checker.save_json_data')
    @patch('flight_checker.load_json_data')
    def test_get_and_save_user_config(self, mock_load_json_data, mock_save_json_data):
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
        
        mock_load_json_data.side_effect = None # 이전 FileNotFoundError 효과 제거
        mock_load_json_data.return_value = saved_config_data
        
        # get_user_config 내부의 파일 읽기/쓰기를 보다 정교하게 모킹
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'read_text', return_value=json.dumps(saved_config_data)), \
             patch.object(Path, 'write_text') as mock_user_config_write_text: # write_text 모킹
            loaded_config = self.get_user_config(self.test_user_id)
        
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
        saved_file_path, saved_data_to_file = args # 변수명 변경 (saved_data -> saved_data_to_file)
        self.assertEqual(saved_file_path, self.user_configs_path / f"config_{self.test_user_id}.json")
        self.assertEqual(saved_data_to_file['time_type'], 'exact')
        self.assertEqual(saved_data_to_file['outbound_exact_hour'], 10)
        self.assertIsNotNone(saved_data_to_file.get('last_activity'))
        self.assertIsNotNone(saved_data_to_file.get('created_at'))

    def test_format_time_range(self):
        """시간 설정 문자열 변환 테스트"""
        period_config = {"time_type": "time_period", "outbound_periods": ["오전1", "오전2"], "inbound_periods": ["오후2", "밤1"]}
        self.assertEqual(self.format_time_range(period_config, 'outbound'), "오전1, 오전2 (06:00-12:00)")
        self.assertEqual(self.format_time_range(period_config, 'inbound'), "오후2, 밤1 (15:00-18:00 / 18:00-21:00)")
        exact_config = {"time_type": "exact", "outbound_exact_hour": 8, "inbound_exact_hour": 17}
        self.assertEqual(self.format_time_range(exact_config, 'outbound'), "08:00 이전")
        self.assertEqual(self.format_time_range(exact_config, 'inbound'), "17:00 이후")

    def test_get_time_range(self):
        """시간 범위 반환 테스트"""
        period_config = {"time_type": "time_period", "outbound_periods": ["오전1"], "inbound_periods": ["오후1"]}
        start_time, end_time = self.get_time_range(period_config, 'outbound'); self.assertIsNone(start_time); self.assertIsNone(end_time)
        start_time, end_time = self.get_time_range(period_config, 'inbound'); self.assertIsNone(start_time); self.assertIsNone(end_time)
        exact_config = {"time_type": "exact", "outbound_exact_hour": 10, "inbound_exact_hour": 14}
        start_time, end_time = self.get_time_range(exact_config, 'outbound'); self.assertEqual(start_time, time(hour=0, minute=0)); self.assertEqual(end_time, time(hour=10, minute=0))
        start_time, end_time = self.get_time_range(exact_config, 'inbound'); self.assertEqual(start_time, time(hour=14, minute=0)); self.assertEqual(end_time, time(hour=23, minute=59))

    async def helper_test_message_manager_update(self, existing_message_text=None, new_text="New Text", should_edit_fail=False, should_reply_fail=False):
        user_id = self.test_user_id
        mock_message = MagicMock()
        mock_message.message_id = 123
        mock_message.chat_id = user_id
        if existing_message_text:
            mock_message.text = existing_message_text
            self.message_manager.set_status_message(user_id, mock_message)
        async def mock_edit_text(*args, **kwargs):
            if should_edit_fail: raise MagicMock(side_effect=Exception("Edit failed"))
            if kwargs.get('text') == mock_message.text and existing_message_text is not None: return mock_message
            mock_message.text = kwargs.get('text'); return mock_message
        async def mock_reply_text(*args, **kwargs):
            if should_reply_fail: raise Exception("Reply failed")
            new_msg = MagicMock(); new_msg.text = kwargs.get('text'); return new_msg
        mock_message.edit_text = MagicMock(side_effect=mock_edit_text)
        mock_message.reply_text = MagicMock(side_effect=mock_reply_text)
        
        # safe_edit_message를 AsyncMock으로 패치
        with patch.object(self.flight_checker_module, 'safe_edit_message', new_callable=AsyncMock) as mock_safe_edit:
            if existing_message_text:
                if should_edit_fail:
                    if should_reply_fail:
                        # AsyncMock은 awaitable 객체를 반환하도록 설정 필요
                        async def side_effect_none(*args, **kwargs): return None
                        mock_safe_edit.side_effect = side_effect_none
                    else:
                        new_reply_message = MagicMock(text=new_text)
                        async def side_effect_reply(*args, **kwargs): return new_reply_message
                        mock_safe_edit.side_effect = side_effect_reply
                else:
                    edited_message = MagicMock(text=new_text)
                    async def side_effect_edit(*args, **kwargs): return edited_message
                    mock_safe_edit.side_effect = side_effect_edit 
            else:
                # 이 경우 update_status_message는 safe_edit_message를 호출하지 않음
                # 따라서 mock_safe_edit.return_value = None 설정 불필요
                pass 

            updated_message = await self.message_manager.update_status_message(user_id, new_text)
            
            if existing_message_text:
                mock_safe_edit.assert_called_once()
                call_args = mock_safe_edit.call_args[0]
                self.assertEqual(call_args[1], new_text)
                if should_edit_fail and not should_reply_fail:
                    self.assertEqual(updated_message.text, new_text)
                    self.assertEqual(self.message_manager.status_messages[user_id].text, new_text)
                elif not should_edit_fail:
                    self.assertEqual(updated_message.text, new_text)
                    self.assertEqual(self.message_manager.status_messages[user_id].text, new_text)
                else: 
                    self.assertIsNone(updated_message)
                    self.assertNotIn(user_id, self.message_manager.status_messages)
            else: 
                self.assertIsNone(updated_message)
                mock_safe_edit.assert_not_called()

    def test_message_manager_update_existing_success(self):
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text"))
    def test_message_manager_update_existing_edit_fail_reply_success(self):
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text", should_edit_fail=True))
    def test_message_manager_update_existing_edit_fail_reply_fail(self):
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text", should_edit_fail=True, should_reply_fail=True))
    def test_message_manager_update_no_existing_message(self):
        asyncio.run(self.helper_test_message_manager_update(new_text="New Text"))
    def test_message_manager_set_and_clear(self):
        user_id = self.test_user_id
        mock_message = MagicMock()
        self.message_manager.set_status_message(user_id, mock_message)
        self.assertIn(user_id, self.message_manager.status_messages)
        self.assertEqual(self.message_manager.status_messages[user_id], mock_message)
        self.message_manager.clear_status_message(user_id)
        self.assertNotIn(user_id, self.message_manager.status_messages)

if __name__ == "__main__":
    unittest.main() 