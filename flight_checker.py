#!/usr/bin/env python3
"""
텔레그램 봇으로 30분마다 항공권 최저가 조회 및 알림 기능 제공

환경변수 설정 (필수):
- BOT_TOKEN         : Telegram 봇 토큰
- SELENIUM_HUB_URL  : Selenium Hub 주소 (기본: http://localhost:4444/wd/hub)
- ADMIN_IDS         : 관리자 ID 목록 (쉼표로 구분)
- USER_AGENT        : (선택) Selenium 헤드리스 브라우저용 User-Agent (지정하지 않으면 기본값 사용)
- MAX_MONITORS      : (선택) 사용자당 최대 모니터링 개수 (기본값: 3)
- DATA_RETENTION_DAYS: (선택) 모니터링 데이터 보관 기간 (일, 기본값: 30)
- CONFIG_RETENTION_DAYS: (선택) 사용자 설정 파일 보관 기간 (일, 기본값: 7)
- MAX_WORKERS       : (선택) Selenium 작업용 최대 동시 실행 브라우저 수 (기본값: 5)
- FILE_WORKERS      : (선택) 파일 I/O 작업용 최대 동시 작업자 수 (기본값: 5)
- LOG_LEVEL         : (선택) 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL 중 선택, 기본값: INFO)
"""
import os
import re
import json
import time as time_module
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from collections import defaultdict
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ConversationHandler,
    ContextTypes, filters, JobQueue,
    CallbackQueryHandler
)
from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.error import BadRequest, TimedOut, NetworkError
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sys
import threading
from typing import Optional, Tuple, Dict, Any, Literal # Literal 추가

# ConfigManager import
from config_manager import config_manager, NotificationPreferenceType

# TelegramBot import
from telegram_bot import TelegramBot, MessageManager, SETTING

# ConfigManager에서 설정값들을 가져옴
TIME_PERIODS = config_manager.TIME_PERIODS
DEFAULT_USER_CONFIG = config_manager.DEFAULT_USER_CONFIG
DEFAULT_NOTIFICATION_PREFERENCE = config_manager.DEFAULT_NOTIFICATION_PREFERENCE
DEFAULT_NOTIFICATION_THRESHOLD_AMOUNT = config_manager.DEFAULT_NOTIFICATION_THRESHOLD_AMOUNT
DEFAULT_NOTIFICATION_TARGET_PRICE = config_manager.DEFAULT_NOTIFICATION_TARGET_PRICE
DATA_DIR = config_manager.DATA_DIR
LOG_DIR = config_manager.LOG_DIR
LOG_FILE = config_manager.LOG_FILE
USER_CONFIG_DIR = config_manager.USER_CONFIG_DIR
AIRPORTS_JSON_PATH = config_manager.AIRPORTS_JSON_PATH
BOT_TOKEN = config_manager.BOT_TOKEN
SELENIUM_HUB_URL = config_manager.SELENIUM_HUB_URL
USER_AGENT = config_manager.USER_AGENT
DATA_RETENTION_DAYS = config_manager.DATA_RETENTION_DAYS
CONFIG_RETENTION_DAYS = config_manager.CONFIG_RETENTION_DAYS
FILE_WORKERS = config_manager.FILE_WORKERS
KST = ZoneInfo("Asia/Seoul")

# 전역 텔레그램 봇 인스턴스
telegram_bot = TelegramBot()
message_manager = telegram_bot.message_manager

# Selenium 작업 관리를 위한 전용 매니저 클래스
class SeleniumManager:
    def __init__(self, max_workers: int = 3, grid_url: str = None, user_agent: str = None):
        """
        Selenium 작업을 위한 전용 매니저
        
        Args:
            max_workers: 동시 실행할 최대 브라우저 수 (환경 변수 SELENIUM_WORKERS로 설정 가능)
            grid_url: Selenium Grid URL (환경 변수 SELENIUM_HUB_URL로 설정 가능)
            user_agent: 브라우저 User-Agent (환경 변수 USER_AGENT로 설정 가능)
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="selenium")
        self.grid_url = grid_url
        self.user_agent = user_agent
        self.active_tasks = 0
        self.lock = threading.Lock()
    
    def setup_driver(self) -> webdriver.Remote:
        """브라우저 드라이버 설정"""
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        if self.user_agent:
            options.add_argument(f'user-agent={self.user_agent}')
        
        if self.grid_url:
            # Selenium Grid 사용
            driver = webdriver.Remote(
                command_executor=self.grid_url,
                options=options
            )
        else:
            # 로컬 ChromeDriver 사용
            driver = webdriver.Chrome(options=options)
        
        return driver
    
    def _fetch_single(self, url: str, depart: str, arrive: str, config: dict) -> Tuple[Any, str, Any, str, str]:
        """단일 조회 실행 (동기 함수)"""
        with self.lock:
            self.active_tasks += 1
            task_id = self.active_tasks
        
        logger.info(f"Selenium 작업 시작 #{task_id}: {depart}->{arrive}")
        driver = None
        
        try:
            driver = self.setup_driver()
            overall_price, restricted_price = None, None
            overall_info, restricted_info = "", ""
            
            driver.get(url)
            WebDriverWait(driver, 40).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[class^="inlineFilter_FilterWrapper__"]'))
            )
            time_module.sleep(5)
            items = driver.find_elements(By.XPATH, '//*[@id="international-content"]/div/div[3]/div')
            
            if not items:
                logger.warning(f"NO_ITEMS for {url}")
                raise NoFlightDataException("항공권 정보를 찾을 수 없습니다 (NO_ITEMS)")

            found_any_price = False
            for item in items:
                text = item.text
                logger.debug(f"항공권 정보 텍스트: {text}")
                
                if "경유" in text:
                    logger.debug("경유 항공편 제외")
                    continue
                    
                flight_info = parse_flight_info(text, depart, arrive)
                if not flight_info:
                    continue
                    
                dep_departure, dep_arrival, ret_departure, ret_arrival, price = flight_info
                found_any_price = True
                
                if overall_price is None or price < overall_price:
                    overall_price = price
                    overall_info = (
                        f"가는 편: {dep_departure} → {dep_arrival}\n"
                        f"오는 편: {ret_departure} → {ret_arrival}\n"
                        f"왕복 가격: {price:,}원"
                    )
                    logger.debug(f"전체 최저가 갱신: {price:,}원")
                
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
                logger.warning(f"NO_PRICES (found_any_price=False) for {url}")
                raise NoMatchingFlightsException("조건에 맞는 항공권을 찾을 수 없습니다 (NO_PRICES_PARSED)")
            
            logger.info(f"Selenium 작업 완료 #{task_id}")
            return restricted_price, restricted_info, overall_price, overall_info, url
            
        except Exception as e:
            logger.error(f"Selenium 작업 #{task_id} 실패: {e}")
            raise
        finally:
            if driver:
                driver.quit()
            with self.lock:
                self.active_tasks -= 1

    async def fetch_prices_async(self, url: str, depart: str, arrive: str, config: dict) -> Tuple[Any, str, Any, str, str]:
        """비동기 가격 조회"""
        loop = asyncio.get_running_loop()
        
        try:
            result = await loop.run_in_executor(
                self.executor,
                self._fetch_single,
                url, depart, arrive, config
            )
            return result
        except Exception as e:
            logger.error(f"비동기 fetch_prices 실패: {e}")
            raise
    
    def shutdown(self):
        """리소스 정리"""
        logger.info("SeleniumManager 종료 중...")
        self.executor.shutdown(wait=True)

# 전역 Selenium 매니저 인스턴스 생성
selenium_manager = SeleniumManager(
    max_workers=config_manager.MAX_WORKERS,
    grid_url=config_manager.SELENIUM_HUB_URL,
    user_agent=config_manager.USER_AGENT
)

# 파일 작업용 executor
file_executor = ThreadPoolExecutor(max_workers=FILE_WORKERS, thread_name_prefix="file")

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

def get_time_range(config: dict, direction: str) -> tuple[time, time]:
    """시간 범위를 반환합니다."""
    return config_manager.get_time_range(config, direction)

def format_time_range(config: dict, direction: str) -> str:
    """시간 설정을 문자열로 변환합니다."""
    return config_manager.format_time_range(config, direction)

def format_notification_setting(config: dict) -> str:
    """알림 설정을 문자열로 변환합니다."""
    return config_manager.format_notification_setting(config)

async def settings_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """사용자 설정 확인 및 변경"""
    user_id = update.effective_user.id
    config = await get_user_config_async(user_id)
    
    msg_lines = [
        "⚙️ *시간 제한 및 알림 설정*",
        "",
        "*현재 시간 설정*",
        f"• 가는 편: {format_time_range(config, 'outbound')}",
        f"• 오는 편: {format_time_range(config, 'inbound')}",
        "",
        "*현재 알림 설정*",
        f"• 알림 조건: {format_notification_setting(config)}",
        "",
        "*현재 알림 주기 설정*",
        f"• 알림 주기: {config.get('notification_interval', 30)}분",
        "",
        "*시간 설정 방법*",
        "1️⃣ *시간대로 설정* (해당 시간대의 항공편만 검색)",
        "• 가는 편: `/set 가는편 시간대 오전1 오전2`",
        "• 오는 편: `/set 오는편 시간대 오후1 오후2 밤1`",
        "",
        "2️⃣ *특정 시각으로 설정*",
        "• 가는 편: `/set 가는편 시각 9` (09:00 이전 출발)",
        "• 오는 편: `/set 오는편 시각 15` (15:00 이후 출발)",
        "",
        "*알림 설정 방법*",
        f"• 기본: `/set 알림조건 기본` ({DEFAULT_NOTIFICATION_THRESHOLD_AMOUNT:,}원 이상 하락 시)",
        f"• 하락 시: `/set 알림조건 하락시` (금액 무관)",
        f"• 변동 시: `/set 알림조건 변동시` (상승/하락 모두)",
        f"• 목표가: `/set 알림조건 목표가 150000` (15만원 이하 시)",
        f"• 역대최저가: `/set 알림조건 역대최저가`",
        f"• 하락기준 변경: `/set 알림조건 하락기준 3000` (3천원 이상 하락 시)",
        "",
        "*알림 주기 설정 방법*",
        "• `/set 알림주기 15` (15분마다 알림)",
        "",
        "*시간대 구분*",
        "• 새벽 (00-06), 오전1 (06-09)",
        "• 오전2 (09-12), 오후1 (12-15)",
        "• 오후2 (15-18), 밤1 (18-21)",
        "• 밤2 (21-24)"    ]
      # 관리자 여부에 따라 다른 키보드 표시
    keyboard = telegram_bot.get_keyboard_for_user(user_id)
    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def set_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """설정 변경"""
    user_id = update.effective_user.id
    args = update.message.text.strip().split()
    
    if len(args) < 3: # 명령어, 설정종류, 값 (최소 3개)
        await update.message.reply_text(
            "❗ 올바른 형식으로 입력해주세요.\n"
            "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
        )
        return
    
    command, target_type, *values = args # command는 /set, target_type은 '가는편', '오는편', '알림조건' 등
    
    config = await get_user_config_async(user_id)
    action_taken_msg = ""

    if target_type in ["가는편", "오는편"]:
        if len(values) < 2: # 시각/시간대, 값 (최소 2개)
            await update.message.reply_text(
                "❗ 시간 설정 형식이 올바르지 않습니다.\n"
                "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
            )
            return

        direction_str = target_type
        set_type, *time_values = values
        direction = "outbound" if direction_str == "가는편" else "inbound"

        if set_type == "시각":
            if len(time_values) != 1 or not time_values[0].isdigit():
                await update.message.reply_text("❗ 시각은 0-23 사이의 숫자로 입력해주세요.")
                return
            
            hour = int(time_values[0])
            if hour < 0 or hour > 23:
                await update.message.reply_text("❗ 시각은 0-23 사이의 숫자로 입력해주세요.")
                return
            
            config['time_type'] = 'exact'
            config[f'{direction}_exact_hour'] = hour
            action_taken_msg = f"✅ {direction_str} 시간 설정이 변경되었습니다: {format_time_range(config, direction)}"
            
        elif set_type == "시간대":
            if not time_values:
                await update.message.reply_text("❗ 하나 이상의 시간대를 선택해주세요.")
                return
            
            invalid_periods = [p for p in time_values if p not in TIME_PERIODS]
            if invalid_periods:
                await update.message.reply_text(
                    f"❗ 올바르지 않은 시간대: {', '.join(invalid_periods)}\n"
                    "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
                )
                return
            
            config['time_type'] = 'time_period'
            config[f'{direction}_periods'] = time_values
            action_taken_msg = f"✅ {direction_str} 시간 설정이 변경되었습니다: {format_time_range(config, direction)}"
            
        else:
            await update.message.reply_text(
                "❗ 시간 설정은 '시각' 또는 '시간대'로만 가능합니다.\n"
                "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
            )
            return

    elif target_type == "알림조건":
        if not values: # 최소한 '기본' 등의 값이 있어야 함
            await update.message.reply_text(
                "❗ 알림 조건을 입력해주세요.\n"
                "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
            )
            return
        
        pref_type = values[0]
        
        if pref_type == "기본":
            config["notification_preference"] = DEFAULT_NOTIFICATION_PREFERENCE
            config["notification_threshold_amount"] = DEFAULT_NOTIFICATION_THRESHOLD_AMOUNT
            config["notification_target_price"] = DEFAULT_NOTIFICATION_TARGET_PRICE
        elif pref_type == "하락시":
            config["notification_preference"] = "PRICE_DROP_ANY"
        elif pref_type == "변동시":
            config["notification_preference"] = "ANY_PRICE_CHANGE"
        elif pref_type == "역대최저가":
            config["notification_preference"] = "HISTORICAL_LOW_UPDATED"
        elif pref_type == "목표가":
            if len(values) < 2 or not values[1].isdigit():
                await update.message.reply_text("❗ 목표 가격을 숫자로 입력해주세요. 예: `/set 알림조건 목표가 150000`")
                return
            target_price = int(values[1])
            if target_price <= 0:
                await update.message.reply_text("❗ 목표 가격은 0보다 커야 합니다.")
                return
            config["notification_preference"] = "TARGET_PRICE_REACHED"
            config["notification_target_price"] = target_price
        elif pref_type == "하락기준":
            if len(values) < 2 or not values[1].isdigit():
                await update.message.reply_text("❗ 하락 기준 금액을 숫자로 입력해주세요. 예: `/set 알림조건 하락기준 3000`")
                return
            threshold = int(values[1])
            if threshold < 0: # 0원 하락도 의미는 있으나, 혼동 방지. 보통 양수로 입력.
                await update.message.reply_text("❗ 하락 기준 금액은 0 이상이어야 합니다.")
                return
            config["notification_preference"] = "PRICE_DROP_THRESHOLD" # 하락기준 변경 시 자동으로 이 타입으로 설정
            config["notification_threshold_amount"] = threshold
        else:
            await update.message.reply_text(
                f"❗ 알 수 없는 알림 조건 타입: {pref_type}\n"
                "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
            )
            return
        action_taken_msg = f"✅ 알림 조건이 변경되었습니다: {format_notification_setting(config)}"

    elif target_type == "알림주기":
        if len(values) != 1 or not values[0].isdigit():
            await update.message.reply_text(
                "❗ 알림 주기는 숫자로 입력해주세요.\n"
                "예: `/set 알림주기 15` (15분마다 알림)"
            )
            return

        interval = int(values[0])
        if interval < 5 or interval > 1440:  # 5분 ~ 24시간 제한
            await update.message.reply_text(
                "❗ 알림 주기는 5분 이상, 1440분 이하로 설정해주세요."
            )
            return

        config['notification_interval'] = interval
        action_taken_msg = f"✅ 알림 주기가 {interval}분으로 설정되었습니다."

    else:
        await update.message.reply_text(
            f"❗ 알 수 없는 설정 타입: {target_type}\n"
            "자세한 설정 방법은 /settings 명령어로 확인하실 수 있습니다."
        )
        return

    if action_taken_msg: # 변경 사항이 있을 때만 저장 및 메시지 응답
        await save_user_config_async(user_id, config)
        await update.message.reply_text(action_taken_msg)
    else:
        await update.message.reply_text(
            "❗ 설정 변경에 실패했습니다. 올바른 명령어인지 확인해주세요."
        )

# Removed rotate_logs function - using config_manager.setup_logging method

# logging.basicConfig(...) # 여기서 로깅 설정 제거
# rotate_logs() # 여기서 호출 제거

# 로거 인스턴스는 모듈 레벨에서 생성 유지
logger = logging.getLogger(__name__)

# 기존 환경변수 상수들을 config_manager로 교체
# BOT_TOKEN, SELENIUM_HUB_URL, USER_AGENT, MAX_MONITORS, ADMIN_IDS 등은 
# config_manager에서 관리되므로 직접 정의하지 않음

KST = ZoneInfo("Asia/Seoul")
SETTING = 1

# 파일 패턴
PATTERN = re.compile(
    r"price_(?P<uid>\d+)_(?P<dep>[A-Z]{3})_(?P<arr>[A-Z]{3})_(?P<dd>\d{8})_(?P<rd>\d{8})\.json"
)

# Removed format_datetime - using config_manager.format_datetime method

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

# Custom Exceptions (defined globally)
class NoFlightDataException(Exception):
    """항공권 정보를 크롤링할 수 없을 때 발생"""
    pass

class NoMatchingFlightsException(Exception):
    """조건에 맞는 항공권을 찾을 수 없을 때 발생"""
    pass

# Modified fetch_prices to raise custom exceptions
async def fetch_prices(depart: str, arrive: str, d_date: str, r_date: str, max_retries=3, user_id=None):
    """항공권 가격 조회 (비동기 처리)"""
    logger.info(f"fetch_prices 호출: {depart}->{arrive} {d_date}~{r_date} (User: {user_id})")
    url = (
        f"https://flight.naver.com/flights/international/"
        f"{depart}-{arrive}-{d_date}/{arrive}-{depart}-{r_date}?adult=1&fareType=Y"
    )
    config = await get_user_config_async(user_id) if user_id else DEFAULT_USER_CONFIG.copy()
    
    async def _fetch_with_retry():
        last_exception = None
        for attempt in range(max_retries):
            try:
                logger.info(f"시도 {attempt + 1}/{max_retries}: {depart}->{arrive}")
                
                # 전역 selenium_manager 사용
                result = await selenium_manager.fetch_prices_async(url, depart, arrive, config)
                
                logger.info(f"조회 성공: {depart}->{arrive} (시도 {attempt + 1})")
                return result
                
            except (NoFlightDataException, NoMatchingFlightsException) as e:
                last_exception = e
                logger.warning(f"fetch_prices 시도 {attempt + 1}/{max_retries} 실패 (Specific): {e}")
                if attempt == max_retries - 1:
                    raise
            except Exception as ex:
                last_exception = ex
                logger.warning(f"fetch_prices 시도 {attempt + 1}/{max_retries} 실패 (Generic): {ex}", exc_info=True)
                if attempt == max_retries - 1:
                    raise Exception(f"항공권 조회 중 오류가 발생했습니다: {ex}") from ex
                
                wait_time = 5 * (attempt + 1)
                logger.info(f"{wait_time}초 대기 후 재시도...")
                await asyncio.sleep(wait_time)
        
        if last_exception:
            raise last_exception
        raise Exception("항공권 조회 중 알 수 없는 오류로 모든 시도 실패")

    return await _fetch_with_retry()

# 도움말 텍스트는 telegram_bot 모듈로 이동됨

# 키보드 관련 함수들은 telegram_bot 모듈로 이동됨

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"사용자 {update.effective_user.id} 요청: /start")
    # 관리자 여부에 따라 다른 키보드 표시
    keyboard = telegram_bot.get_keyboard_for_user(update.effective_user.id)
    await update.message.reply_text(
        await telegram_bot.help_text(update.effective_user.id),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"사용자 {update.effective_user.id} 요청: /help")
    # 관리자 여부에 따라 다른 키보드 표시
    keyboard = telegram_bot.get_keyboard_for_user(update.effective_user.id)
    await update.message.reply_text(
        await telegram_bot.help_text(update.effective_user.id),
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

# Removed validate_env_vars - using config_manager.validate_env_vars method

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
    user_id = update.effective_user.id
    logger.info(f"사용자 {user_id} 요청: /monitor")      # 현재 모니터링 개수 확인
    existing = [p for p in DATA_DIR.iterdir() if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id]
    if len(existing) >= config_manager.MAX_MONITORS:
        logger.warning(f"사용자 {user_id} 최대 모니터링 초과")
        keyboard = telegram_bot.get_keyboard_for_user(user_id)
        await update.message.reply_text(
            f"❗ 최대 {config_manager.MAX_MONITORS}개까지 모니터링할 수 있습니다.\n"
            "새로운 모니터링을 추가하려면 먼저 기존 모니터링을 취소해주세요.",
            reply_markup=keyboard
        )
        return ConversationHandler.END

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
    airports_file = AIRPORTS_JSON_PATH
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

# New cancel_conversation function
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the current conversation."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} canceled the conversation.")
    keyboard = telegram_bot.get_keyboard_for_user(user_id)
    await update.message.reply_text(
        '진행 중이던 설정 작업을 취소했습니다.', reply_markup=keyboard
    )
    return ConversationHandler.END

# Modified monitor_setting function for better flow
async def monitor_setting(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    final_keyboard = telegram_bot.get_keyboard_for_user(user_id)
    text = update.message.text.strip().split()

    if len(text) != 4:
        logger.warning(f"monitor_setting ({user_id}): 형식 오류 - {text}")
        await update.message.reply_text(
            "❗ 형식 오류\n"
            "✅ 올바른 형식: `ICN FUK 20251025 20251027`\n"
            "- 공항코드: 3자리 영문\n"
            "- 날짜: YYYYMMDD\n\n"
            "💡 주요 공항 코드 목록은 /airport 명령으로 확인하실 수 있습니다.\n"
            "다시 입력하시거나 /cancel 명령으로 취소하세요.",
            parse_mode="Markdown"
        )
        return SETTING

    outbound_dep, outbound_arr, outbound_date, inbound_date = text
    outbound_dep = outbound_dep.upper()
    outbound_arr = outbound_arr.upper()

    # 초기 상태 메시지 생성
    status_message = await update.message.reply_text(
        "🔍 항공권 정보를 조회하는 중입니다...\n⏳ 잠시만 기다려주세요.",
        reply_markup=None
    )
      # 메시지 매니저에 등록
    message_manager.set_status_message(user_id, status_message)
    
    try:
        # 기존 모니터링 개수 확인
        loop = asyncio.get_running_loop()
        existing = await loop.run_in_executor(
            file_executor,
            lambda: [p for p in DATA_DIR.iterdir() 
                    if PATTERN.fullmatch(p.name) and 
                    int(PATTERN.fullmatch(p.name).group('uid')) == user_id]
        )
        
        if len(existing) >= config_manager.MAX_MONITORS:
            logger.warning(f"사용자 {user_id} 최대 모니터링 초과")
            await message_manager.update_status_message(
                user_id,
                f"❗ 최대 {config_manager.MAX_MONITORS}개까지 모니터링할 수 있습니다.",
                reply_markup=final_keyboard
            )
            return ConversationHandler.END

        # 공항 정보 확인
        _, dep_city, dep_airport = get_airport_info(outbound_dep)
        _, arr_city, arr_airport = get_airport_info(outbound_arr)
        dep_city = dep_city or outbound_dep
        dep_airport = dep_airport or f"{outbound_dep}공항"
        arr_city = arr_city or outbound_arr
        arr_airport = arr_airport or f"{outbound_arr}공항"

        # 진행 상황 업데이트
        await message_manager.update_status_message(
            user_id,
            f"🔍 {dep_city} → {arr_city} 항공권 조회 중...\n⏳ 네이버 항공권에서 정보를 가져오고 있습니다."
        )
        
        # 가격 조회 (시간이 오래 걸리는 작업)
        try:
            restricted, r_info, overall, o_info, link = await fetch_prices(
                outbound_dep, outbound_arr, outbound_date, inbound_date, 3, user_id
            )
            
            if restricted is None and overall is None:
                raise NoFlightDataException("항공권 정보를 찾을 수 없습니다 (결과 없음)")
            
        except Exception as fetch_error:
            logger.error(f"가격 조회 실패 (User: {user_id}): {fetch_error}")
            await message_manager.update_status_message(
                user_id,
                f"❌ 항공권 조회 중 오류가 발생했습니다.\n\n🔸 {str(fetch_error)}\n\n다시 시도해 주세요.",
                reply_markup=final_keyboard
            )
            return ConversationHandler.END
        
        # 모니터링 설정 저장
        hist_path = DATA_DIR / f"price_{user_id}_{outbound_dep}_{outbound_arr}_{outbound_date}_{inbound_date}.json"
        start_time = config_manager.format_datetime(datetime.now())
        user_config = await get_user_config_async(user_id)
        
        await save_json_data_async(hist_path, {
            "start_time": start_time,
            "restricted": restricted or 0,
            "overall": overall or 0,
            "last_fetch": config_manager.format_datetime(datetime.now()),
            "time_setting_outbound": format_time_range(user_config, 'outbound'),
            "time_setting_inbound": format_time_range(user_config, 'inbound')
        })

        # 작업 스케줄러 등록
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
        
        # 최종 성공 메시지
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
            msg_lines.extend([f"🎯 *시간 제한 적용 최저가*", r_info, ""])
        if overall:
            msg_lines.extend([f"📌 *전체 최저가*", o_info])
            
        msg_lines.extend([
            "", "ℹ️ 30분마다 자동으로 가격을 확인하며,", 
            "가격이 하락하면 알림을 보내드립니다.",
            "", f"🔗 [네이버 항공권 바로가기]({link})"
        ])
        
        # 최종 결과 업데이트
        final_result = await message_manager.update_status_message(
            user_id,
            "\n".join(msg_lines),
            parse_mode="Markdown",
            reply_markup=final_keyboard
        )
        
        if not final_result:
            # 편집 실패 시 새 메시지 발송
            await update.message.reply_text(
                "\n".join(msg_lines),
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=final_keyboard
            )
        
    except Exception as e:
        logger.error(f"monitor_setting 전체 실패 (User: {user_id}): {e}")
        await message_manager.update_status_message(
            user_id,
            f"❌ 처리 중 오류가 발생했습니다.\n{str(e)}",
            reply_markup=final_keyboard
        )
    
    finally:
        # 상태 메시지 정리
        message_manager.clear_status_message(user_id)
    
    return ConversationHandler.END

async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    """등록된 모니터링 작업을 주기적으로 실행하여 항공권 가격 변동을 확인하고 알림을 전송합니다."""
    data = context.job.data
    user_id = data['chat_id']
    outbound_dep, outbound_arr, outbound_date, inbound_date = data['settings']
    hist_path = Path(data['hist_path'])

    if not hist_path.exists():
        logger.warning(f"monitor_job: 히스토리 파일 없음, 작업 중단: {hist_path.name}")
        context.job.schedule_removal()
        return
        
    logger.info(f"monitor_job 실행: {outbound_dep}->{outbound_arr}, 히스토리 파일: {hist_path.name}")

    try:
        state = await load_json_data_async(hist_path)
    except json.JSONDecodeError:
        logger.error(f"monitor_job: JSON 디코딩 오류 {hist_path.name}. 작업 중단 및 파일 삭제 시도.")
        try: hist_path.unlink()
        except OSError as e: logger.error(f"손상된 히스토리 파일 삭제 실패 {hist_path.name}: {e}")
        context.job.schedule_removal()
        return
    except FileNotFoundError:
        logger.warning(f"monitor_job: 히스토리 파일 (lock 내부) 없음, 작업 중단: {hist_path.name}")
        context.job.schedule_removal()
        return

    old_restr = state.get("restricted", 0)
    old_overall = state.get("overall", 0)
    restricted, r_info, overall, o_info, link = None, "", None, "", ""

    # 공항 정보 미리 가져오기
    _, dep_city, _ = get_airport_info(outbound_dep)
    _, arr_city, _ = get_airport_info(outbound_arr)
    dep_city = dep_city or outbound_dep
    arr_city = arr_city or outbound_arr

    try:
        restricted, r_info, overall, o_info, link = await fetch_prices(
            outbound_dep, outbound_arr, outbound_date, inbound_date, 3, user_id
        )
        
        notify_msg_lines = []
        price_change_occurred = False

        if restricted is not None and old_restr > 0 and old_restr - restricted >= 5000:
            price_change_occurred = True
            notify_msg_lines.extend([
                f"📉 *{dep_city} ↔ {arr_city} 가격 하락 알림*", "",
                "🎯 *시간 제한 적용 최저가*",
                f"💰 {old_restr:,}원 → *{restricted:,}원* (-{old_restr - restricted:,}원)",
                r_info
            ])

        if overall is not None and old_overall > 0 and old_overall - overall >= 5000:
            if not price_change_occurred:
                 notify_msg_lines.extend([f"📉 *{dep_city} ↔ {arr_city} 가격 하락 알림*", ""])
            price_change_occurred = True
            notify_msg_lines.extend([
                "", "📌 *전체 최저가*",
                f"💰 {old_overall:,}원 → *{overall:,}원* (-{old_overall - overall:,}원)",
                o_info
            ])
            
        if price_change_occurred:
            notify_msg_lines.extend([
                "", f"📅 {outbound_date[:4]}/{outbound_date[4:6]}/{outbound_date[6:]} → {inbound_date[:4]}/{inbound_date[4:6]}/{inbound_date[6:]}",
                f"🔗 [네이버 항공권]({link})"
            ])
            try:
                await context.bot.send_message(
                    user_id, 
                    "\n".join(notify_msg_lines), 
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                logger.info(f"가격 하락 알림 전송 완료 for {hist_path.name}")
            except Exception as send_error:
                logger.error(f"가격 하락 알림 전송 실패 ({hist_path.name}): {send_error}")

    except NoMatchingFlightsException:
        logger.info(f"monitor_job: 조건에 맞는 항공권 없음 - {hist_path.name}")
        user_config = await get_user_config_async(user_id)
        if old_restr != 0 or old_overall != 0:
            naver_link = f"https://flight.naver.com/flights/international/{outbound_dep}-{outbound_arr}-{outbound_date}/{outbound_arr}-{outbound_dep}-{inbound_date}?adult=1&fareType=Y"
            msg_lines = [
                f"ℹ️ *{dep_city} ↔ {arr_city} 항공권 알림*", "",
                "현재 설정하신 시간 조건에 맞는 항공권이 없습니다.",
                f"• 가는 편 시간: {format_time_range(user_config, 'outbound')}",
                f"• 오는 편 시간: {format_time_range(user_config, 'inbound')}",
                "시간 설정을 변경하시려면 /settings 명령어를 사용해주세요.", "",
                f"📅 {outbound_date[:4]}/{outbound_date[4:6]}/{outbound_date[6:]} → {inbound_date[:4]}/{inbound_date[4:6]}/{inbound_date[6:]}",
                f"🔗 [네이버 항공권]({naver_link})"
            ]
            try:
                await context.bot.send_message(
                    user_id, 
                    "\n".join(msg_lines), 
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            except Exception as send_error:
                logger.error(f"항공권 없음 알림 전송 실패 ({hist_path.name}): {send_error}")
    except NoFlightDataException:
        logger.warning(f"monitor_job: 항공권 정보 없음 (아마도 경로 문제) - {hist_path.name}")
    except Exception as ex:
        logger.error(f"monitor_job 실행 중 오류 발생 ({hist_path.name}): {ex}", exc_info=True)

    current_user_config = await get_user_config_async(user_id)
    new_state_data = {
        "start_time": state.get("start_time"),
        "restricted": restricted if restricted is not None else old_restr,
        "overall": overall if overall is not None else old_overall,
        "last_fetch": config_manager.format_datetime(datetime.now()),
        "time_setting_outbound": format_time_range(current_user_config, 'outbound'),
        "time_setting_inbound": format_time_range(current_user_config, 'inbound')
    }
    logger.debug(f"[{hist_path.name}] 상태 저장 시도: {new_state_data}")
    try:
        await save_json_data_async(hist_path, new_state_data)
        logger.info(f"[{hist_path.name}] 상태 저장 및 last_fetch 업데이트 성공. 새 last_fetch: {new_state_data.get('last_fetch')}")
    except Exception as e_save:
        logger.error(f"CRITICAL: [{hist_path.name}] monitor_job 실행 후 상태 파일 저장 실패: {e_save}", exc_info=True)

@rate_limit
async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"사용자 {user_id} 요청: /status")
    
    # 비동기적으로 파일 목록 가져오기
    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(
        file_executor,
        lambda: sorted([
            p for p in DATA_DIR.iterdir()
            if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id
        ])
    )
    
    if not files:
        await update.message.reply_text(
            "현재 실행 중인 모니터링이 없습니다."
        )
        return

    now = datetime.now(KST)
    msg_lines = ["📋 *모니터링 현황*"]

    for idx, hist_file_path in enumerate(files, start=1):
        try:
            info = PATTERN.fullmatch(hist_file_path.name).groupdict()
            data = await load_json_data_async(hist_file_path)
            start_time = datetime.strptime(
                data['start_time'], '%Y-%m-%d %H:%M:%S'
            ).replace(tzinfo=KST)
            elapsed = (now - start_time).days
            
            dep, arr = info['dep'], info['arr']
            _, dep_city, _ = get_airport_info(dep)
            _, arr_city, _ = get_airport_info(arr)
            dep_city = dep_city or dep # 도시 정보가 없으면 공항 코드로 대체
            arr_city = arr_city or arr # 도시 정보가 없으면 공항 코드로 대체
            dd, rd = info['dd'], info['rd']
            dd_fmt = f"{dd[2:4]}.{dd[4:6]}.{dd[6:]}"
            rd_fmt = f"{rd[2:4]}.{rd[4:6]}.{rd[6:]}"
            
            prices = []
            if data['restricted']:
                prices.append(f"조건부: {data['restricted']:,}원")
            if data['overall']:
                prices.append(f"전체: {data['overall']:,}원")
            price_info = " / ".join(prices) if prices else "조회된 가격 없음"
            
            msg_lines.extend([
                "",
                f"*{idx}. {dep_city}({dep}) ↔ {arr_city}({arr})*",
                f"📅 {dd_fmt} → {rd_fmt}",
                f"💰 {price_info}",
                f"⏱️ {elapsed}일째 진행 중",
                f"🔄 마지막 조회: {data['last_fetch']}",
                f"[🔗 네이버 항공권](https://flight.naver.com/flights/international/{dep}-{arr}-{dd}/{arr}-{dep}-{rd}?adult=1&fareType=Y)"
            ])
        except FileNotFoundError:
            logger.warning(f"Status: File not found for {hist_file_path.name}, skipping.")
            continue
        except json.JSONDecodeError:
            logger.warning(f"Status: JSON decode error for {hist_file_path.name}, skipping.")
            continue

    keyboard = telegram_bot.get_keyboard_for_user(user_id)
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
        keyboard = telegram_bot.get_keyboard_for_user(user_id)
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
    """모니터링 취소 요청(인라인 버튼 콜백)을 처리합니다."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    logger.info(f"사용자 {user_id} 콜백: {data}")
    monitors = ctx.application.bot_data.get("monitors", {})
    user_mons = monitors.get(user_id, [])
    keyboard = telegram_bot.get_keyboard_for_user(user_id)

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
    if user_id not in config_manager.ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    # 모든 모니터링 파일 찾기 (비동기적으로)
    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(
        file_executor,
        lambda: sorted(DATA_DIR.glob("price_*.json"))
    )

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
    if user_id not in config_manager.ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    # 모든 모니터링 파일 찾기 (비동기적으로)
    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(
        file_executor,
        lambda: list(DATA_DIR.glob("price_*.json"))
    )

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
    """전체 모니터링 취소 요청(인라인 버튼 콜백)을 처리합니다."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in config_manager.ADMIN_IDS:
        await query.answer("❌ 관리자 권한이 필요합니다.")
        return
    
    if query.data == "cancel_allcancel":
        # 인라인 키보드 제거
        await query.message.edit_text(
            "모니터링 취소가 취소되었습니다."
        )
        # 새로운 메시지로 관리자 키보드 표시
        keyboard = telegram_bot.get_keyboard_for_user(query.from_user.id)
        await query.message.reply_text(
            "다른 작업을 선택해주세요.",
            reply_markup=keyboard
        )
        await query.answer("작업이 취소되었습니다.")
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
      # 인라인 키보드 제거
    await query.message.edit_text(
        "\n".join(msg_parts)
    )
    # 새로운 메시지로 관리자 키보드 표시
    keyboard = telegram_bot.get_keyboard_for_user(query.from_user.id)
    await query.message.reply_text(
        "다른 작업을 선택해주세요.",
        reply_markup=keyboard
    )
    await query.answer("모든 모니터링이 취소되었습니다.")
    logger.info(f"전체 모니터링 종료: {count}건 처리됨, {error_count}건의 오류")

async def on_startup(app: ApplicationBuilder): # Type hint for app
    now = datetime.now(KST)
    monitors = app.bot_data.setdefault("monitors", {})
    logger.info("봇 시작: 기존 모니터링 작업 복원 중...")

    processed_files = 0
    active_jobs_restored = 0

    for hist_path in DATA_DIR.glob("price_*.json"):
        processed_files += 1
        try:
            # logger.debug(f"모니터링 파일 처리 중: {hist_path.name}") # 상세 로그는 필요시 활성화
            m = PATTERN.fullmatch(hist_path.name)
            if not m:
                logger.warning(f"잘못된 모니터링 파일 이름 패턴 무시: {hist_path.name}")
                continue

            try:
                data = await load_json_data_async(hist_path)
            except json.JSONDecodeError:
                logger.error(f"모니터링 복원 중 JSON 디코딩 오류 ({hist_path.name}). 파일 삭제 시도.")
                try: hist_path.unlink(missing_ok=True) # missing_ok 추가 (Python 3.8+)
                except OSError as e_unlink: logger.error(f"손상된 모니터링 파일 삭제 실패 ({hist_path.name}): {e_unlink}")
                continue
            except FileNotFoundError:
                logger.warning(f"모니터링 복원 중 파일 없음 (race condition?): {hist_path.name}")
                continue

            start_time_str = data.get("start_time")
            last_fetch_str = data.get("last_fetch")
            
            if not last_fetch_str:
                # last_fetch가 없는 경우, 오래된 것으로 간주하여 즉시 실행하고 다음 정기 실행 예약
                logger.warning(f"last_fetch 누락 ({hist_path.name}). 즉시 실행 대상으로 처리.")
                last_fetch = now - timedelta(minutes=31) # 30분 이상 경과한 것으로 처리
            else:
                try:
                    last_fetch = datetime.strptime(last_fetch_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
                except ValueError as e_time:
                    logger.warning(f"잘못된 last_fetch 형식 ({hist_path.name}): '{last_fetch_str}' ({e_time}). 즉시 실행 대상으로 처리.")
                    last_fetch = now - timedelta(minutes=31)

            interval = timedelta(minutes=30)
            delta = now - last_fetch

            uid = int(m.group("uid"))
            dep, arr, dd, rd = m.group("dep"), m.group("arr"), m.group("dd"), m.group("rd")
            
            job_base_name = str(hist_path)

            # 마감된 작업 즉시 실행 (Catch-up job)
            if delta >= interval:
                logger.info(f"즉시 조회 예약 (경과 시간 {delta.total_seconds()/60:.1f}분): {hist_path.name}")
                app.job_queue.run_once(
                    monitor_job,
                    when=timedelta(seconds=0),
                    name=f"{job_base_name}_startup_immediate",
                    data={
                        "chat_id": uid,
                        "settings": (dep, arr, dd, rd),
                        "hist_path": str(hist_path)
                    }
                )

            # 정기 반복 작업 (Repeating job)
            if delta.total_seconds() < 0: # last_fetch가 미래 시간인 경우 (시스템 시간 변경 등)
                next_run_delay = interval
                logger.warning(
                    f"last_fetch가 미래 시간 ({hist_path.name}): {config_manager.format_datetime(last_fetch)}. "
                    f"다음 정기 실행은 {next_run_delay.total_seconds()/60:.1f}분 후로 예약합니다."
                )
            else:
                time_into_current_cycle = delta % interval
                next_run_delay = interval - time_into_current_cycle
                if next_run_delay.total_seconds() == 0 and delta.total_seconds() > 0:
                     next_run_delay = interval

            # logger.info(
            #     f"정기 모니터링 등록: {hist_path.name} | "
            #     f"Last Fetch: {last_fetch_str if last_fetch_str else 'N/A'} | Now: {config_manager.format_datetime(now)} | Delta: {delta.total_seconds()/60:.1f}분 | "
            #     f"다음 실행까지 약: {next_run_delay.total_seconds()/60:.1f}분"
            # ) # 상세 로그는 유지하거나 필요시 주석 해제

            job = app.job_queue.run_repeating(
                monitor_job,
                interval=interval,
                first=next_run_delay,
                name=job_base_name,
                data={
                    "chat_id": uid,
                    "settings": (dep, arr, dd, rd),
                    "hist_path": str(hist_path)
                }
            )
            active_jobs_restored +=1

            parsed_start_time = now # Fallback
            if start_time_str:
                try:
                    parsed_start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
                except ValueError:
                    logger.warning(f"잘못된 start_time 형식 ({hist_path.name}): '{start_time_str}'")
            
            monitors.setdefault(uid, []).append({
                "settings": (dep, arr, dd, rd),
                "start_time": parsed_start_time,
                "hist_path": str(hist_path),
                "job_name_repeating": job.name 
            })

        except Exception as ex_outer:
            logger.error(f"모니터링 복원 중 ({hist_path.name}) 처리 실패: {ex_outer}", exc_info=True)
            # 오류 발생한 모니터링 파일 삭제 시도 (선택적)
            # try:
            #     hist_path.unlink(missing_ok=True)
            #     logger.info(f"오류 발생으로 모니터링 파일 삭제 시도: {hist_path.name}")
            # except OSError as e_unlink_outer:
            #     logger.error(f"오류 모니터링 파일 삭제 실패 ({hist_path.name}): {e_unlink_outer}")

    logger.info(f"모니터링 복원 완료: 총 {processed_files}개 파일 처리, {active_jobs_restored}개 작업 활성/재개됨.")

# Removed file_lock, save_json_data, load_json_data - using config_manager methods

# Modified cleanup_old_data function signature and body
async def cleanup_old_data(context: ContextTypes.DEFAULT_TYPE): # Add context argument
    """오래된 모니터링 데이터와 설정 파일 정리"""
    retention_days = config_manager.DATA_RETENTION_DAYS
    config_retention_days = config_manager.CONFIG_RETENTION_DAYS
    cutoff_date = datetime.now(KST) - timedelta(days=retention_days)
    config_cutoff_date = datetime.now(KST) - timedelta(days=config_retention_days)

    monitor_deleted = 0
    config_deleted = 0

    # 오래된 모니터링 데이터 정리
    for file_path in config_manager.DATA_DIR.glob("price_*.json"):
        try:
            # Use load_json_data for consistent locking
            data = await load_json_data_async(file_path)
            start_time_str = data.get("start_time")
            if not start_time_str:
                logger.warning(f"데이터 정리 중 'start_time' 누락: {file_path.name}, 파일 삭제 시도.")
                try:
                    file_path.unlink()
                    monitor_deleted +=1
                except OSError as e:
                    logger.error(f"오래된 데이터 파일 삭제 실패 '{file_path.name}': {e}")
                continue

            start_time = datetime.strptime(
                start_time_str,
                "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=KST)
            if start_time < cutoff_date:
                logger.info(f"오래된 데이터 삭제: {file_path.name}")
                try:
                    file_path.unlink()
                    monitor_deleted += 1
                except OSError as e:
                    logger.error(f"오래된 데이터 파일 삭제 실패 '{file_path.name}': {e}")
        except json.JSONDecodeError:
            logger.warning(f"데이터 정리 중 JSON 디코딩 오류: {file_path.name}, 파일 삭제 시도.")
            try:
                file_path.unlink() # Delete corrupted file
                monitor_deleted +=1
            except OSError as e:
                logger.error(f"손상된 데이터 파일 삭제 실패 '{file_path.name}': {e}")
        except Exception as ex:
            logger.warning(f"데이터 정리 중 오류 발생 ({file_path.name}): {ex}")

    # 오래된 설정 파일 정리
    for config_file in config_manager.USER_CONFIG_DIR.glob("config_*.json"):
        try:
            # Use async load for consistency and proper locking
            if not config_file.exists(): continue # Might have been deleted

            data = await load_json_data_async(config_file) # 비동기 로드 및 잠금
            last_activity_str = data.get('last_activity', data.get('created_at'))

            if not last_activity_str:
                logger.warning(f"설정 파일 정리 중 'last_activity' 또는 'created_at' 누락: {config_file.name}, 파일 삭제 시도.")
                try:
                    if config_file.exists(): config_file.unlink()
                    config_deleted += 1
                except OSError as e:
                    logger.error(f"오래된 설정 파일 삭제 실패 '{config_file.name}': {e}")
                continue
            
            last_activity = datetime.strptime(
                last_activity_str,
                '%Y-%m-%d %H:%M:%S'
            ).replace(tzinfo=KST)

            if last_activity < config_cutoff_date:
                user_id_match = re.search(r"config_(\d+)\.json", config_file.name)
                if not user_id_match:
                    logger.warning(f"설정 파일 이름에서 user_id 추출 불가: {config_file.name}")
                    continue
                user_id = int(user_id_match.group(1))

                # Check for active monitors for this user
                loop = asyncio.get_running_loop()
                active_monitors = await loop.run_in_executor(
                    file_executor, 
                    lambda: [p for p in config_manager.DATA_DIR.glob(f"price_{user_id}_*.json") if p.exists()]
                )

                if not active_monitors:
                    logger.info(f"비활성 사용자 설정 삭제: {config_file.name}")
                    try:
                        if config_file.exists(): config_file.unlink()
                        config_deleted += 1
                    except OSError as e:
                        logger.error(f"비활성 사용자 설정 파일 삭제 실패 '{config_file.name}': {e}")
        except json.JSONDecodeError:
            logger.warning(f"설정 파일 정리 중 JSON 디코딩 오류: {config_file.name}, 파일 삭제 시도.")
            try:
                if config_file.exists():
                     config_file.unlink()
                     config_deleted +=1
            except OSError as e:
                logger.error(f"손상된 설정 파일 삭제 실패 '{config_file.name}': {e}")
        except Exception as ex:
            logger.warning(f"설정 파일 정리 중 오류 발생 ({config_file.name}): {ex}")

    if config_manager.ADMIN_IDS and (monitor_deleted > 0 or config_deleted > 0) : # Only notify if changes were made
        msg = (
            "🧹 *데이터 정리 완료*\n"
            f"• 삭제된 모니터링: {monitor_deleted}건\n"
            f"• 삭제된 설정 파일: {config_deleted}건\n\n"
            f"모니터링 보관 기간: {retention_days}일\n"
            f"설정 파일 보관 기간: {config_retention_days}일"
        )
        for admin_id in config_manager.ADMIN_IDS:
            try:
                await context.bot.send_message( # Use context.bot
                    chat_id=admin_id,
                    text=msg,
                    parse_mode="Markdown"
                )
            except Exception as ex:
                logger.error(f"관리자({admin_id})에게 알림 전송 실패: {ex}")

async def airport_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """등록된 주요 공항 코드 목록을 보여줍니다."""
    logger.info(f"사용자 {update.effective_user.id} 요청: /airport")
    # airport 명령어 실행 시 키보드 유지
    keyboard = telegram_bot.get_keyboard_for_user(update.effective_user.id)
    await update.message.reply_text(
        format_airport_list(),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

def cleanup_resources():
    """리소스 정리"""
    logger.info("리소스 정리 시작...")
    selenium_manager.shutdown()
    file_executor.shutdown(wait=True)
    logger.info("리소스 정리 완료")

def main():
    # config_manager로 로깅 설정 및 환경변수 검증
    config_manager.setup_logging()

    logger.info("텔레그램 봇 애플리케이션 시작 중...")
    
    # 환경변수 검증
    errors = config_manager.validate_env_vars()
    if errors:
        for error in errors:
            logger.error(error)
        # 환경변수 오류 시에는 봇을 시작하지 않고 종료
        logger.error("환경변수 설정 오류로 인해 봇을 시작할 수 없습니다.")
        return # main 함수 종료
    
    if not config_manager.BOT_TOKEN:
        # 이 경우는 validate_env_vars에서 이미 처리되지만, 추가 방어 코드
        logger.error("환경변수 BOT_TOKEN이 설정되어 있지 않습니다. 봇을 시작할 수 없습니다.")
        return # main 함수 종료
    
    application = ApplicationBuilder().token(config_manager.BOT_TOKEN).concurrent_updates(True).build()
    
    # 작업 디렉토리 생성 (DATA_DIR은 이미 상단에서 생성 시도됨, USER_CONFIG_DIR 등)
    # DATA_DIR.mkdir(parents=True, exist_ok=True) # 중복될 수 있으므로 확인
    
    # 핸들러 등록
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("monitor", monitor_cmd)],
        states={
            SETTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_setting),
                CommandHandler("cancel", cancel_conversation)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("airport", airport_cmd))
    application.add_handler(CommandHandler("settings", settings_cmd))
    application.add_handler(CommandHandler("set", set_cmd))
      # 콜백 쿼리 핸들러 추가 (패턴이 더 구체적인 것을 먼저 등록)
    application.add_handler(CallbackQueryHandler(all_cancel_callback, pattern="^(confirm|cancel)_allcancel$"))
    application.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel_"))
    
    # 관리자 명령어
    if config_manager.ADMIN_IDS:
        application.add_handler(CommandHandler("allstatus", all_status))
        application.add_handler(CommandHandler("allcancel", all_cancel))
    
    # 매일 자정에 오래된 데이터 정리
    application.job_queue.run_daily(        cleanup_old_data,
        time=time(hour=0, minute=0, tzinfo=KST)
    )
    
    logger.info("봇 실행 시작")
    # 시작 시 on_startup 함수 실행 (비동기)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(on_startup(application))
    
    try:
        # 봇 실행
        application.run_polling()
    except KeyboardInterrupt:
        logger.info("키보드 인터럽트로 봇 종료")
    except Exception as e:
        logger.error(f"봇 실행 중 오류 발생: {e}", exc_info=True)
    finally:
        # 종료 시 리소스 정리
        logger.info("봇 종료 중...")
        cleanup_resources()
        try:
            loop.close()
        except Exception as e:
            logger.warning(f"이벤트 루프 종료 중 오류: {e}")
        logger.info("봇 종료 완료")

if __name__ == "__main__":
    main()
