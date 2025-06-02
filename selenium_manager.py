#!/usr/bin/env python3
"""
Selenium Manager for Flight Price Checker Bot

이 모듈은 항공권 가격 체커 봇의 Selenium 관련 기능을 담당합니다.
- SeleniumManager 클래스: 브라우저 드라이버 관리 및 웹 크롤링
- 항공편 정보 파싱 함수들
- 시간 제한 조건 체크 함수
- 커스텀 예외 클래스들
"""

import re
import time as time_module
import logging
import asyncio
import threading
from datetime import datetime, time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple, Dict, Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ConfigManager import
from config_manager import config_manager

# 로거 설정
logger = logging.getLogger(__name__)

# ConfigManager에서 설정값들을 가져옴
TIME_PERIODS = config_manager.TIME_PERIODS
DEFAULT_USER_CONFIG = config_manager.DEFAULT_USER_CONFIG


# Custom Exceptions
class NoFlightDataException(Exception):
    """항공권 정보를 크롤링할 수 없을 때 발생"""
    pass


class NoMatchingFlightsException(Exception):
    """조건에 맞는 항공권을 찾을 수 없을 때 발생"""
    pass


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
            for period in inbound_periods            for period_start, period_end in [TIME_PERIODS[period]]
        )
        if not is_valid_inbound:
            logger.debug(f"오는 편 시간대 미매칭: {ret_t}는 선택된 시간대 {inbound_periods}에 포함되지 않음")
            return False
            
    else:  # exact
        # 시각 설정: 가는 편은 설정 시각 이하, 오는 편은 설정 시각 이상
        outbound_limit = time(hour=config['outbound_exact_hour'], minute=0)
        if dep_t > outbound_limit:
            logger.debug(f"가는 편 시각 미매칭: {dep_t} > {outbound_limit}")
            return False
            
        inbound_limit = time(hour=config['inbound_exact_hour'], minute=0)
        if ret_t < inbound_limit:
            logger.debug(f"오는 편 시각 미매칭: {ret_t} < {inbound_limit}")
            return False
            
    return True


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
        logger.info(f"[SeleniumManager] setup_driver 진입 (grid_url={self.grid_url}, user_agent={self.user_agent})")
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        if self.user_agent:
            options.add_argument(f'user-agent={self.user_agent}')
        try:
            if self.grid_url:
                logger.info(f"[SeleniumManager] Remote WebDriver 생성 시도: {self.grid_url}")
                driver = webdriver.Remote(
                    command_executor=self.grid_url,
                    options=options
                )
            else:
                logger.info("[SeleniumManager] Local ChromeDriver 생성 시도")
                driver = webdriver.Chrome(options=options)
            logger.info("[SeleniumManager] WebDriver 생성 완료")
            return driver
        except Exception as e:
            logger.error(f"[SeleniumManager] WebDriver 생성 실패: {e}", exc_info=True)
            raise

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
            
            logger.info(f"[SeleniumManager] driver.get 호출 준비: {url}")
            driver.get(url)
            logger.info(f"[SeleniumManager] driver.get 완료: {url}")
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
            logger.error(f"Selenium 작업 #{task_id} 실패: {e}", exc_info=True)
            raise
        finally:
            if driver:
                try:
                    driver.quit()
                    logger.info(f"[SeleniumManager] WebDriver quit 완료 (task_id={task_id})")
                except Exception as quit_e:
                    logger.error(f"[SeleniumManager] WebDriver quit 중 오류: {quit_e}", exc_info=True)
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


async def fetch_prices(depart: str, arrive: str, d_date: str, r_date: str, max_retries=3, user_id=None, selenium_manager=None):
    """항공권 가격 조회 (비동기 처리)"""
    logger.info(f"fetch_prices 호출: {depart}->{arrive} {d_date}~{r_date} (User: {user_id})")
    url = (
        f"https://flight.naver.com/flights/international/"
        f"{depart}-{arrive}-{d_date}/{arrive}-{depart}-{r_date}?adult=1&fareType=Y"
    )
    
    # config_manager에서 사용자 설정 로드하는 함수를 임포트해야 하는데,
    # 순환 임포트를 피하기 위해 매개변수로 받거나 config 인자를 직접 받도록 수정
    if user_id:
        # 기본 config를 사용하거나, 호출하는 쪽에서 config를 전달받도록 수정
        config = DEFAULT_USER_CONFIG.copy()
    else:
        config = DEFAULT_USER_CONFIG.copy()
    
    if selenium_manager is None:
        raise ValueError("selenium_manager 인스턴스가 필요합니다")
    
    async def _fetch_with_retry():
        last_exception = None
        for attempt in range(max_retries):
            try:
                logger.info(f"시도 {attempt + 1}/{max_retries}: {depart}->{arrive}")
                
                # 전달받은 selenium_manager 사용
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
