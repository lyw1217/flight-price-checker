#!/usr/bin/env python3
import unittest
from unittest.mock import patch, MagicMock
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


class BaseTestCase(unittest.TestCase):
    """테스트 케이스의 기본 클래스"""
    _airports_patcher = None
    logger_patcher = None
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
        cls.MessageManager = cls.flight_checker_module.message_manager.__class__
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
        cls.format_datetime = cls.flight_checker_module.config_manager.format_datetime
        cls.AIRPORTS_loaded = cls.flight_checker_module.AIRPORTS
        cls.user_configs_path_class = cls.flight_checker_module.USER_CONFIG_DIR
        cls.logs_path_class = cls.flight_checker_module.LOG_DIR

    @classmethod
    def tearDownClass(cls):
        if cls.logger_patcher:
            cls.logger_patcher.stop()
        if cls._airports_patcher:
            cls._airports_patcher.stop()
        
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
