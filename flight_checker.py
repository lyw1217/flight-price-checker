#!/usr/bin/env python3
"""
환경변수 설정 (필수):
- BOT_TOKEN         : Telegram 봇 토큰 (예: 123456:ABCDEF...)
- SELENIUM_HUB_URL  : Selenium Hub 주소 (예: http://192.168.0.88:4445/wd/hub)
- ADMIN_IDS         : 관리자 ID 목록 (쉼표로 구분된 Telegram 사용자 ID, 예: 123456789,987654321)

.env 예시:
BOT_TOKEN=123456:ABCDEF-your-token
SELENIUM_HUB_URL=http://192.168.0.88:4445/wd/hub
ADMIN_IDS=123456789,987654321
"""

import os
import re
import json
import time
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ConversationHandler,
    ContextTypes, filters
)
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 로깅 설정 (파일 + 콘솔, INFO 레벨)
LOG_FILE = "flight_bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 상수 정의
SETTING = 1
BOT_TOKEN = os.getenv("BOT_TOKEN")
SELENIUM_HUB_URL = os.getenv("SELENIUM_HUB_URL", "http://localhost:4444/wd/hub")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit())

# 유틸: 시간 문자열을 datetime 객체로 변환
def to_time(timestr: str) -> datetime:
    logger.debug(f"to_time 호출: {timestr}")
    return datetime.strptime(timestr, "%H:%M")

# 도움말 텍스트 생성
def help_text() -> str:
    admin_help = ""
    if ADMIN_IDS:
        admin_help = "\n관리자 명령:\n/all_status - 전체 상태 조회\n/all_cancel - 전체 감시 종료"
    text = (
        "✈️ 30분마다 항공권 최저가 조회\n"
        "🛫 조건: 출발일 12시 이전, 도착일 14시 이후\n"
        "🛬 항공권 모니터링 봇 사용법:\n"
        "/monitor - 모니터링 시작 (예: ICN FUK 20251025 20251027)\n"
        "/status  - 내 설정 확인\n"
        "/cancel  - 모니터링 중단\n"
        "/help    - 도움말"
        + admin_help
    )
    logger.info("help_text 생성 완료")
    return text

# --- 핸들러 정의 ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(help_text())
    logger.info(f"[{update.effective_user.id}] /start 호출")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(help_text())
    logger.info(f"[{update.effective_user.id}] /help 호출")

async def monitor_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ 입력 예시: ICN FUK 20251025 20251027 (YYYYMMDD)")
    logger.info(f"[{update.effective_user.id}] /monitor 호출")
    return SETTING


def valid_date(d: str) -> bool:
    try:
        valid = bool(re.fullmatch(r"\d{8}", d)) and datetime.strptime(d, "%Y%m%d")
        logger.info(f"valid_date({d}) -> {valid}")
        return valid
    except Exception as e:
        logger.info(f"valid_date 오류: {e}")
        return False

async def monitor_setting(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    logger.info(f"[{user_id}] 모니터 설정 입력: {text}")
    await update.message.reply_text(f"모니터 설정 적용 중: {text}")
    parts = text.split()
    if len(parts) != 4 or not valid_date(parts[2]) or not valid_date(parts[3]):
        await update.message.reply_text("❗ 형식 오류. 예: ICN FUK 20251025 20251027")
        logger.info(f"[{user_id}] 입력 형식 오류: {text}")
        return SETTING

    depart, arrive, d_date, r_date = parts
    settings = (depart, arrive, d_date, r_date)
    ctx.chat_data['settings']   = settings
    ctx.chat_data['start_time'] = datetime.now()
    ctx.chat_data['task']       = asyncio.create_task(
        monitor_loop(ctx, user_id, settings)
    )
    ctx.chat_data['lowest_price'] = None

    await update.message.reply_text(f"✅ 모니터링 시작: {depart}→{arrive} {d_date}~{r_date}")
    logger.info(f"[{user_id}] 모니터링 작업 시작: {settings}")
    return ConversationHandler.END

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = ctx.chat_data.get('settings')
    logger.info(f"[{user_id}] /status 호출")
    if not settings:
        await update.message.reply_text("현재 실행 중인 모니터링이 없습니다.")
        return
    lp      = ctx.chat_data.get('lowest_price')
    elapsed = (datetime.now() - ctx.chat_data.get('start_time')).days
    depart, arrive, d_date, r_date = settings
    await update.message.reply_text(
        f"📋 내 설정:\n"
        f"{depart}→{arrive} {d_date}~{r_date}\n"
        f"최저가: {lp if lp is not None else '없음'}원\n"
        f"경과일: {elapsed}일 (최대 30일)"
    )

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"[{user_id}] /cancel 호출")
    task = ctx.chat_data.get('task')
    if task:
        task.cancel()
        ctx.chat_data.clear()
        await update.message.reply_text("✅ 모니터링이 취소되었습니다.")
        logger.info(f"[{user_id}] 모니터링 작업 취소")
    else:
        await update.message.reply_text("실행 중인 모니터링이 없습니다.")

async def all_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"[{user_id}] /all_status 호출")
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    lines = []
    for chat_id, data in ctx.application.chat_data.items():
        settings = data.get('settings')
        if not settings:
            continue
        lp      = data.get('lowest_price')
        elapsed = (datetime.now() - data.get('start_time')).days
        d, a, dd, rr = settings
        lines.append(f"{chat_id}: {d}→{a} {dd}~{rr} | 최저가:{lp or '없음'}원 | {elapsed}일")
    msg = "\n".join(lines) or "현재 등록된 모니터링이 없습니다."
    await update.message.reply_text(msg)

async def all_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"[{user_id}] /all_cancel 호출")
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    count = 0
    # 각 챗의 chat_data dict 내부를 clear() 방식으로 초기화
    for chat_id, data in ctx.application.chat_data.items():
        task = data.get('task')
        if task:
            task.cancel()
            count += 1
        # 설정 및 상태 정보 삭제
        data.clear()
    await update.message.reply_text(f"✅ 전체 모니터링 종료: {count}건")

# --- 모니터링 루프 ---
async def monitor_loop(ctx: ContextTypes.DEFAULT_TYPE, user_id: int, settings: tuple):
    depart, arrive, d_date, r_date = settings
    start_time = ctx.chat_data['start_time']
    hist_file  = f"price_{user_id}_{depart}_{arrive}_{d_date}_{r_date}.json"
    old_price  = None
    if os.path.exists(hist_file):
        old_price = int(json.load(open(hist_file)).get("price", 0))

    while True:
        if (datetime.now() - start_time).days >= 30:
            await ctx.bot.send_message(user_id, "⏳ 30일 경과, 자동 종료됩니다.")
            ctx.chat_data.clear()
            logger.info(f"[{user_id}] 30일 경과 자동 종료")
            break

        link = (
            f"https://flight.naver.com/flights/international/"
            f"{depart}-{arrive}-{d_date}/"
            f"{arrive}-{depart}-{r_date}?adult=1&fareType=Y"
        )
        logger.info(f"[{user_id}] 크롤링 URL: {link}")

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Remote(command_executor=SELENIUM_HUB_URL, options=options)

        try:
            driver.get(link)
            WebDriverWait(driver, 40).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[class^="inlineFilter_FilterWrapper__"]'))
            )
            time.sleep(10)

            flight_list = driver.find_element(By.XPATH, '//*[@id="international-content"]/div/div[3]')
            flights     = flight_list.find_elements(By.XPATH, './div')
            logger.info(f"[{user_id}] 총 {len(flights)}개 항공권 탐색 완료")

            overall_price = None
            overall_info  = ""
            restricted_price = None
            restricted_info  = ""

            for idx, item in enumerate(flights, 1):
                text = item.text
                logger.debug(f"[{user_id}] 항공권[{idx}] 처리")
                if "경유" in text:
                    logger.debug(f"[{user_id}] 경유편 제외")
                    continue

                m_dep = re.search(rf'(\d{{2}}:\d{{2}}){depart}\s+(\d{{2}}:\d{{2}}){arrive}', text)
                m_ret = re.search(rf'(\d{{2}}:\d{{2}}){arrive}\s+(\d{{2}}:\d{{2}}){depart}', text)
                m_price = re.search(r'왕복\s([\d,]+)원', text)
                if not (m_dep and m_ret and m_price):
                    logger.debug(f"[{user_id}] 정보 누락, 스킵")
                    continue

                price = int(m_price.group(1).replace(",", ""))
                if overall_price is None or price < overall_price:
                    overall_price = price
                    overall_info = f"출국 {m_dep.group(1)}, 귀국 {m_ret.group(1)}, 가격 {price:,}원"
                    logger.info(f"[{user_id}] 전체 최저가 업데이트: {overall_price}")

                dep_time = to_time(m_dep.group(1))
                ret_time = to_time(m_ret.group(1))
                logger.debug(f"dep_time.hour={dep_time.hour}, ret_time.hour={ret_time.hour}")
                if dep_time.hour <= 12 and ret_time.hour >= 14:
                    if restricted_price is None or price < restricted_price:
                        restricted_price = price
                        restricted_info = (
                            f"출국: {m_dep.group(1)} → {m_dep.group(2)}\n"
                            f"귀국: {m_ret.group(1)} → {m_ret.group(2)}\n"
                            f"왕복 가격: {price:,}원"
                        )
                        logger.info(f"[{user_id}] 조건 최저가 업데이트: {restricted_price}")

            ctx.chat_data['lowest_price'] = restricted_price

            if restricted_price is not None and (old_price is None or restricted_price < old_price):
                msg = (
                    f"📉 {depart}→{arrive} {d_date}~{r_date} 가격 하락!\n"
                    f"[조건 최저가]\n{restricted_info}\n"
                    f"[전체 최저가]\n🛫 {overall_info}\n"
                    f"🔗 {link}"
                )
                await ctx.bot.send_message(user_id, msg)
                old_price = restricted_price
                with open(hist_file, "w") as f:
                    json.dump({"price": old_price}, f)
                logger.info(f"[{user_id}] 알림 전송 가격: 조건={restricted_price}, 전체={overall_price}")

            report = (
                f"🔍 조건 최저가:\n{restricted_info or '없음'}\n"
                f"🛫 전체 최저가:\n{overall_info or '없음'}"
            )
            await ctx.bot.send_message(user_id, report)

        except Exception:
            logger.exception(f"[{user_id}] 모니터링 중 예외 발생")
            await ctx.bot.send_message(user_id, "⚠️ 오류 발생, 재시도합니다.")
        finally:
            driver.quit()
            logger.info(f"[{user_id}] WebDriver 종료")

        await asyncio.sleep(30 * 60)

# --- 메인 함수 ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("monitor", monitor_cmd)],
        states={SETTING: [MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_setting)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("all_status", all_status))
    app.add_handler(CommandHandler("all_cancel", all_cancel))
    app.add_handler(conv)

    logger.info("✈️ Flight Bot 시작")
    app.run_polling()

if __name__ == "__main__":
    main()
