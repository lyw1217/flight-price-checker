#!/usr/bin/env python3
"""
Configuration Manager for Flight Price Checker Bot

이 모듈은 항공권 가격 체커 봇의 설정 관리를 담당합니다.
- 환경변수 검증 및 로드
- 사용자 설정 파일 관리
- 디렉토리 및 파일 경로 설정
- 로깅 설정
"""

import os
import json
import logging
import contextlib
import platform
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Literal
from urllib.parse import urlparse

# Platform-specific imports for file locking
if platform.system() == 'Windows':
    import msvcrt
else:
    import fcntl

# 알림 조건 타입 정의
NotificationPreferenceType = Literal[
    "PRICE_DROP_THRESHOLD",  # 설정된 값 이상 가격 하락 시 알림 (기본)
    "PRICE_DROP_ANY",        # 1원이라도 가격 하락 시 알림
    "ANY_PRICE_CHANGE",      # 가격 상승 또는 하락 시 모두 알림
    "TARGET_PRICE_REACHED",  # 사용자가 설정한 목표 가격 이하 도달 시 알림
    "HISTORICAL_LOW_UPDATED" # 모니터링 시작 이후 가장 낮은 가격 갱신 시 알림
]


class ConfigManager:
    """설정 관리자 클래스"""
    
    def __init__(self):
        # 기본 상수 설정
        self._setup_constants()
        # 디렉토리 설정
        self._setup_directories()
        # 환경변수 로드
        self._load_environment_variables()
    
    def _setup_constants(self):
        """기본 상수들을 설정합니다."""
        # 시간대 설정
        self.TIME_PERIODS = {
            "새벽": (0, 6),    # 00:00 ~ 06:00
            "오전1": (6, 9),   # 06:00 ~ 09:00
            "오전2": (9, 12),  # 09:00 ~ 12:00
            "오후1": (12, 15), # 12:00 ~ 15:00
            "오후2": (15, 18), # 15:00 ~ 18:00
            "밤1": (18, 21),   # 18:00 ~ 21:00
            "밤2": (21, 24),   # 21:00 ~ 00:00
        }
        
        # 기본 사용자 설정
        self.DEFAULT_USER_CONFIG = {
            "time_type": "time_period",        # 'time_period' 또는 'exact'
            "outbound_periods": ["오전1", "오전2"],  # 가는 편 시간대
            "inbound_periods": ["오후1", "오후2", "밤1"],  # 오는 편 시간대
            "outbound_exact_hour": 9,          # 가는 편 시각 (시간 단위)
            "inbound_exact_hour": 15,          # 오는 편 시각 (시간 단위)
            "notification_preference": "PRICE_DROP_THRESHOLD",
            "notification_threshold_amount": 5000,
            "notification_target_price": None,
            "notification_interval": 30,  # 분 단위
            "notification_price_type": "RESTRICTED_ONLY",  # 알림 대상: RESTRICTED_ONLY, OVERALL_ONLY, BOTH
        }
        
        # 알림 조건 기본값
        self.DEFAULT_NOTIFICATION_PREFERENCE: NotificationPreferenceType = "PRICE_DROP_THRESHOLD"
        self.DEFAULT_NOTIFICATION_THRESHOLD_AMOUNT = 5000
        self.DEFAULT_NOTIFICATION_TARGET_PRICE = None
        self.DEFAULT_NOTIFICATION_PRICE_TYPE = "RESTRICTED_ONLY"
        
        # 로그 파일 크기 제한 (10MB)
        self.MAX_LOG_SIZE = 10 * 1024 * 1024
    
    def _setup_directories(self):
        """디렉토리 경로들을 설정하고 생성합니다."""
        # 테스트 환경에서는 FLIGHT_CHECKER_TEST_DATA_DIR 환경 변수를 사용하여 DATA_DIR 경로를 오버라이드할 수 있음
        data_dir_path_str = os.getenv("FLIGHT_CHECKER_TEST_DATA_DIR")
        if data_dir_path_str:
            self.DATA_DIR = Path(data_dir_path_str)
        else:
            self.DATA_DIR = Path("/data")
        
        # 디렉토리 생성
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # 로그 디렉토리
        self.LOG_DIR = self.DATA_DIR / "logs"
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_FILE = self.LOG_DIR / "flight_bot.log"
        
        # 사용자 설정 디렉토리
        self.USER_CONFIG_DIR = self.DATA_DIR / "user_configs"
        self.USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        # 공항 데이터 파일 경로 (테스트 시 패치 가능하도록 변수화)
        self.AIRPORTS_JSON_PATH = Path(__file__).resolve().parent / "data" / "airports.json"
    
    def _load_environment_variables(self):
        """환경변수들을 로드합니다."""
        # 필수 환경변수
        self.BOT_TOKEN = os.getenv("BOT_TOKEN")
        
        # Selenium 관련 설정
        self.SELENIUM_HUB_URL = os.getenv("SELENIUM_HUB_URL", "http://localhost:4444/wd/hub")
        self.USER_AGENT = os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        )
          # 제한 설정
        self.MAX_MONITORS = int(os.getenv("MAX_MONITORS", "5"))
        self.MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))
        self.FILE_WORKERS = int(os.getenv("FILE_WORKERS", "5"))
        
        # 데이터 보관 기간
        self.DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "30"))
        self.CONFIG_RETENTION_DAYS = int(os.getenv("CONFIG_RETENTION_DAYS", "7"))
        
        # 관리자 ID 목록 처리
        raw_admin = os.getenv("ADMIN_IDS", "")
        self.ADMIN_IDS = []
        if raw_admin:
            try:
                self.ADMIN_IDS = [int(x.strip()) for x in raw_admin.split(",") if x.strip()]
            except ValueError as e:
                # 초기화 시점에서는 로거가 아직 설정되지 않을 수 있으므로 print 사용
                print(f"ADMIN_IDS 환경변수 파싱 오류: {e}")
                self.ADMIN_IDS = []
        
        # 로그 레벨
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    
    def validate_environment_variables(self) -> List[str]:
        """환경변수 검증
        Returns:
            list[str]: 오류 메시지 목록
        """
        errors = []
        
        # 필수 환경변수
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN이 설정되지 않았습니다")
        
        # Selenium Hub URL 검증
        is_valid, error_msg = self._validate_url(self.SELENIUM_HUB_URL)
        if not is_valid:
            errors.append(f"SELENIUM_HUB_URL이 올바르지 않습니다: {error_msg}")
        
        # 관리자 ID 검증
        raw_admin = os.getenv("ADMIN_IDS", "")
        if raw_admin:
            for admin_id in raw_admin.split(","):
                if admin_id.strip() and not admin_id.strip().isdigit():
                    errors.append(f"ADMIN_IDS에 올바르지 않은 ID가 포함되어 있습니다: {admin_id}")
          # 숫자형 환경변수 검증
        for var_name, default, min_val in [
            ("MAX_MONITORS", "5", 1),
            ("DATA_RETENTION_DAYS", "30", 1),
            ("CONFIG_RETENTION_DAYS", "7", 1),
            ("MAX_WORKERS", "5", 1),
            ("FILE_WORKERS", "5", 1)
        ]:
            try:
                value = int(os.getenv(var_name, default))
                if value < min_val:
                    errors.append(f"{var_name}는 {min_val} 이상이어야 합니다")
            except ValueError:
                errors.append(f"{var_name}가 올바른 숫자가 아닙니다")
        
        # 로그 레벨 환경변수 검증
        if self.LOG_LEVEL not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            errors.append(f"LOG_LEVEL이 올바르지 않습니다: {self.LOG_LEVEL}. (DEBUG, INFO, WARNING, ERROR, CRITICAL 중 하나여야 합니다)")
        
        return errors
    
    def validate_env_vars(self) -> List[str]:
        """환경변수 검증 (validate_environment_variables의 별칭)
        Returns:
            list[str]: 오류 메시지 목록
        """
        return self.validate_environment_variables()
    
    def _validate_url(self, url: str) -> tuple[bool, str]:
        """URL 유효성 검사"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False, "잘못된 URL 형식입니다"
            if parsed.scheme not in ['http', 'https']:
                return False, "http 또는 https 스키마만 지원됩니다"
            return True, ""
        except Exception as e:
            return False, f"URL 파싱 오류: {e}"
    
    def setup_logging(self):
        """로깅 시스템을 설정합니다."""
        # 로그 로테이션 실행
        self.rotate_logs()
        
        # 로그 레벨 설정
        log_level = getattr(logging, self.LOG_LEVEL, logging.INFO)
        
        # 로깅 설정
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
            handlers=[
                logging.FileHandler(self.LOG_FILE, encoding="utf-8"),
                logging.StreamHandler()
            ]
        )
          # httpx 로거의 레벨을 WARNING으로 설정하여 INFO 로그 비활성화
        logging.getLogger("httpx").setLevel(logging.WARNING)
    
    def rotate_logs(self):
        """로그 파일 로테이션"""
        if not self.LOG_FILE.exists() or self.LOG_FILE.stat().st_size < self.MAX_LOG_SIZE:
            return
        
        for i in range(4, 0, -1):
            old = self.LOG_FILE.with_suffix(f'.log.{i}')
            new = self.LOG_FILE.with_suffix(f'.log.{i+1}')
            if old.exists():
                old.rename(new)
        if self.LOG_FILE.exists():
            self.LOG_FILE.rename(self.LOG_FILE.with_suffix('.log.1'))
    
    @contextlib.contextmanager
    def file_lock(self, file_path: Path):
        """파일 잠금 컨텍스트 매니저 (크로스 플랫폼)"""
        lock_file = file_path.with_suffix(file_path.suffix + '.lock')
        try:
            with open(lock_file, 'w') as f:
                if platform.system() == 'Windows':
                    # Windows에서는 msvcrt 사용
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    except:
                        pass  # 잠금 실패 시 무시 (단순화)
                else:
                    # Unix/Linux에서는 fcntl 사용
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                yield
        finally:
            try:
                lock_file.unlink(missing_ok=True)
            except:
                pass
    
    def save_json_data(self, file_path: Path, data: dict):
        """JSON 데이터를 파일 잠금과 함께 저장"""
        with self.file_lock(file_path):
            file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    def load_json_data(self, file_path: Path) -> dict:
        """JSON 데이터를 파일 잠금과 함께 로드"""
        with self.file_lock(file_path):
            return json.loads(file_path.read_text(encoding='utf-8'))
    
    def get_user_config(self, user_id: int) -> dict:
        """사용자 설정을 로드하거나 기본값을 생성하여 반환합니다.
        
        설정 파일이 존재하면 로드하고, last_activity를 현재 시간으로 갱신 후 저장합니다.
        파일이 없거나 오류 발생 시 기본 설정을 생성하고 저장합니다.
        """
        config_file = self.USER_CONFIG_DIR / f"config_{user_id}.json"
        
        try:
            if config_file.exists():
                with self.file_lock(config_file):
                    data = json.loads(config_file.read_text(encoding='utf-8'))
                    # 마지막 활동 시간 업데이트
                    data['last_activity'] = self.format_datetime(datetime.now())
                    # 변경된 내용을 다시 파일에 씀
                    config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                    return data
        except Exception as e:
            # 로거가 아직 초기화되지 않았을 수 있으므로 조건부 로깅
            logger = logging.getLogger(__name__)
            logger.error(f"사용자 설정 로드 중 오류 (ID: {user_id}, 파일: {config_file}): {e}")
        
        # 설정 파일이 없거나 로드 중 오류 발생 시 기본값으로 생성 및 저장
        logger = logging.getLogger(__name__)
        logger.info(f"기본 사용자 설정 생성 (ID: {user_id}, 파일: {config_file})")
        default_config = self.DEFAULT_USER_CONFIG.copy()
        default_config['created_at'] = self.format_datetime(datetime.now())
        default_config['last_activity'] = self.format_datetime(datetime.now())
        
        try:
            # save_user_config 함수를 사용하지 않고 직접 저장 (순환 호출 방지 및 로직 명확화)
            with self.file_lock(config_file):
                config_file.write_text(json.dumps(default_config, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e_save:
            logger.error(f"기본 사용자 설정 저장 실패 (ID: {user_id}, 파일: {config_file}): {e_save}")
            # 저장 실패 시 메모리상의 기본 설정이라도 반환
        
        return default_config
    
    def save_user_config(self, user_id: int, config: dict):
        """사용자 설정을 저장합니다.
        
        last_activity와 created_at (없는 경우)을 현재 시간으로 설정 후 저장합니다.
        """
        config_file = self.USER_CONFIG_DIR / f"config_{user_id}.json"
        config['last_activity'] = self.format_datetime(datetime.now())
        if 'created_at' not in config or not config['created_at']:
            config['created_at'] = self.format_datetime(datetime.now())
        
        self.save_json_data(config_file, config)  # 파일 잠금과 함께 저장
    
    def format_datetime(self, dt: datetime) -> str:
        """datetime을 KST 문자열로 포맷팅"""
        from zoneinfo import ZoneInfo
        KST = ZoneInfo("Asia/Seoul")
        return dt.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')
    
    def format_time_range(self, config: dict, direction: str) -> str:
        """시간 설정을 문자열로 변환합니다."""
        if config['time_type'] == 'time_period':
            periods = config[f'{direction}_periods']
            period_ranges = [self.TIME_PERIODS[p] for p in periods]
            start_hours = [start for start, _ in period_ranges]
            end_hours = [end for _, end in period_ranges]
            period_str = ", ".join(periods)
            
            if direction == 'outbound':
                return f"{period_str} ({min(start_hours):02d}:00-{max(end_hours):02d}:00)"
            else:
                # 오는 편은 선택한 시간대들을 모두 표시
                time_ranges = [f"{start:02d}:00-{end:02d}:00" for start, end in period_ranges]
                return f"{period_str} ({' / '.join(time_ranges)})"
        else:  # exact
            hour = config[f'{direction}_exact_hour']
            direction_str = "이전 출발" if direction == 'outbound' else "이후 출발"
            return f"{hour:02d}:00 {direction_str}"
    
    def format_notification_setting(self, config: dict) -> str:
        """알림 설정을 문자열로 변환합니다."""
        preference = config.get("notification_preference", self.DEFAULT_NOTIFICATION_PREFERENCE)
        
        if preference == "PRICE_DROP_THRESHOLD":
            threshold = config.get("notification_threshold_amount", self.DEFAULT_NOTIFICATION_THRESHOLD_AMOUNT)
            return f"기본 ({threshold:,}원 이상 하락 시)"
        elif preference == "PRICE_DROP_ANY":
            return "하락 시 (금액 무관)"
        elif preference == "ANY_PRICE_CHANGE":
            return "변동 시 (상승/하락 모두)"
        elif preference == "TARGET_PRICE_REACHED":
            target_price = config.get("notification_target_price")
            if target_price:
                return f"목표가 ({target_price:,}원 이하)"
            else:
                return "목표가 (설정되지 않음)"
        elif preference == "HISTORICAL_LOW_UPDATED":
            return "역대최저가 갱신 시"
        else:
            return f"알 수 없음 ({preference})"
    
    def format_notification_price_type(self, config: dict) -> str:
        """알림 가격 타입을 문자열로 변환합니다."""
        price_type = config.get("notification_price_type", self.DEFAULT_NOTIFICATION_PRICE_TYPE)
        
        if price_type == "RESTRICTED_ONLY":
            return "시간 제한 적용 최저가만"
        elif price_type == "OVERALL_ONLY":
            return "전체 최저가만"
        elif price_type == "BOTH":
            return "시간 제한 적용 + 전체 최저가"
        else:
            return f"알 수 없음 ({price_type})"
    
    def get_time_range(self, config: dict, direction: str) -> tuple:
        """시간 범위를 반환합니다.
        
        Args:
            config: 사용자 설정
            direction: 'outbound' 또는 'inbound'
            
        Returns:
            tuple: 시작 시각과 종료 시각, 또는 (None, None)
        """
        from datetime import time
        
        if config['time_type'] == 'time_period':
            periods = config[f'{direction}_periods']
            period_ranges = [self.TIME_PERIODS[p] for p in periods]
            
            if direction == 'outbound':
                # 가는 편: 선택한 시간대들의 각각의 범위를 모두 체크
                return None, None  # 시간대는 개별 체크하도록 None 반환
            else:
                # 오는 편: 선택한 시간대들의 각각의 범위를 모두 체크
                return None, None  # 시간대는 개별 체크하도록 None 반환
        else:  # exact
            hour = config[f'{direction}_exact_hour']
            if direction == 'outbound':
                # 가는 편: 지정 시각 이전 출발
                return time(0, 0), time(hour, 0)
            else:
                # 오는 편: 지정 시각 이후 출발
                return time(hour, 0), time(23, 59)


# 전역 ConfigManager 인스턴스
config_manager = ConfigManager()