#!/usr/bin/env python3
"""
텔레그램 봇으로 30분마다 항공권 최저가 조회 및 알림 기능 제공
환경변수 설정 (필수):
- BOT_TOKEN         : Telegram 봇 토큰
- SELENIUM_HUB_URL  : Selenium Hub 주소 (기본: http://localhost:4444/wd/hub)
- ADMIN_IDS         : 관리자 ID 목록 (쉼표 구분)
- USER_AGENT        : (선택) Selenium 헤드리스 브라우저용 User-Agent
- MAX_MONITORS      : (선택) 사용자당 최대 모니터링 개수 (기본 3)
- DATA_RETENTION_DAYS: (선택) 모니터링 데이터 보관 기간 (일, 기본 30)
- CONFIG_RETENTION_DAYS: (선택) 사용자 설정 파일 보관 기간 (일, 기본 7)
"""
import os
import re
import json
import time as time_module
import logging
import asyncio
import fcntl
import contextlib
from pathlib import Path
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from collections import defaultdict
from urllib.parse import urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ConversationHandler,
    ContextTypes, filters, JobQueue,
    CallbackQueryHandler
)
from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sys

# --- 설정 및 초기화 ---
DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "flight_bot.log"

# 사용자 설정 디렉토리
USER_CONFIG_DIR = DATA_DIR / "user_configs"
USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# 시간대 설정
TIME_PERIODS = {
    "새벽": (0, 6),    # 00:00 ~ 06:00
    "오전1": (6, 9),   # 06:00 ~ 09:00
    "오전2": (9, 12),  # 09:00 ~ 12:00
    "오후1": (12, 15), # 12:00 ~ 15:00
    "오후2": (15, 18), # 15:00 ~ 18:00
    "밤1": (18, 21),   # 18:00 ~ 21:00
    "밤2": (21, 24),   # 21:00 ~ 00:00
}

# 기본 설정값
DEFAULT_USER_CONFIG = {
    "time_type": "time_period",        # 'time_period' 또는 'exact'
    "outbound_periods": ["오전1", "오전2"],  # 가는 편 시간대
    "inbound_periods": ["오후1", "오후2", "밤1"],  # 오는 편 시간대
    "outbound_exact_hour": 9,          # 가는 편 시각 (시간 단위)
    "inbound_exact_hour": 15,          # 오는 편 시각 (시간 단위)
    "last_activity": None,             # 마지막 활동 시간
    "created_at": None                 # 설정 생성 시간
}

def get_user_config(user_id: int) -> dict:
    """사용자 설정을 가져옵니다."""
    config_file = USER_CONFIG_DIR / f"config_{user_id}.json"
    if config_file.exists():
        try:
            with file_lock(config_file):
                data = json.loads(config_file.read_text(encoding='utf-8'))
                # 마지막 활동 시간 업데이트
                data['last_activity'] = format_datetime(datetime.now())
                config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                return data
        except Exception as e:
            logger.error(f"사용자 설정 로드 중 오류: {e}")
    
    # 설정 파일이 없으면 기본값으로 생성
    default_config = DEFAULT_USER_CONFIG.copy()
    default_config['created_at'] = format_datetime(datetime.now())
    default_config['last_activity'] = format_datetime(datetime.now())
    save_user_config(user_id, default_config)
    return default_config

def save_user_config(user_id: int, config: dict):
    """사용자 설정을 저장합니다."""
    config_file = USER_CONFIG_DIR / f"config_{user_id}.json"
    with file_lock(config_file):
        config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')

def get_time_range(config: dict, direction: str) -> tuple[time, time]:
    """시간 범위를 반환합니다.
    
    Args:
        config: 사용자 설정
        direction: 'outbound' 또는 'inbound'
        
    Returns:
        tuple[time, time]: 시작 시각과 종료 시각
    """
    if config['time_type'] == 'time_period':
        periods = config[f'{direction}_periods']
        period_ranges = [TIME_PERIODS[p] for p in periods]
        
        if direction == 'outbound':
            # 가는 편: 선택한 시간대들의 각각의 범위를 모두 체크
            return None, None  # 시간대는 개별 체크하도록 None 반환
        else:
            # 오는 편: 선택한 시간대들의 각각의 범위를 모두 체크
            return None, None  # 시간대는 개별 체크하도록 None 반환
    else:  # exact
        hour = config[f'{direction}_exact_hour']
        if direction == 'outbound':
            # 가는 편은 "이전"이므로 정확한 시각이 끝 시각
            return time(hour=0, minute=0), time(hour=hour, minute=0)
        else:
            # 오는 편은 "이후"이므로 정확한 시각이 시작 시각
            return time(hour=hour, minute=0), time(hour=23, minute=59)

def format_time_range(config: dict, direction: str) -> str:
    """시간 설정을 문자열로 변환합니다."""
    if config['time_type'] == 'time_period':
        periods = config[f'{direction}_periods']
        period_ranges = [TIME_PERIODS[p] for p in periods]
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
        return f"{hour:02d}:00 {'이전' if direction == 'outbound' else '이후'}"

async def settings_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """사용자 설정 확인 및 변경"""
    user_id = update.effective_user.id
    config = get_user_config(user_id)
    
    msg_lines = [
        "⚙️ *시간 제한 설정*",
        "",
        "*현재 설정*",
        f"• 가는 편: {format_time_range(config, 'outbound')}",
        f"• 오는 편: {format_time_range(config, 'inbound')}",
        "",
        "*설정 방법*",
        "1️⃣ *시간대로 설정* (해당 시간대의 항공편만 검색)",
        "• 가는 편: `/set 가는편 시간대 오전1 오전2`",
        "• 오는 편: `/set 오는편 시간대 오후1 오후2 밤1`",
        "",
        "2️⃣ *특정 시각으로 설정*",
        "• 가는 편: `/set 가는편 시각 9` (09:00 이전 출발)",
        "• 오는 편: `/set 오는편 시각 15` (15:00 이후 출발)",
        "",
        "*시간대 구분*",
        "• 새벽 (00-06), 오전1 (06-09)",
        "• 오전2 (09-12), 오후1 (12-15)",
        "• 오후2 (15-18), 밤1 (18-21)",
        "• 밤2 (21-24)"
    ]
    
    # 관리자 여부에 따라 다른 키보드 표시
    keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else get_base_keyboard()
    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def set_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """설정 변경"""
    user_id = update.effective_user.id
    args = update.message.text.strip().split()
    
    if len(args) < 4:
        await update.message.reply_text(
            "❗ 올바른 형식으로 입력해주세요.\n"
            "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
        )
        return
    
    _, direction, set_type, *values = args
    
    if direction not in ["가는편", "오는편"]:
        await update.message.reply_text("❗ '가는편' 또는 '오는편'만 설정 가능합니다.")
        return
    
    direction = "outbound" if direction == "가는편" else "inbound"
    config = get_user_config(user_id)
    
    if set_type == "시각":
        if len(values) != 1 or not values[0].isdigit():
            await update.message.reply_text("❗ 시각은 0-23 사이의 숫자로 입력해주세요.")
            return
            
        hour = int(values[0])
        if hour < 0 or hour > 23:
            await update.message.reply_text("❗ 시각은 0-23 사이의 숫자로 입력해주세요.")
            return
            
        config['time_type'] = 'exact'
        config[f'{direction}_exact_hour'] = hour
        
    elif set_type == "시간대":
        if not values:
            await update.message.reply_text("❗ 하나 이상의 시간대를 선택해주세요.")
            return
            
        invalid_periods = [p for p in values if p not in TIME_PERIODS]
        if invalid_periods:
            await update.message.reply_text(
                f"❗ 올바르지 않은 시간대: {', '.join(invalid_periods)}\n"
                "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
            )
            return
            
        config['time_type'] = 'time_period'
        config[f'{direction}_periods'] = values
        
    else:
        await update.message.reply_text(
            "❗ '시각' 또는 '시간대'로만 설정 가능합니다.\n"
            "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
        )
        return
    
    save_user_config(user_id, config)
    await update.message.reply_text(
        f"✅ {direction=='outbound'and'가는 편'or'오는 편'} 설정이 변경되었습니다:\n"
        f"{format_time_range(config, direction)}"
    )

# 로그 파일 크기 제한 (10MB)
MAX_LOG_SIZE = 10 * 1024 * 1024

def rotate_logs():
    """로그 파일 로테이션"""
    if not LOG_FILE.exists() or LOG_FILE.stat().st_size < MAX_LOG_SIZE:
        return
    
    for i in range(4, 0, -1):
        old = LOG_FILE.with_suffix(f'.log.{i}')
        new = LOG_FILE.with_suffix(f'.log.{i+1}')
        if old.exists():
            old.rename(new)
    if LOG_FILE.exists():
        LOG_FILE.rename(LOG_FILE.with_suffix('.log.1'))

rotate_logs()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("환경변수 BOT_TOKEN이 설정되어 있지 않습니다.")
    raise RuntimeError("BOT_TOKEN이 필요합니다.")

SELENIUM_HUB_URL = os.getenv("SELENIUM_HUB_URL", "http://localhost:4444/wd/hub")
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
# 사용자당 최대 모니터링 개수
MAX_MONITORS = int(os.getenv("MAX_MONITORS", "3"))

raw_admin = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set(int(p.strip()) for p in raw_admin.split(",") if p.strip().isdigit())

KST = ZoneInfo("Asia/Seoul")
SETTING = 1

# 파일 패턴
PATTERN = re.compile(
    r"price_(?P<uid>\d+)_(?P<dep>[A-Z]{3})_(?P<arr>[A-Z]{3})_(?P<dd>\d{8})_(?P<rd>\d{8})\.json"
)

def format_datetime(dt: datetime) -> str:
    return dt.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')

def setup_selenium_driver():
    """Selenium WebDriver 설정"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={USER_AGENT}")
    return webdriver.Remote(
        command_executor=SELENIUM_HUB_URL,
        options=options
    )

def parse_flight_info(text: str, depart: str, arrive: str) -> tuple[str, str, str, str, int] | None:
    """항공편 정보 파싱
    Returns:
        tuple[str, str, str, str, int] | None: (출발시각, 도착시각, 귀국출발시각, 귀국도착시각, 가격)
    """
    # 가는 편: 출발지에서 도착지로 가는 항공편
    m_dep = re.search(rf'(\d{{2}}:\d{{2}}){depart}\s+(\d{{2}}:\d{{2}}){arrive}', text, re.IGNORECASE)
    if not m_dep:
        return None
        
    # 오는 편: 도착지에서 출발지로 오는 항공편
    m_ret = re.search(rf'(\d{{2}}:\d{{2}}){arrive}\s+(\d{{2}}:\d{{2}}){depart}', text, re.IGNORECASE)
    if not m_ret:
        return None
        
    # 가격 정보
    m_price = re.search(r'왕복\s*([\d,]+)원', text)
    if not m_price:
        return None
        
    price = int(m_price.group(1).replace(",", ""))
    return (
        m_dep.group(1),  # 출발시각
        m_dep.group(2),  # 도착시각
        m_ret.group(1),  # 귀국출발시각
        m_ret.group(2),  # 귀국도착시각
        price           # 가격
    )

def check_time_restrictions(dep_time: str, ret_time: str, config: dict) -> bool:
    """시간 제한 조건 체크
    Returns:
        bool: 시간 제한 조건 만족 여부
    """
    dep_t = datetime.strptime(dep_time, "%H:%M").time()
    ret_t = datetime.strptime(ret_time, "%H:%M").time()
    
    if config['time_type'] == 'time_period':
        # 시간대 설정: 선택된 시간대 중 하나라도 포함되면 유효
        outbound_periods = config['outbound_periods']
        inbound_periods = config['inbound_periods']
        
        # 가는 편: 선택된 시간대 중 하나라도 포함되면 유효
        is_valid_outbound = any(
            period_start <= dep_t.hour < period_end
            for period in outbound_periods
            for period_start, period_end in [TIME_PERIODS[period]]
        )
        if not is_valid_outbound:
            logger.debug(f"가는 편 시간대 미매칭: {dep_t}는 선택된 시간대 {outbound_periods}에 포함되지 않음")
            return False
            
        # 오는 편: 선택된 시간대 중 하나라도 포함되면 유효
        is_valid_inbound = any(
            period_start <= ret_t.hour < period_end
            for period in inbound_periods
            for period_start, period_end in [TIME_PERIODS[period]]
        )
        if not is_valid_inbound:
            logger.debug(f"오는 편 시간대 미매칭: {ret_t}는 선택된 시간대 {inbound_periods}에 포함되지 않음")
            return False
            
    else:  # exact
        # 시각 설정: 가는 편은 설정 시각 이전, 오는 편은 설정 시각 이후
        outbound_limit = time(hour=config['outbound_exact_hour'], minute=0)
        if dep_t > outbound_limit:
            logger.debug(f"가는 편 시각 미매칭: {dep_t} > {outbound_limit}")
            return False
            
        inbound_limit = time(hour=config['inbound_exact_hour'], minute=0)
        if ret_t < inbound_limit:
            logger.debug(f"오는 편 시각 미매칭: {ret_t} < {inbound_limit}")
            return False
            
    return True

def fetch_prices(depart: str, arrive: str, d_date: str, r_date: str, max_retries=3, user_id=None):
    """항공권 가격 조회"""
    logger.info(f"fetch_prices 호출: {depart}->{arrive} {d_date}~{r_date}")
    url = (
        f"https://flight.naver.com/flights/international/"
        f"{depart}-{arrive}-{d_date}/{arrive}-{depart}-{r_date}?adult=1&fareType=Y"
    )
    
    # 사용자 설정 가져오기
    config = get_user_config(user_id) if user_id else DEFAULT_USER_CONFIG.copy()
    
    last_error = None
    for attempt in range(max_retries):
        try:
            driver = setup_selenium_driver()
            
            overall_price = None
            overall_info = ""
            restricted_price = None
            restricted_info = ""
            
            try:
                driver.get(url)
                logger.debug("페이지 로드 완료, 필터 대기 중...")
                WebDriverWait(driver, 40).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '[class^="inlineFilter_FilterWrapper__"]')
                    )
                )
                time_module.sleep(5)
                items = driver.find_elements(By.XPATH, '//*[@id="international-content"]/div/div[3]/div')
                logger.debug(f"크롤링 항목 개수: {len(items)}")
                
                if not items:
                    raise Exception("NO_ITEMS")
                    
                found_any_price = False
                for item in items:
                    text = item.text
                    logger.debug(f"항공권 정보 텍스트: {text}")
                    
                    if "경유" in text:
                        logger.debug("경유 항공편 제외")
                        continue
                        
                    # 항공편 정보 파싱
                    flight_info = parse_flight_info(text, depart, arrive)
                    if not flight_info:
                        continue
                        
                    dep_departure, dep_arrival, ret_departure, ret_arrival, price = flight_info
                    found_any_price = True
                    
                    # 전체 최저가 갱신
                    if overall_price is None or price < overall_price:
                        overall_price = price
                        overall_info = (
                            f"가는 편: {dep_departure} → {dep_arrival}\n"
                            f"오는 편: {ret_departure} → {ret_arrival}\n"
                            f"왕복 가격: {price:,}원"
                        )
                        logger.debug(f"전체 최저가 갱신: {price:,}원")
                    
                    # 시간 제한 체크
                    if check_time_restrictions(dep_departure, ret_departure, config):
                        if restricted_price is None or price < restricted_price:
                            restricted_price = price
                            restricted_info = (
                                f"가는 편: {dep_departure} → {dep_arrival}\n"
                                f"오는 편: {ret_departure} → {ret_arrival}\n"
                                f"왕복 가격: {price:,}원"
                            )
                            logger.info(f"조건부 최저가 갱신: {price:,}원")
                
                if not found_any_price:
                    logger.warning("NO_PRICES: 매칭되는 항공권이 없음")
                    raise Exception("NO_PRICES")
                    
                return restricted_price, restricted_info, overall_price, overall_info, url
                
            finally:
                driver.quit()
                
        except Exception as ex:
            last_error = str(ex)
            logger.warning(f"fetch_prices 시도 {attempt + 1}/{max_retries} 실패: {ex}")
            if attempt == max_retries - 1:
                if "NO_PRICES" in str(ex):
                    raise Exception("조건에 맞는 항공권을 찾을 수 없습니다")
                elif "NO_ITEMS" in str(ex):
                    raise Exception("항공권 정보를 찾을 수 없습니다")
                logger.exception(f"fetch_prices 최종 실패: {ex}")
                raise Exception(f"항공권 조회 중 오류가 발생했습니다: {ex}")
            time_module.sleep(5 * (attempt + 1))  # 점진적으로 대기 시간 증가
    
    return None, "조회 실패", None, "조회 실패", url

# 도움말 텍스트
async def help_text() -> str:
    admin_help = ""
    if ADMIN_IDS:
        admin_help = (
            "\n\n👑 *관리자 명령어*\n"
            "• /allstatus - 전체 모니터링 현황\n"
            "• /allcancel - 전체 모니터링 취소"
        )
    
    return (
        "✈️ *항공권 최저가 모니터링 봇*\n"
        "\n"
        "📝 *기본 명령어*\n"
        "• /monitor - 새로운 모니터링 시작\n"
        "• /status - 모니터링 현황 확인\n"
        "• /cancel - 모니터링 취소\n"
        "\n"
        "⚙️ *설정 명령어*\n"
        "• /settings - 시간 제한 설정\n"
        "• /airport - 공항 코드 목록"
        + admin_help
    )

def get_base_keyboard() -> ReplyKeyboardMarkup:
    """기본 키보드 버튼 생성"""
    keyboard = [
        [KeyboardButton("/monitor"), KeyboardButton("/status")],
        [KeyboardButton("/settings"), KeyboardButton("/airport")],
        [KeyboardButton("/cancel"), KeyboardButton("/help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """관리자용 키보드 버튼 생성"""
    keyboard = [
        [KeyboardButton("/monitor"), KeyboardButton("/status")],
        [KeyboardButton("/settings"), KeyboardButton("/airport")],
        [KeyboardButton("/cancel"), KeyboardButton("/help")],
        [KeyboardButton("/allstatus"), KeyboardButton("/allcancel")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"사용자 {update.effective_user.id} 요청: /start")
    # 관리자 여부에 따라 다른 키보드 표시
    keyboard = get_admin_keyboard() if update.effective_user.id in ADMIN_IDS else get_base_keyboard()
    await update.message.reply_text(
        await help_text(),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"사용자 {update.effective_user.id} 요청: /help")
    # 관리자 여부에 따라 다른 키보드 표시
    keyboard = get_admin_keyboard() if update.effective_user.id in ADMIN_IDS else get_base_keyboard()
    await update.message.reply_text(
        await help_text(),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

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

def validate_env_vars() -> list[str]:
    """환경변수 검증
    Returns:
        list[str]: 오류 메시지 목록
    """
    errors = []
    
    # 필수 환경변수
    if not os.getenv("BOT_TOKEN"):
        errors.append("BOT_TOKEN이 설정되지 않았습니다")
        
    # Selenium Hub URL 검증
    selenium_url = os.getenv("SELENIUM_HUB_URL", "http://localhost:4444/wd/hub")
    is_valid, error_msg = validate_url(selenium_url)
    if not is_valid:
        errors.append(f"SELENIUM_HUB_URL이 올바르지 않습니다: {error_msg}")
        
    # 관리자 ID 검증
    admin_ids = os.getenv("ADMIN_IDS", "")
    if admin_ids:
        for admin_id in admin_ids.split(","):
            if admin_id.strip() and not admin_id.strip().isdigit():
                errors.append(f"ADMIN_IDS에 올바르지 않은 ID가 포함되어 있습니다: {admin_id}")
        
    # 숫자형 환경변수 검증
    for var_name, default, min_val in [
        ("MAX_MONITORS", "3", 1),
        ("DATA_RETENTION_DAYS", "30", 1),
        ("CONFIG_RETENTION_DAYS", "7", 1)
    ]:
        try:
            value = int(os.getenv(var_name, default))
            if value < min_val:
                errors.append(f"{var_name}는 {min_val} 이상이어야 합니다")
        except ValueError:
            errors.append(f"{var_name}가 올바른 숫자가 아닙니다")
        
    return errors

# 명령어 속도 제한
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
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not rate_limiter.is_allowed(user_id):
            await update.message.reply_text(
                "❗ 너무 많은 명령어를 실행했습니다. 잠시 후 다시 시도해주세요."
            )
            return
            
        return await func(update, context)
    return wrapper

@rate_limit
async def monitor_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"사용자 {update.effective_user.id} 요청: /monitor")
    msg_lines = [
        "✈️ *항공권 모니터링 설정*",
        "",
        "출발공항 도착공항 가는날짜 오는날짜",
        "예시: `ICN FUK 20251025 20251027`",
        "",
        "• 공항코드: 3자리 영문",
        "• 날짜: YYYYMMDD"
    ]
    # 모니터링 설정 시에는 키보드 숨기기
    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return SETTING

# 유효 날짜 체크
from datetime import datetime as _dt

def valid_date(d: str) -> tuple[bool, str]:
    """날짜 유효성 검사
    Returns:
        (bool, str): (유효성 여부, 오류 메시지)
    """
    try:
        date = _dt.strptime(d, "%Y%m%d")
        now = _dt.now()
        
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

# 공항 코드 유효성 검사
def load_airports():
    """공항 데이터 로드"""
    airports_file = DATA_DIR / "airports.json"
    if not airports_file.exists():
        logger.error("공항 데이터 파일이 없습니다: airports.json")
        raise FileNotFoundError("airports.json 파일을 찾을 수 없습니다")
        
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
    sys.exit(1)

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
    """지원하는 공항 목록을 포매팅"""
    lines = [
        "✈️ *주요 공항 코드 목록*",
        "_아래 목록은 자주 사용되는 공항의 예시이며,",
        "실제로는 더 많은 공항을 검색할 수 있습니다._",
        ""
    ]
    for region_data in AIRPORTS.values():
        region_name = region_data.get('name', "")
        lines.append(f"\n*{region_name}*")
        for code, (city, airport) in region_data.get('airports', {}).items():
            lines.append(f"• `{code}`: {city} ({airport})")
    return "\n".join(lines)

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

async def monitor_setting(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().split()
    len_text = len(text)
    if len_text != 4:
        logger.warning("monitor_setting: 형식 오류")
        await update.message.reply_text(
            "❗ 형식 오류\n"
            "✅ 올바른 형식: `ICN FUK 20251025 20251027`\n"
            "- 공항코드: 3자리 영문\n"
            "- 날짜: YYYYMMDD\n\n"
            "💡 주요 공항 코드 목록은 /airport 명령으로 확인하실 수 있습니다.",
            parse_mode="Markdown"
        )
        return SETTING

    outbound_dep, outbound_arr, outbound_date, inbound_date = text
    outbound_dep = outbound_dep.upper()
    outbound_arr = outbound_arr.upper()
    
    # 공항 코드 기본 형식 검증
    for code, name in [(outbound_dep, "출발"), (outbound_arr, "도착")]:
        is_valid, msg = valid_airport(code)
        if not is_valid:
            await update.message.reply_text(f"❗ {name}공항 코드 오류: {msg}")
            return SETTING
        
    if outbound_dep == outbound_arr:
        await update.message.reply_text("❗ 출발지와 도착지가 같을 수 없습니다")
        return SETTING
    
    # 날짜 검증
    is_valid, msg = valid_date(outbound_date)
    if not is_valid:
        await update.message.reply_text(f"❗ 가는 편 날짜 오류: {msg}")
        return SETTING
        
    is_valid, msg = valid_date(inbound_date)
    if not is_valid:
        await update.message.reply_text(f"❗ 오는 편 날짜 오류: {msg}")
        return SETTING
        
    outbound_date_obj = _dt.strptime(outbound_date, "%Y%m%d")
    inbound_date_obj = _dt.strptime(inbound_date, "%Y%m%d")
    if inbound_date_obj <= outbound_date_obj:
        await update.message.reply_text("❗ 오는 편 날짜는 가는 편 날짜보다 뒤여야 합니다")
        return SETTING

    user_id = update.effective_user.id
    existing = [p for p in DATA_DIR.iterdir() if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id]
    if len(existing) >= MAX_MONITORS:
        logger.warning(f"사용자 {user_id} 최대 모니터링 초과")
        await update.message.reply_text(f"❗ 최대 {MAX_MONITORS}개까지 모니터링할 수 있습니다.")
        return ConversationHandler.END

    # 공항 정보 가져오기
    _, dep_city, dep_airport = get_airport_info(outbound_dep)
    _, arr_city, arr_airport = get_airport_info(outbound_arr)
    
    # 데이터베이스에 없는 공항의 경우 기본값 설정
    if not dep_city:
        dep_city = outbound_dep
        dep_airport = f"{outbound_dep}공항"
    if not arr_city:
        arr_city = outbound_arr
        arr_airport = f"{outbound_arr}공항"

    logger.info(f"사용자 {user_id} 설정: {outbound_dep}->{outbound_arr} {outbound_date}~{inbound_date}")
    await update.message.reply_text(
        "✅ *항공권 모니터링 시작*\n"
        f"가는 편: {dep_city} ({outbound_dep}) → {arr_city} ({outbound_arr})\n"
        f"오는 편: {arr_city} ({outbound_arr}) → {dep_city} ({outbound_dep})\n"
        f"일정: {outbound_date[:4]}/{outbound_date[4:6]}/{outbound_date[6:]} → {inbound_date[:4]}/{inbound_date[4:6]}/{inbound_date[6:]}\n\n"
        "🔍 첫 조회 중...",
        parse_mode="Markdown"
    )

    try:
        loop = asyncio.get_running_loop()
        restricted, r_info, overall, o_info, link = await loop.run_in_executor(
            None, 
            fetch_prices,
            outbound_dep,    # 출발 공항
            outbound_arr,    # 도착 공항
            outbound_date,   # 가는 날짜
            inbound_date,    # 오는 날짜
            3,              # max_retries
            user_id         # user_id
        )
        
        # 가격이 모두 None인 경우도 오류로 처리
        if restricted is None and overall is None:
            raise Exception("항공권 정보를 찾을 수 없습니다")
            
    except Exception as e:
        logger.warning(f"항공권 조회 실패: {e}")
        error_msg = str(e)
        if "항공권 정보를 찾을 수 없습니다" in error_msg:
            await update.message.reply_text(
                "❗ 지원하지 않는 공항이거나 해당 경로의 항공편이 없습니다.\n"
                "💡 주요 공항 코드 목록은 /airport 명령으로 확인하실 수 있습니다."
            )
        else:
            await update.message.reply_text(
                "❗ 항공권 조회 중 오류가 발생했습니다.\n"
                "잠시 후 다시 시도해주세요."
            )
        return SETTING

    hist_path = DATA_DIR / f"price_{user_id}_{outbound_dep}_{outbound_arr}_{outbound_date}_{inbound_date}.json"
    start_time = format_datetime(datetime.now())
    
    # 사용자 설정 가져오기
    user_config = get_user_config(user_id)
    
    hist_path.write_text(json.dumps({
        "start_time": start_time,
        "restricted": restricted or 0,
        "overall": overall or 0,
        "last_fetch": format_datetime(datetime.now()),
        "outbound_before": format_time_range(user_config, 'outbound'),
        "outbound_after": format_time_range(user_config, 'outbound'),
        "inbound_before": format_time_range(user_config, 'inbound'),
        "inbound_after": format_time_range(user_config, 'inbound')
    }), encoding="utf-8")

    job = ctx.application.job_queue.run_repeating(
        monitor_job,
        interval=timedelta(minutes=30),
        first=timedelta(seconds=0),
        name=str(hist_path),      
        data={                    
            "chat_id": user_id,
            "settings": (outbound_dep, outbound_arr, outbound_date, inbound_date),
            "hist_path": str(hist_path)
        }
    )

    monitors = ctx.application.bot_data.setdefault("monitors", {})
    monitors.setdefault(user_id, []).append({
        "settings": (outbound_dep, outbound_arr, outbound_date, inbound_date),
        "start_time": datetime.now(KST),
        "hist_path": str(hist_path),
        "job": job
    })

    logger.info(f"모니터링 시작 등록: {hist_path}")
    
    # 결과 메시지 생성
    msg_lines = [
        f"✅ *{dep_city} ↔ {arr_city} 모니터링 시작*",
        f"🛫 가는 편: {dep_airport} → {arr_airport}",
        f"🛬 오는 편: {arr_airport} → {dep_airport}",
        f"📅 {outbound_date[:4]}/{outbound_date[4:6]}/{outbound_date[6:]} → {inbound_date[:4]}/{inbound_date[4:6]}/{inbound_date[6:]}",
        "",
        "⚙️ *적용된 시간 제한*",
        f"• 가는 편: {format_time_range(user_config, 'outbound')}",
        f"• 오는 편: {format_time_range(user_config, 'inbound')}",
        "",
        "📊 *현재 최저가*"
    ]
    
    if restricted:
        msg_lines.extend([
            "🎯 *시간 제한 적용 최저가*",
            r_info,
            ""
        ])
    
    if overall:
        msg_lines.extend([
            "📌 *전체 최저가*",
            o_info
        ])
        
    msg_lines.extend([
        "",
        "ℹ️ 30분마다 자동으로 가격을 확인하며,",
        "가격이 하락하면 알림을 보내드립니다.",
        "",
        "🔗 네이버 항공권:",
        link
    ])
    
    # 모니터링 설정 완료 후 키보드 다시 표시
    keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else get_base_keyboard()
    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=keyboard
    )
    return ConversationHandler.END

async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    user_id = data['chat_id']  # chat_id를 user_id로 사용
    outbound_dep, outbound_arr, outbound_date, inbound_date = data['settings']
    hist_path = Path(data['hist_path'])
    logger.info(f"monitor_job 실행: {outbound_dep}->{outbound_arr}, 히스토리 파일: {hist_path.name}")

    state = json.loads(hist_path.read_text(encoding='utf-8'))
    old_restr = state.get("restricted", 0)
    old_overall = state.get("overall", 0)

    try:
        loop = asyncio.get_running_loop()
        restricted, r_info, overall, o_info, link = await loop.run_in_executor(
            None, 
            fetch_prices,
            outbound_dep,    # 출발 공항
            outbound_arr,    # 도착 공항
            outbound_date,   # 가는 날짜
            inbound_date,    # 오는 날짜
            3,              # max_retries
            user_id         # user_id
        )

        # 공항 정보 가져오기
        _, dep_city, _ = get_airport_info(outbound_dep)
        _, arr_city, _ = get_airport_info(outbound_arr)
        dep_city = dep_city or outbound_dep
        arr_city = arr_city or outbound_arr

        notify = False
        msg_lines = []
        
        if restricted and restricted < old_restr:
            notify = True
            msg_lines.extend([
                f"📉 *{dep_city} ↔ {arr_city} 가격 하락 알림*",
                "",
                "🎯 *시간 제한 적용 최저가*",
                f"💰 {old_restr:,}원 → *{restricted:,}원* (-{old_restr - restricted:,}원)",
                r_info
            ])
            logger.info(f"시간 제한 적용 최저가 하락: {old_restr} → {restricted}")
            
        if overall and overall < old_overall:
            notify = True
            if not msg_lines:  # 첫 번째 알림인 경우
                msg_lines.extend([
                    f"📉 *{dep_city} ↔ {arr_city} 가격 하락 알림*",
                    ""
                ])
            msg_lines.extend([
                "",
                "📌 *전체 최저가*",
                f"💰 {old_overall:,}원 → *{overall:,}원* (-{old_overall - overall:,}원)",
                o_info
            ])
            logger.info(f"전체 최저가 하락: {old_overall} → {overall}")

        if notify:
            msg_lines.extend([
                "",
                f"📅 {outbound_date[:4]}/{outbound_date[4:6]}/{outbound_date[6:]} → {inbound_date[:4]}/{inbound_date[4:6]}/{inbound_date[6:]}",
                "🔗 네이버 항공권:",
                link
            ])
            await context.bot.send_message(
                user_id,
                "\n".join(msg_lines),
                parse_mode="Markdown"
            )
            logger.info("가격 하락 알림 전송 완료")

    except Exception as ex:
        error_msg = str(ex)
        if "조건에 맞는 항공권을 찾을 수 없습니다" in error_msg:
            msg_lines = [
                f"ℹ️ *{dep_city} ↔ {arr_city} 항공권 알림*",
                "",
                "현재 설정하신 시간 조건에 맞는 항공권이 없습니다.",
                "시간 설정을 변경하시려면 /settings 명령어를 사용해주세요.",
                "",
                f"📅 {outbound_date[:4]}/{outbound_date[4:6]}/{outbound_date[6:]} → {inbound_date[:4]}/{inbound_date[4:6]}/{inbound_date[6:]}",
                "🔗 네이버 항공권:",
                link
            ]
            await context.bot.send_message(
                user_id,
                "\n".join(msg_lines),
                parse_mode="Markdown"
            )
        logger.error(f"monitor_job 실행 중 오류 발생: {ex}")

    new_state = {
        "start_time": state.get("start_time"),
        "restricted": restricted or old_restr,
        "overall": overall or old_overall,
        "last_fetch": format_datetime(datetime.now()),
        "outbound_before": format_time_range(get_user_config(user_id), 'outbound'),
        "outbound_after": format_time_range(get_user_config(user_id), 'outbound'),
        "inbound_before": format_time_range(get_user_config(user_id), 'inbound'),
        "inbound_after": format_time_range(get_user_config(user_id), 'inbound')
    }
    hist_path.write_text(json.dumps(new_state), encoding='utf-8')
    logger.debug("상태 파일 업데이트 완료")

@rate_limit
async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"사용자 {user_id} 요청: /status")
    files = sorted([
        p for p in DATA_DIR.iterdir()
        if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id
    ])
    if not files:
        await update.message.reply_text(
            "현재 실행 중인 모니터링이 없습니다.\n"
            "새로운 모니터링을 시작하려면 /monitor 명령을 사용하세요."
        )
        return

    now = datetime.now(KST)
    msg_lines = ["📋 *현재 모니터링 상태*"]

    for idx, hist in enumerate(files, start=1):
        info = PATTERN.fullmatch(hist.name).groupdict()
        data = json.loads(hist.read_text(encoding='utf-8'))
        start_dt = datetime.strptime(
            data['start_time'], '%Y-%m-%d %H:%M:%S'
        ).replace(tzinfo=KST)
        elapsed = (now - start_dt).days
        
        # 공항 정보 가져오기
        dep, arr = info['dep'], info['arr']
        _, dep_city, _ = get_airport_info(dep)
        _, arr_city, _ = get_airport_info(arr)
        dep_city = dep_city or dep  # 데이터베이스에 없는 경우 코드 사용
        arr_city = arr_city or arr
        
        dd, rd = info['dd'], info['rd']
        
        msg_lines.extend([
            "",
            f"*{idx}. {dep_city}({dep}) → {arr_city}({arr})*",
            f"📅 {dd[:4]}/{dd[4:6]}/{dd[6:]} ~ {rd[:4]}/{rd[4:6]}/{rd[6:]}",
            "💰 최저가 현황:",
            f"  • 조건부: {data['restricted']:,}원" if data['restricted'] else "  • 조건부: 없음",
            f"  • 전체: {data['overall']:,}원" if data['overall'] else "  • 전체: 없음",
            f"⏱️ 모니터링 {elapsed}일째 진행 중",
            f"🔄 마지막 조회: {data['last_fetch']}",
            f"[🔗 네이버 항공권](https://flight.naver.com/flights/international/{dep}-{arr}-{dd}/{arr}-{dep}-{rd}?adult=1&fareType=Y)"
        ])

    msg_lines.extend([
        "",
        "ℹ️ *모니터링 취소 방법*:",
        "• 특정 항공권 취소: `/cancel <번호>`",
        "• 전체 취소: `/cancel all`",
        "",
        "💡 새로운 모니터링을 시작하려면 /monitor 명령을 사용하세요."
    ])

    # status 명령어 실행 시 키보드 유지
    keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else get_base_keyboard()
    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=keyboard
    )

@rate_limit
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"사용자 {user_id} 요청: /cancel")
    
    # 모니터링 파일 찾기
    files = sorted([
        p for p in DATA_DIR.iterdir()
        if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id
    ])
    
    if not files:
        keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else get_base_keyboard()
        await update.message.reply_text(
            "현재 실행 중인 모니터링이 없습니다.\n"
            "새로운 모니터링을 시작하려면 /monitor 명령을 사용하세요.",
            reply_markup=keyboard
        )
        return

    msg_lines = ["📋 *취소할 모니터링을 선택하세요*"]
    keyboard = []

    for idx, hist in enumerate(files, start=1):
        info = PATTERN.fullmatch(hist.name).groupdict()
        data = json.loads(hist.read_text(encoding='utf-8'))
        
        # 공항 정보 가져오기
        dep, arr = info['dep'], info['arr']
        _, dep_city, _ = get_airport_info(dep)
        _, arr_city, _ = get_airport_info(arr)
        dep_city = dep_city or dep
        arr_city = arr_city or arr
        
        dd, rd = info['dd'], info['rd']
        
        # 모니터링 정보 표시
        msg_lines.extend([
            "",
            f"*{idx}. {dep_city}({dep}) → {arr_city}({arr})*",
            f"📅 {dd[:4]}/{dd[4:6]}/{dd[6:]} ~ {rd[:4]}/{rd[4:6]}/{rd[6:]}",
            "💰 최저가 현황:",
            f"  • 조건부: {data['restricted']:,}원" if data['restricted'] else "  • 조건부: 없음",
            f"  • 전체: {data['overall']:,}원" if data['overall'] else "  • 전체: 없음"
        ])
        
        # 인라인 버튼 추가
        keyboard.append([
            InlineKeyboardButton(
                f"❌ {idx}번 모니터링 취소",
                callback_data=f"cancel_{hist.name}"
            )
        ])

    # 전체 취소 버튼 추가
    keyboard.append([
        InlineKeyboardButton(
            "🗑️ 전체 모니터링 취소",
            callback_data="cancel_all"
        )
    ])

    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    logger.info(f"사용자 {user_id} 콜백: {data}")
    
    monitors = ctx.application.bot_data.get("monitors", {})
    user_mons = monitors.get(user_id, [])
    keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else get_base_keyboard()

    if data == "cancel_all":
        files = [
            p for p in DATA_DIR.iterdir()
            if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id
        ]
        if not files:
            await query.answer("취소할 모니터링이 없습니다.")
            return

        msg_lines = ["✅ 모든 모니터링이 취소되었습니다:"]
        for hist in files:
            m = PATTERN.fullmatch(hist.name)
            dep, arr = m.group("dep"), m.group("arr")
            dd, rd = m.group("dd"), m.group("rd")
            # 공항 정보 가져오기
            _, dep_city, _ = get_airport_info(dep)
            _, arr_city, _ = get_airport_info(arr)
            dep_city = dep_city or dep
            arr_city = arr_city or arr
            msg_lines.append(
                f"• {dep_city}({dep}) → {arr_city}({arr})\n"
                f"  {dd[:4]}/{dd[4:6]}/{dd[6:]} ~ {rd[:4]}/{rd[4:6]}/{rd[6:]}"
            )
            hist.unlink()
            for job in ctx.application.job_queue.get_jobs_by_name(str(hist)):
                job.schedule_removal()
        
        monitors.pop(user_id, None)
        await query.message.edit_text(
            "\n".join(msg_lines),
            parse_mode="Markdown"
        )
        await query.answer("모든 모니터링이 취소되었습니다.")
        return

    if data.startswith("cancel_"):
        target_file = data[7:]  # "cancel_" 제거
        target = DATA_DIR / target_file
        
        if not target.exists():
            await query.answer("이미 취소된 모니터링입니다.")
            return
            
        m = PATTERN.fullmatch(target_file)
        dep, arr = m.group("dep"), m.group("arr")
        dd, rd = m.group("dd"), m.group("rd")
        
        # 공항 정보 가져오기
        _, dep_city, _ = get_airport_info(dep)
        _, arr_city, _ = get_airport_info(arr)
        dep_city = dep_city or dep
        arr_city = arr_city or arr
        
        target.unlink()
        for job in ctx.application.job_queue.get_jobs_by_name(str(target)):
            job.schedule_removal()

        if user_id in monitors:
            monitors[user_id] = [m for m in user_mons if m.get('hist_path') != str(target)]
            if not monitors[user_id]:
                monitors.pop(user_id)
                
        msg_lines = [
            "✅ 다음 모니터링이 취소되었습니다:",
            f"• {dep_city}({dep}) → {arr_city}({arr})",
            f"  {dd[:4]}/{dd[4:6]}/{dd[6:]} ~ {rd[:4]}/{rd[4:6]}/{rd[6:]}"
        ]
        
        await query.message.edit_text(
            "\n".join(msg_lines),
            parse_mode="Markdown"
        )
        await query.answer("모니터링이 취소되었습니다.")

async def all_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"관리자 {user_id} 요청: /allstatus")
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    # 모든 모니터링 파일 찾기
    files = sorted(DATA_DIR.glob("price_*.json"))
    if not files:
        await update.message.reply_text("현재 등록된 모니터링이 없습니다.")
        return

    # 사용자별 모니터링 개수 집계
    user_counts = defaultdict(int)
    for hist_path in files:
        try:
            m = PATTERN.fullmatch(hist_path.name)
            if not m:
                continue
            uid = int(m.group("uid"))
            user_counts[uid] += 1
        except Exception as e:
            logger.error(f"모니터링 상태 처리 중 오류 발생: {e}")

    # 결과 메시지 생성
    total_users = len(user_counts)
    total_monitors = len(files)
    msg_lines = [
        f"📊 *전체 모니터링 현황*",
        f"• 총 사용자 수: {total_users}명",
        f"• 총 모니터링 수: {total_monitors}건",
        "",
        "📋 *사용자별 모니터링 현황*"
    ]

    # 사용자별 모니터링 개수 정렬 (개수 내림차순)
    sorted_users = sorted(user_counts.items(), key=lambda x: (-x[1], x[0]))
    for uid, count in sorted_users:
        msg_lines.append(f"• 사용자 {uid}: {count}건")

    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown"
    )

async def all_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"관리자 {user_id} 요청: /allcancel")
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    # 모든 모니터링 파일 찾기
    files = list(DATA_DIR.glob("price_*.json"))
    if not files:
        await update.message.reply_text("현재 등록된 모니터링이 없습니다.")
        return

    # 확인 버튼이 있는 인라인 키보드 생성
    keyboard = [
        [
            InlineKeyboardButton("✅ 예, 모두 취소합니다", callback_data="confirm_allcancel"),
            InlineKeyboardButton("❌ 아니오", callback_data="cancel_allcancel")
        ]
    ]

    await update.message.reply_text(
        f"⚠️ *주의*: 정말 모든 모니터링({len(files)}건)을 취소하시겠습니까?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def all_cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ 관리자 권한이 필요합니다.")
        return
        
    if query.data == "cancel_allcancel":
        await query.message.edit_text("모니터링 취소가 취소되었습니다.")
        return
        
    if query.data != "confirm_allcancel":
        return

    files = list(DATA_DIR.glob("price_*.json"))
    count = 0
    error_count = 0
    processed_users = set()

    for hist_path in files:
        try:
            m = PATTERN.fullmatch(hist_path.name)
            if not m:
                continue

            uid = int(m.group("uid"))
            processed_users.add(uid)

            try:
                hist_path.unlink()
                count += 1
            except FileNotFoundError:
                pass
            except Exception as e:
                error_count += 1
                logger.error(f"파일 삭제 중 오류 발생 ({hist_path.name}): {e}")

            for job in ctx.application.job_queue.get_jobs_by_name(str(hist_path)):
                job.schedule_removal()

        except Exception as e:
            error_count += 1
            logger.error(f"모니터링 취소 중 오류 발생: {e}")

    monitors = ctx.application.bot_data.get("monitors", {})
    for uid in processed_users:
        monitors.pop(uid, None)

    msg_parts = [f"✅ 전체 모니터링 종료: {count}건 처리됨"]
    if error_count > 0:
        msg_parts.append(f"⚠️ {error_count}건의 오류 발생")
    
    await query.message.edit_text("\n".join(msg_parts))
    logger.info(f"전체 모니터링 종료: {count}건 처리됨, {error_count}건의 오류")

async def on_startup(app):
    now = datetime.now(KST)
    monitors = app.bot_data.setdefault("monitors", {})
    logger.info("봇 시작 시 on_startup 실행")
    
    # 모든 모니터링 작업 즉시 실행
    for hist_path in DATA_DIR.glob("price_*.json"):
        try:
            m = PATTERN.fullmatch(hist_path.name)
            if not m:
                continue
                
            data = json.loads(hist_path.read_text(encoding="utf-8"))
            start_time_str = data.get("start_time")
            try:
                start_time = datetime.strptime(
                    start_time_str,
                    "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=KST)
            except Exception:
                start_time = now
                
            # 마지막 조회 시간 확인
            last_fetch_str = data.get("last_fetch")
            try:
                last_fetch = datetime.strptime(
                    last_fetch_str,
                    "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=KST)
            except Exception:
                last_fetch = start_time
                
            # 30분 이상 지났거나 마지막 조회 시간이 없는 경우 즉시 실행
            interval = timedelta(minutes=30)
            delta = now - last_fetch
            
            uid = int(m.group("uid"))
            dep, arr, dd, rd = m.group("dep"), m.group("arr"), m.group("dd"), m.group("rd")
            
            # 즉시 실행이 필요한 경우 별도의 일회성 작업 추가
            if delta >= interval:
                logger.info(f"즉시 조회 예약: {hist_path.name} (마지막 조회: {last_fetch_str}, 경과 시간: {delta.total_seconds()/60:.1f}분)")
                app.job_queue.run_once(
                    monitor_job,
                    when=0,
                    name=f"{hist_path}_immediate",
                    data={
                        "chat_id": uid,
                        "settings": (dep, arr, dd, rd),
                        "hist_path": str(hist_path)
                    }
                )
            
            # 정기 모니터링 작업 등록 (다음 실행 시간은 마지막 조회 시간 기준으로 계산)
            next_run = interval - (delta % interval)  # 다음 30분 간격까지 남은 시간
            logger.info(f"정기 모니터링 등록: {hist_path.name} (다음 실행: {next_run.total_seconds()/60:.1f}분 후)")
            
            job = app.job_queue.run_repeating(
                monitor_job,
                interval=interval,
                first=next_run,
                name=str(hist_path),
                data={
                    "chat_id": uid,
                    "settings": (dep, arr, dd, rd),
                    "hist_path": str(hist_path)
                }
            )
            
            monitors.setdefault(uid, []).append({
                "settings": (dep, arr, dd, rd),
                "start_time": start_time,
                "hist_path": str(hist_path),
                "job": job
            })
        except Exception as ex:
            logger.error(f"모니터링 복원 중 오류 발생 ({hist_path.name}): {ex}")
            try:
                hist_path.unlink()
                logger.info(f"손상된 모니터링 파일 삭제: {hist_path.name}")
            except Exception:
                pass

@contextlib.contextmanager
def file_lock(file_path):
    """파일 잠금을 위한 컨텍스트 매니저"""
    lock_path = str(file_path) + '.lock'
    with open(lock_path, 'w') as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            if os.path.exists(lock_path):
                os.unlink(lock_path)

def save_json_data(file_path: Path, data: dict):
    """스레드 세이프한 JSON 데이터 저장"""
    with file_lock(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def load_json_data(file_path: Path) -> dict:
    """스레드 세이프한 JSON 데이터 로드"""
    with file_lock(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

async def cleanup_old_data():
    """오래된 모니터링 데이터와 설정 파일 정리"""
    retention_days = int(os.getenv("DATA_RETENTION_DAYS", "30"))
    config_retention_days = int(os.getenv("CONFIG_RETENTION_DAYS", "7"))
    cutoff_date = datetime.now(KST) - timedelta(days=retention_days)
    config_cutoff_date = datetime.now(KST) - timedelta(days=config_retention_days)
    
    monitor_deleted = 0
    config_deleted = 0
    
    # 오래된 모니터링 데이터 정리
    for file_path in DATA_DIR.glob("price_*.json"):
        try:
            data = load_json_data(file_path)
            start_time = datetime.strptime(
                data["start_time"],
                "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=KST)
            if start_time < cutoff_date:
                logger.info(f"오래된 데이터 삭제: {file_path.name}")
                file_path.unlink()
                monitor_deleted += 1
        except Exception as ex:
            logger.warning(f"데이터 정리 중 오류 발생: {ex}")
    
    # 오래된 설정 파일 정리
    for config_file in USER_CONFIG_DIR.glob("config_*.json"):
        try:
            with file_lock(config_file):
                data = json.loads(config_file.read_text(encoding='utf-8'))
                last_activity = datetime.strptime(
                    data.get('last_activity', data['created_at']),
                    '%Y-%m-%d %H:%M:%S'
                ).replace(tzinfo=KST)
                
                # 마지막 활동으로부터 설정된 기간이 지났고, 활성화된 모니터링이 없는 경우
                if last_activity < config_cutoff_date:
                    user_id = int(config_file.stem.split('_')[1])
                    active_monitors = [
                        p for p in DATA_DIR.glob(f"price_{user_id}_*.json")
                        if p.exists()
                    ]
                    if not active_monitors:
                        logger.info(f"비활성 사용자 설정 삭제: {config_file.name}")
                        config_file.unlink()
                        config_deleted += 1
        except Exception as ex:
            logger.warning(f"설정 파일 정리 중 오류 발생: {ex}")
            
    # 관리자에게 정리 결과 알림
    if ADMIN_IDS:
        msg = (
            "🧹 *데이터 정리 완료*\n"
            f"• 삭제된 모니터링: {monitor_deleted}건\n"
            f"• 삭제된 설정 파일: {config_deleted}건\n\n"
            f"모니터링 보관 기간: {retention_days}일\n"
            f"설정 파일 보관 기간: {config_retention_days}일"
        )
        for admin_id in ADMIN_IDS:
            try:
                await ctx.bot.send_message(
                    chat_id=admin_id,
                    text=msg,
                    parse_mode="Markdown"
                )
            except Exception as ex:
                logger.error(f"관리자({admin_id})에게 알림 전송 실패: {ex}")

async def airport_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """공항 코드 목록 보기"""
    logger.info(f"사용자 {update.effective_user.id} 요청: /airport")
    # airport 명령어 실행 시 키보드 유지
    keyboard = get_admin_keyboard() if update.effective_user.id in ADMIN_IDS else get_base_keyboard()
    await update.message.reply_text(
        format_airport_list(),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

def main():
    logger.info("메인 함수 시작: ApplicationBuilder 설정 중...")
    
    # 환경변수 검증
    errors = validate_env_vars()
    if errors:
        for error in errors:
            logger.error(error)
        return
    
    if not BOT_TOKEN:
        logger.error("환경변수 BOT_TOKEN이 설정되어 있지 않습니다.")
        return
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # 작업 디렉토리 생성
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # 핸들러 등록
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("monitor", monitor_cmd)],
        states={
            SETTING: [MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_setting)]
        },
        fallbacks=[],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("airport", airport_cmd))
    application.add_handler(CommandHandler("settings", settings_cmd))
    application.add_handler(CommandHandler("set", set_cmd))
    
    # 콜백 쿼리 핸들러 추가
    application.add_handler(CallbackQueryHandler(cancel_callback))
    application.add_handler(CallbackQueryHandler(all_cancel_callback, pattern="^(confirm|cancel)_allcancel$"))
    
    # 관리자 명령어
    if ADMIN_IDS:
        application.add_handler(CommandHandler("allstatus", all_status))
        application.add_handler(CommandHandler("allcancel", all_cancel))
    
    # 시작 시 기존 모니터링 복원
    application.job_queue.run_once(on_startup, 0)
    
    # 매일 자정에 오래된 데이터 정리
    application.job_queue.run_daily(
        lambda ctx: asyncio.create_task(cleanup_old_data()),
        time=time(hour=0, minute=0, tzinfo=KST)
    )
    
    logger.info("봇 실행 시작")
    application.run_polling()

if __name__ == "__main__":
    main()
