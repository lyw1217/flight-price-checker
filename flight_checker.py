#!/usr/bin/env python3
"""
텔레그램 봇으로 30분마다 항공권 최저가 조회 및 알림 기능 제공
환경변수 설정 (필수):
- BOT_TOKEN         : Telegram 봇 토큰
- SELENIUM_HUB_URL  : Selenium Hub 주소 (기본: http://localhost:4444/wd/hub)
- ADMIN_IDS         : 관리자 ID 목록 (쉼표 구분)
- USER_AGENT        : (선택) Selenium 헤드리스 브라우저용 User-Agent
- MAX_MONITORS      : (선택) 사용자당 최대 모니터링 개수 (기본 3)
"""
import os
import re
import json
import time
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ConversationHandler,
    ContextTypes, filters, JobQueue
)
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 설정 및 초기화 ---
LOG_FILE = Path(__file__).parent / "flight_bot.log"
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

DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

KST = ZoneInfo("Asia/Seoul")
SETTING = 1

# 파일 패턴
PATTERN = re.compile(
    r"price_(?P<uid>\d+)_(?P<dep>[A-Z]{3})_(?P<arr>[A-Z]{3})_(?P<dd>\d{8})_(?P<rd>\d{8})\.json"
)

def format_datetime(dt: datetime) -> str:
    return dt.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')

# 항공권 조회 로직
def fetch_prices(depart: str, arrive: str, d_date: str, r_date: str):
    url = (
        f"https://flight.naver.com/flights/international/"
        f"{depart}-{arrive}-{d_date}/{arrive}-{depart}-{r_date}?adult=1&fareType=Y"
    )
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={USER_AGENT}")
    driver = webdriver.Remote(
        command_executor=SELENIUM_HUB_URL,
        options=options
    )

    overall_price = None
    overall_info = ""
    restricted_price = None
    restricted_info = ""
    try:
        driver.get(url)
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[class^="inlineFilter_FilterWrapper__"]')
            )
        )
        time.sleep(5)
        items = driver.find_elements(By.XPATH, '//*[@id="international-content"]/div/div[3]/div')
        for item in items:
            text = item.text
            if "경유" in text:
                continue
            m_dep = re.search(rf'(\d{{2}}:\d{{2}}){depart}\s+(\d{{2}}:\d{{2}}){arrive}', text)
            m_ret = re.search(rf'(\d{{2}}:\d{{2}}){arrive}\s+(\d{{2}}:\d{{2}}){depart}', text)
            m_price = re.search(r'왕복\s([\d,]+)원', text)
            if not (m_dep and m_ret and m_price):
                continue
            price = int(m_price.group(1).replace(",", ""))
            if overall_price is None or price < overall_price:
                overall_price = price
                overall_info = f"출국 {m_dep.group(1)}, 귀국 {m_ret.group(1)}, 가격 {price:,}원"
            dep_t = datetime.strptime(m_dep.group(1), "%H:%M")
            ret_t = datetime.strptime(m_ret.group(1), "%H:%M")
            if dep_t.hour < 12 and ret_t.hour >= 14:
                if restricted_price is None or price < restricted_price:
                    restricted_price = price
                    restricted_info = (
                        f"출국: {m_dep.group(1)} → {m_dep.group(2)}\n"
                        f"귀국: {m_ret.group(1)} → {m_ret.group(2)}\n"
                        f"왕복 가격: {price:,}원"
                    )
    except Exception as ex:
        logger.exception(f"fetch_prices 오류: {ex}")
    finally:
        driver.quit()

    return restricted_price, restricted_info, overall_price, overall_info, url

# 도움말 텍스트
async def help_text() -> str:
    admin_help = ""
    if ADMIN_IDS:
        admin_help = "\n관리자 명령:\n/all_status - 전체 상태 조회\n/all_cancel - 전체 모니터링 취소"
    return (
        "✈️ 30분마다 네이버 항공권 최저가 조회\n"
        "🛫 조건: 출발일 12시 이전, 도착일 14시 이후\n"
        "사용법:\n"
        "/monitor - 모니터링 시작 (예: ICN FUK 20251025 20251027)\n"
        "/status  - 내 설정 확인\n"
        "/cancel  - 모니터링 취소\n"
        "/help    - 도움말"
        + admin_help
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await help_text())
    logger.info(f"[{update.effective_user.id}] /help 호출")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await help_text())
    logger.info(f"[{update.effective_user.id}] /start 호출")

# 모니터 명령 핸들러
async def monitor_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ 입력 예시: ICN FUK 20251025 20251027 (YYYYMMDD)")
    return SETTING

# 유효 날짜 체크
from datetime import datetime as _dt

def valid_date(d: str) -> bool:
    try:
        _dt.strptime(d, "%Y%m%d")
        return True
    except ValueError:
        return False

async def monitor_setting(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().split()
    if len(text) != 4 or not (valid_date(text[2]) and valid_date(text[3])):
        await update.message.reply_text("❗ 형식 오류. 예: ICN FUK 20251025 20251027")
        return SETTING

    depart, arrive, d_date, r_date = text
    user_id = update.effective_user.id
    existing = [p for p in DATA_DIR.iterdir() if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id]
    if len(existing) >= MAX_MONITORS:
        await update.message.reply_text(f"❗ 최대 {MAX_MONITORS}개까지 모니터링할 수 있습니다.")
        return ConversationHandler.END

    await update.message.reply_text("✅ 모니터링 설정 완료. 첫 조회 중...")
    loop = asyncio.get_running_loop()
    restricted, r_info, overall, o_info, link = await loop.run_in_executor(None, fetch_prices, depart, arrive, d_date, r_date)
    hist_path = DATA_DIR / f"price_{user_id}_{depart}_{arrive}_{d_date}_{r_date}.json"
    start_time = format_datetime(datetime.now())
    hist_path.write_text(json.dumps({
        "start_time": start_time,
        "restricted": restricted or 0,
        "overall": overall or 0,
        "last_fetch": format_datetime(datetime.now())
    }), encoding="utf-8")

    job = ctx.application.job_queue.run_repeating(
        monitor_job,  # 콜백 함수
        interval=timedelta(minutes=30),
        first=timedelta(seconds=0),
        name=str(hist_path),      
        data={                    
            "chat_id": user_id,
            "settings": (depart, arrive, d_date, r_date),
            "hist_path": str(hist_path)
        }
    )

    monitors = ctx.application.bot_data.setdefault("monitors", {})
    monitors.setdefault(user_id, []).append({
        "settings":   (depart, arrive, d_date, r_date),
        "start_time": datetime.now(KST),
        "hist_path":  str(hist_path),
        "job":        job
    })

    await update.message.reply_text(
        f"✅ 모니터링 시작: {depart}→{arrive} {d_date}~{r_date}\n"
        f"[조건 최저가]\n{r_info}\n"
        f"[전체 최저가]\n{o_info}\n"
        f"🔗 {link}"
    )
    return ConversationHandler.END

async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    chat_id = data['chat_id']
    depart, arrive, d_date, r_date = data['settings']
    hist_path = Path(data['hist_path'])

    state = json.loads(hist_path.read_text(encoding='utf-8'))
    old_restr = state.get("restricted", 0)
    old_overall = state.get("overall", 0)
    start_time_str = state.get("start_time")

    loop = asyncio.get_running_loop()
    restricted, r_info, overall, o_info, link = await loop.run_in_executor(None, fetch_prices, depart, arrive, d_date, r_date)
    notify = False
    if restricted and restricted < old_restr:
        notify = True
    if overall and overall < old_overall:
        notify = True

    if notify:
        msg = (
            f"📉 {depart}->{arrive} {d_date}~{r_date} 가격 하락!\n"
            f"[조건] {restricted or '없음'}원\n{r_info}\n"
            f"[전체] {overall or '없음'}원\n{o_info}\n"
            f"🔗 {link}"
        )
        await context.bot.send_message(chat_id, msg)

    new_state = {
        "start_time": start_time_str,
        "restricted": restricted or old_restr,
        "overall": overall or old_overall,
        "last_fetch": format_datetime(datetime.now())
    }
    hist_path.write_text(json.dumps(new_state), encoding='utf-8')

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    files = sorted([
        p for p in DATA_DIR.iterdir()
        if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id
    ])
    if not files:
        await update.message.reply_text("현재 실행 중인 모니터링이 없습니다.")
        return

    now = datetime.now(KST)
    msg_lines = ["📋 현재 설정:"]

    for idx, hist in enumerate(files, start=1):
        info = PATTERN.fullmatch(hist.name).groupdict()
        data = json.loads(hist.read_text(encoding='utf-8'))

        start_dt = datetime.strptime(
            data['start_time'], '%Y-%m-%d %H:%M:%S'
        ).replace(tzinfo=KST)
        elapsed = (now - start_dt).days

        msg_lines.append(f"{idx}. {info['dep']}↔️{info['arr']} {info['dd']}~{info['rd']}")
        msg_lines.append(f"• 조건 최저가 | {data['restricted']:,}원")
        msg_lines.append(f"• 전체 최저가 | {data['overall']:,}원")
        msg_lines.append(f"• 조회 시작일 | {data['start_time']}")
        msg_lines.append(f"• 마지막 조회 | {data['last_fetch']}")
        msg_lines.append(f"• 경과된 일수 | {elapsed}일(최대 30일)")

    await update.message.reply_text("\n".join(msg_lines))


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = update.message.text.strip().split()

    # 인자가 정확히 하나만 있어야 처리
    if len(args) != 2:
        await update.message.reply_text("❗ 올바른 명령 형식: `/cancel <번호>` 또는 `/cancel all`", parse_mode="Markdown")
        return

    key = args[1].lower()
    # 디스크에 저장된 JSON 파일 목록 조회
    files = sorted([
        p for p in DATA_DIR.iterdir()
        if PATTERN.fullmatch(p.name) and int(PATTERN.fullmatch(p.name).group('uid')) == user_id
    ])

    if key == 'all':
        # 전체 삭제
        for hist in files:
            hist.unlink()
            # JobQueue에서도 제거
            for job in ctx.application.job_queue.get_jobs_by_name(str(hist)):
                job.schedule_removal()
        await update.message.reply_text("✅ 전체 모니터링을 취소했습니다.")
        return

    if key.isdigit():
        idx = int(key) - 1
        if idx < 0 or idx >= len(files):
            await update.message.reply_text("❗ 유효하지 않은 번호입니다.")
            return

        target = files[idx]
        # 파일 삭제
        target.unlink()
        # JobQueue에서 제거
        for job in ctx.application.job_queue.get_jobs_by_name(str(target)):
            job.schedule_removal()

        await update.message.reply_text(f"✅ {key}번 모니터링을 취소했습니다.")
        return

    # 그 외 잘못된 인자
    await update.message.reply_text("❗ 올바른 명령 형식: `/cancel <번호>` 또는 `/cancel all`", parse_mode="Markdown")

# 관리자 전용: 전체 상태 조회
async def all_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    monitors = ctx.application.bot_data.get("monitors", {})
    # 모든 모니터링 항목을 펼쳐서 리스트로
    entries = []
    for uid, mons in monitors.items():
        for mon in mons:
            entries.append((uid, mon))
    total = len(entries)
    if total == 0:
        await update.message.reply_text("현재 등록된 모니터링이 없습니다.")
        return

    # 메시지 생성
    msg_lines = [f"📋 전체 모니터링 상태 ({total}건):"]
    now = datetime.now(KST)
    for idx, (uid, mon) in enumerate(entries, start=1):
        dep, arr, dd, rd = mon["settings"]
        hist = Path(mon["hist_path"])
        data = json.loads(hist.read_text(encoding="utf-8")) if hist.exists() else {}
        restricted = data.get("restricted", 0)
        overall = data.get("overall", 0)
        last_fetch = data.get("last_fetch", "")
        start_time = data.get("start_time", "")
        # 경과일 계산
        if start_time:
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            elapsed = (now - start_dt).days
        else:
            elapsed = 0

        msg_lines.append(f"{idx}. {uid} | {dep}→{arr} {dd}~{rd}")
        msg_lines.append(f"   • 조건최저가: {restricted:,}원\n   • 전체최저가: {overall:,}원")
        msg_lines.append(f"   • 조회시작일: {start_time}\n   • 마지막조회: {last_fetch}")
        msg_lines.append(f"   • 경과된일수: {elapsed}일")

    full_message = "\n".join(msg_lines)
    # 텔레그램 최대 메시지 길이(4096)에 맞춰 분할 전송
    MAX_LEN = 4000
    for i in range(0, len(full_message), MAX_LEN):
        chunk = full_message[i:i+MAX_LEN]
        await update.message.reply_text(chunk)


# 관리자 전용: 전체 모니터링 취소
async def all_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 관리자 권한이 필요합니다.")
        return

    monitors = ctx.application.bot_data.get("monitors", {})
    count = 0

    for uid, mons in list(monitors.items()):
        for mon in mons:
            job = mon.get("job")
            if job:
                job.schedule_removal()
                count += 1
            hist = Path(mon.get("hist_path", ""))
            if hist.exists():
                hist.unlink()
        # 해당 uid의 리스트 삭제
        monitors.pop(uid, None)

    await update.message.reply_text(f"✅ 전체 모니터링 종료: {count}건")

async def on_startup(app):
    now = datetime.now(KST)
    monitors = app.bot_data.setdefault("monitors", {})

    for hist_path in DATA_DIR.glob("price_*.json"):
        m = PATTERN.fullmatch(hist_path.name)
        if not m:
            continue

        # JSON에서 start_time, last_fetch 파싱
        data = json.loads(hist_path.read_text(encoding="utf-8"))
        start_time_str = data.get("start_time")
        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except Exception:
            start_time = now  # 파싱 실패 시 현재 시각 사용

        last_fetch_str = data.get("last_fetch")
        try:
            last_fetch = datetime.strptime(last_fetch_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except Exception:
            # 파싱 실패 시 즉시 실행
            delta = timedelta(minutes=999)
        else:
            delta = now - last_fetch

        # 지연 시간 계산
        interval = timedelta(minutes=30)
        if delta >= interval:
            first_delay = timedelta(seconds=0)
        else:
            first_delay = interval - delta

        uid = int(m.group("uid"))
        dep, arr, dd, rd = m.group("dep"), m.group("arr"), m.group("dd"), m.group("rd")
        
        job = app.job_queue.run_repeating(
            monitor_job,
            interval=interval,
            first=first_delay,
            name=str(hist_path),
            data={
                "chat_id": uid,
                "settings": (dep, arr, dd, rd),
                "hist_path": str(hist_path)
            }
        )

        monitors.setdefault(uid, []).append({
            "settings":   (dep, arr, dd, rd),
            "start_time": start_time,
            "hist_path":  str(hist_path),
            "job":        job
        })

        logger.info(f"▶ 복원된 모니터링: {hist_path.name}")

def main():
    app = ApplicationBuilder()\
        .token(BOT_TOKEN)\
        .post_init(on_startup)\
        .build()

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
