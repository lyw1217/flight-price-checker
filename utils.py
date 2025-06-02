#!/usr/bin/env python3
"""
항공권 가격 체커 유틸리티 함수들
"""
import json
import time as time_module
import logging
import asyncio
from pathlib import Path
from datetime import datetime, time
from zoneinfo import ZoneInfo
from collections import defaultdict
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from config_manager import config_manager

# 로거 설정
logger = logging.getLogger(__name__)

# 상수
KST = ZoneInfo("Asia/Seoul")

# 전역 인스턴스
file_executor = ThreadPoolExecutor(max_workers=config_manager.FILE_WORKERS, thread_name_prefix="file")


# ===== 데이터 처리 헬퍼 함수들 =====

async def load_json_data_async(file_path: Path) -> dict:
    """비동기 JSON 데이터 로드"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(file_executor, config_manager.load_json_data, file_path)

async def save_json_data_async(file_path: Path, data: dict):
    """비동기 JSON 데이터 저장"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(file_executor, config_manager.save_json_data, file_path, data)

async def save_user_config_async(user_id: int, config: dict):
    """비동기 사용자 설정 저장"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(file_executor, config_manager.save_user_config, user_id, config)

async def get_user_config_async(user_id: int) -> dict:
    """비동기 사용자 설정 로드. 내부적으로 동기 함수 get_user_config 호출."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(file_executor, config_manager.get_user_config, user_id)

def get_user_config(user_id: int) -> dict:
    """사용자 설정을 로드하거나 기본값을 생성하여 반환합니다."""
    return config_manager.get_user_config(user_id)

def save_user_config(user_id: int, config: dict):
    """사용자 설정을 저장합니다."""
    config_manager.save_user_config(user_id, config)


# ===== 포맷팅 함수들 =====

def get_time_range(config: dict, direction: str) -> tuple[time, time]:
    """시간 범위를 반환합니다."""
    return config_manager.get_time_range(config, direction)

def format_time_range(config: dict, direction: str) -> str:
    """시간 설정을 문자열로 변환합니다."""
    return config_manager.format_time_range(config, direction)

def format_notification_setting(config: dict) -> str:
    """알림 설정을 문자열로 변환합니다."""
    return config_manager.format_notification_setting(config)

def format_notification_price_type(config: dict) -> str:
    """알림 가격 타입을 문자열로 변환합니다."""
    return config_manager.format_notification_price_type(config)

# ===== 검증 함수들 =====

def validate_url(url: str) -> tuple[bool, str]:
    """URL 유효성 검사
    Returns:
        tuple[bool, str]: (유효성 여부, 오류 메시지)
    """
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False, "URL 형식이 올바르지 않습니다"
        if result.scheme not in ["http", "https"]:
            return False, "URL은 http 또는 https로 시작해야 합니다"
        return True, ""
    except Exception:
        return False, "URL 파싱 중 오류가 발생했습니다"

def valid_date(d: str) -> tuple[bool, str]:
    """날짜 유효성 검사
    Returns:
        (bool, str): (유효성 여부, 오류 메시지)
    """
    try:
        date = datetime.strptime(d, "%Y%m%d")
        now = datetime.now()
        
        # 과거 날짜 체크
        if date.date() < now.date():
            return False, "과거 날짜는 선택할 수 없습니다"
            
        # 1년 이상 미래 체크
        max_future = now.replace(year=now.year + 1)
        if date > max_future:
            return False, "1년 이상 미래의 날짜는 선택할 수 없습니다"
            
        return True, ""
    except ValueError:
        return False, "올바른 날짜 형식이 아닙니다 (YYYYMMDD)"

def valid_airport(code: str) -> tuple[bool, str]:
    """공항 코드 유효성 검사 (기본 형식만 검사)
    Returns:
        (bool, str): (유효성 여부, 오류 메시지)
    """
    if not code.isalpha() or len(code) != 3:
        return False, "공항 코드는 3자리 영문이어야 합니다"
    
    code = code.upper()
    is_valid, city, airport = get_airport_info(code)
    
    # 알려진 공항이 아니더라도 형식이 맞으면 일단 허용
    # 실제 유효성은 항공권 조회 시 확인됨
    return True, ""


# ===== 공항 관련 함수들 =====

def load_airports():
    """공항 데이터 로드"""
    airports_file = config_manager.AIRPORTS_JSON_PATH
    if not airports_file.exists():
        logger.error(f"공항 데이터 파일이 없습니다: {airports_file.name}")
        raise FileNotFoundError(f"{airports_file.name} 파일을 찾을 수 없습니다")
        
    try:
        with open(airports_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"공항 데이터 로드 중 오류 발생: {e}")
        raise

# 공항 데이터 로드
try:
    AIRPORTS = load_airports()
except Exception as e:
    logger.error(f"공항 데이터 초기화 실패: {e}")
    AIRPORTS = {}

def get_airport_info(code: str) -> tuple[bool, str, str]:
    """공항 코드의 유효성과 정보를 반환
    Returns:
        tuple[bool, str, str]: (유효성 여부, 도시명, 공항명)
    """
    code = code.upper()
    for region_data in AIRPORTS.values():
        airports = region_data.get('airports', {})
        if code in airports:
            city, airport = airports[code]
            return True, city, airport
    return False, "", ""

def format_airport_list() -> str:
    """자주 가는 공항 목록을 포매팅"""
    lines = [
        "✈️ *자주 찾는 공항 코드*",
        "",
        "*한국*",
        "• `ICN`: 인천 (서울/인천국제공항)",
        "• `GMP`: 김포 (서울/김포국제공항)",
        "• `PUS`: 부산 (부산/김해국제공항)",
        "• `CJU`: 제주 (제주국제공항)",
        "",
        "*일본*",
        "• `NRT`: 나리타 (도쿄/나리타국제공항)",
        "• `HND`: 하네다 (도쿄/하네다국제공항)",
        "• `KIX`: 간사이 (오사카/간사이국제공항)",
        "• `FUK`: 후쿠오카 (후쿠오카국제공항)",
        "",
        "*동남아시아*",
        "• `BKK`: 방콕 (수완나품국제공항)",
        "• `SGN`: 호치민 (떤선녓국제공항)",
        "• `MNL`: 마닐라 (니노이 아키노국제공항)",
        "• `SIN`: 싱가포르 (창이국제공항)",
        "",
        "💡 더 많은 공항 코드는 아래 링크에서 확인하실 수 있습니다:",
        "[항공정보포털시스템](https://www.airportal.go.kr/airport/airport.do)"
    ]
    return "\n".join(lines)


# ===== 속도 제한 기능 =====

class RateLimiter:
    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = defaultdict(list)
        
    def is_allowed(self, user_id: int) -> bool:
        """사용자의 명령어 실행 허용 여부 확인"""
        now = time_module.time()
        user_calls = self.calls[user_id]
        
        # 시간 창 밖의 기록 제거
        while user_calls and now - user_calls[0] > self.time_window:
            user_calls.pop(0)
            
        if len(user_calls) >= self.max_calls:
            return False
            
        user_calls.append(now)
        return True

# 속도 제한 설정 (1분에 10회)
rate_limiter = RateLimiter(max_calls=10, time_window=60)

def rate_limit(func):
    """명령어 속도 제한 데코레이터"""
    async def wrapper(update, context):
        user_id = update.effective_user.id
        
        if not rate_limiter.is_allowed(user_id):
            await update.message.reply_text(
                "❗ 너무 많은 명령어를 실행했습니다. 잠시 후 다시 시도해주세요."
            )
            return
            
        return await func(update, context)
    return wrapper


# ===== 리소스 정리 =====

def cleanup_utils_resources():
    """utils 리소스 정리"""
    logger.info("utils 리소스 정리 시작...")
    file_executor.shutdown(wait=True)
    logger.info("utils 리소스 정리 완료")
