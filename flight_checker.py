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
from zoneinfo import ZoneInfo
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
KST = ZoneInfo("Asia/Seoul")

# 유틸: URL 및 가격 파싱 로직 분리
def fetch_prices(depart: str, arrive: str, d_date: str, r_date: str):
    link = (
        f"https://flight.naver.com/flights/international/"
        f"{depart}-{arrive}-{d_date}/"
        f"{arrive}-{depart}-{r_date}?adult=1&fareType=Y"
    )
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Remote(command_executor=SELENIUM_HUB_URL, options=options)

    # 결과 초기화
    overall_price = None
    overall_info = ""
    restricted_price = None
    restricted_info = ""

    try:
        driver.get(link)
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[class^="inlineFilter_FilterWrapper__"]'))
        )
        time.sleep(5)

        elems = driver.find_elements(By.XPATH, '//*[@id="international-content"]/div/div[3]/div')
        for item in elems:
            text = item.text
            if "경유" in text:
                continue
            m_dep = re.search(rf'(\d{{2}}:\d{{2}}){depart}\s+(\d{{2}}:\d{{2}}){arrive}', text)
            m_ret = re.search(rf'(\d{{2}}:\d{{2}}){arrive}\s+(\d{{2}}:\d{{2}}){depart}', text)
            m_price = re.search(r'왕복\s([\d,]+)원', text)
            if not (m_dep and m_ret and m_price):
                continue

            price = int(m_price.group(1).replace(",", ""))
            # 전체 최저가
            if overall_price is None or price < overall_price:
                overall_price = price
                overall_info = f"출국 {m_dep.group(1)}, 귀국 {m_ret.group(1)}, 가격 {price:,}원"
            # 제한 조건 최저가
            dep_time = datetime.strptime(m_dep.group(1), "%H:%M")
            ret_time = datetime.strptime(m_ret.group(1), "%H:%M")
            if dep_time.hour < 12 and ret_time.hour >= 14:
                if restricted_price is None or price < restricted_price:
                    restricted_price = price
                    restricted_info = (
                        f"출국: {m_dep.group(1)} → {m_dep.group(2)}\n"
                        f"귀국: {m_ret.group(1)} → {m_ret.group(2)}\n"
                        f"왕복 가격: {price:,}원"
                    )
    except Exception as e:
        logger.exception(f"fetch_prices 오류: {e}")
    finally:
        driver.quit()

    return restricted_price, restricted_info, overall_price, overall_info, link

# 도움말 텍스트 생성
def help_text() -> str:
    admin_help = ""
    if ADMIN_IDS:
        admin_help = "\n관리자 명령:\n/all_status - 전체 상태 조회\n/all_cancel - 전체 감시 종료"
    return (
        "✈️ 30분마다 항공권 최저가 조회\n"
        "🛫 조건: 출발일 12시 이전, 도착일 14시 이후\n"
        "🛬 항공권 모니터링 봇 사용법:\n"
        "/monitor - 모니터링 시작 (예: ICN FUK 20251025 20251027)\n"
        "/status  - 내 설정 확인\n"
        "/cancel  - 모니터링 중단\n"
        "/help    - 도움말"
        + admin_help
    )

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
        return bool(re.fullmatch(r"\d{8}", d)) and datetime.strptime(d, "%Y%m%d")
    except:
        return False

async def monitor_setting(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    parts = update.message.text.strip().split()
    logger.info(f"[{user_id}] monitor_setting 입력: {parts}")
    if len(parts) != 4 or not valid_date(parts[2]) or not valid_date(parts[3]):
        await update.message.reply_text("❗ 형식 오류. 예: ICN FUK 20251025 20251027")
        return SETTING
    
    await update.message.reply_text("모니터링 설정 적용 중")

    depart, arrive, d_date, r_date = parts
    # 초기 가격 조회
    restricted, r_info, overall, o_info, link = await asyncio.get_event_loop().run_in_executor(
        None, fetch_prices, depart, arrive, d_date, r_date
    )
    # 이력 파일 저장
    hist_file = f"price_{user_id}_{depart}_{arrive}_{d_date}_{r_date}.json"
    with open(hist_file, "w") as f:
        json.dump({"restricted": restricted or 0, "overall": overall or 0}, f)
    # 저장
    ctx.chat_data['settings'] = (depart, arrive, d_date, r_date)
    ctx.chat_data['start_time'] = datetime.now(KST)
    ctx.chat_data['last_fetch'] = datetime.now(KST)
    ctx.chat_data['task'] = asyncio.create_task(monitor_loop(ctx, user_id, hist_file))
    # 초기 안내 메시지
    await update.message.reply_text(
        f"✅ 모니터링 시작: {depart}→{arrive} {d_date}~{r_date}\n"
        f"[조건 최저가]\n{r_info}\n"
        f"[전체 최저가]\n{o_info}\n"
        f"🔗 {link}"
    )
    return ConversationHandler.END

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = ctx.chat_data.get('settings')
    logger.info(f"[{user_id}] /status 호출")
    if not settings:
        await update.message.reply_text("현재 실행 중인 모니터링이 없습니다.")
        return
    depart, arrive, d_date, r_date = settings
    # 이력 로드
    hist_file = f"price_{user_id}_{depart}_{arrive}_{d_date}_{r_date}.json"
    data = json.load(open(hist_file)) if os.path.exists(hist_file) else {}
    restricted = data.get("restricted")
    overall = data.get("overall")
    elapsed = (datetime.now(KST) - ctx.chat_data['start_time']).days
    lf = ctx.chat_data.get('last_fetch')
    await update.message.reply_text(
        f"📋 현재 설정:\n"
        f"{depart}↔️{arrive} {d_date}~{r_date}\n"
        f"조건 최저가: {restricted or '없음':,}원\n"
        f"전체 최저가: {overall or '없음':,}원\n"
        f"마지막 조회: {lf.strftime('%Y-%m-%d %H:%M:%S')}\n"
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
    else:
        await update.message.reply_text("실행 중인 모니터링이 없습니다.")

async def all_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"[{user_id}] /all_status 호출")
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return
    lines=[]
    for chat_id, data in ctx.application.chat_data.items():
        settings = data.get('settings')
        if not settings: continue
        depart, arrive, d_date, r_date = settings
        hist_file=f"price_{chat_id}_{depart}_{arrive}_{d_date}_{r_date}.json"
        hist=json.load(open(hist_file)) if os.path.exists(hist_file) else {}
        restricted=hist.get("restricted"); overall=hist.get("overall")
        elapsed=(datetime.now(KST)-data.get('start_time')).days
        lines.append(f"{chat_id}: {depart}->{arrive} {d_date}~{r_date} | 제한:{restricted}원 | 전체:{overall}원 | {elapsed}일")
    await update.message.reply_text("\n".join(lines) or "현재 등록된 모니터링이 없습니다.")

async def all_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id=update.effective_user.id
    logger.info(f"[{user_id}] /all_cancel 호출")
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return
    count=0
    for data in ctx.application.chat_data.values():
        task=data.get('task')
        if task: task.cancel(); count+=1
        data.clear()
    await update.message.reply_text(f"✅ 전체 모니터링 종료: {count}건")

async def monitor_loop(ctx: ContextTypes.DEFAULT_TYPE, user_id: int, hist_file: str):
    settings = ctx.chat_data['settings']
    while True:
        try:
            depart, arrive, d_date, r_date = settings
            # 이력 로드
            data=json.load(open(hist_file)) if os.path.exists(hist_file) else {"restricted":0,"overall":0}
            old_restr, old_overall = data.get("restricted"), data.get("overall")
            # 최신 가격 조회
            restricted, r_info, overall, o_info, link = await asyncio.get_event_loop().run_in_executor(
                None, fetch_prices, depart, arrive, d_date, r_date
            )
            # 하락 감지
            notify=False
            if restricted and restricted < old_restr:
                notify=True
            if overall and overall < old_overall:
                notify=True
            if notify:
                msg=(
                    f"📉 {depart}->{arrive} {d_date}~{r_date} 가격 하락!\n"
                    f"[조건] {restricted or '없음'}원\n{r_info}\n"
                    f"[전체] {overall or '없음'}원\n{o_info}\n"
                    f"🔗 {link}"
                )
                await ctx.bot.send_message(user_id, msg)
                # 이력 업데이트
                data["restricted"]=restricted or old_restr
                data["overall"]=overall or old_overall
                data['last_fetch'] = datetime.now(KST)
                with open(hist_file,"w") as f: json.dump(data,f)

        except Exception as e:
            # 사용자에게도 알림
            logger.exception(f"[{user_id}] monitor_loop 중 예외 발생\n{e}")
            await ctx.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ 모니터링 중 오류가 발생했습니다:\n5분 후 재시도합니다."
            )
            # 짧게 대기 후 재시도
            await asyncio.sleep(5 * 60)
            continue

        await asyncio.sleep(30*60)

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
