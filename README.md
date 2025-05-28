# flight-price-checker
# 네이버 항공권 가격 알리미 봇 🛫

네이버 항공권의 가격을 주기적으로 모니터링하고 텔레그램을 통해 최저가를 알려주는 봇입니다.

## 주요 기능 🌟

- 30분 간격으로 항공권 가격 자동 조회
- 출발/도착 시간대 설정 가능 (시간대 또는 특정 시각 기준)
- 텔레그램을 통한 실시간 가격 알림
- 사용자별 최대 3개 항공권 동시 모니터링
- 관리자 전용 명령어 지원

## 설치 방법 🔧

### 필수 요구사항
- Python 3.10 이상
- Docker (선택사항)
- Selenium Grid/Standalone (Chrome)

### 환경변수 설정
```bash
# 필수 환경변수
BOT_TOKEN=your_telegram_bot_token
SELENIUM_HUB_URL=http://localhost:4444/wd/hub
ADMIN_IDS=admin_telegram_id1,admin_telegram_id2

# 선택적 환경변수
USER_AGENT=your_custom_user_agent
MAX_MONITORS=3  # 사용자당 최대 모니터링 개수
DATA_RETENTION_DAYS=30  # 데이터 보관 기간(일)
```

### Docker로 실행하기
```bash
docker build -t flight-price-checker .
docker run -d \
  -e BOT_TOKEN=your_token \
  -e SELENIUM_HUB_URL=http://selenium:4444/wd/hub \
  -e ADMIN_IDS=your_admin_ids \
  -v /path/to/data:/data \
  flight-price-checker
```

## 사용 방법 📱

### 기본 명령어
- `/start` - 봇 시작
- `/help` - 도움말
- `/monitor` - 새로운 항공권 모니터링 시작
- `/status` - 현재 모니터링 중인 항공권 상태 확인
- `/cancel` - 모니터링 취소
- `/settings` - 시간 설정 확인 및 변경
- `/airport` - 공항 코드 목록 확인

### 시간 설정
1. 시간대로 설정
   - 가는 편: `/set 가는편 시간대 오전1 오전2`
   - 오는 편: `/set 오는편 시간대 오후1 오후2 밤1`

2. 특정 시각으로 설정
   - 가는 편: `/set 가는편 시각 9` (09:00 이전 출발)
   - 오는 편: `/set 오는편 시각 15` (15:00 이후 출발)

### 시간대 구분
- 새벽 (00-06)
- 오전1 (06-09)
- 오전2 (09-12)
- 오후1 (12-15)
- 오후2 (15-18)
- 밤1 (18-21)
- 밤2 (21-24)

## 관리자 전용 기능 👑
- `/allstatus` - 모든 사용자의 모니터링 상태 확인
- `/allcancel` - 모든 모니터링 작업 취소

## 데이터 저장 📁
- 모든 데이터는 `/data` 디렉토리에 저장
- 사용자 설정: `/data/user_configs/`
- 로그 파일: `/data/logs/flight_bot.log`

## 의존성 패키지 📦
- selenium
- requests
- python-telegram-bot[job-queue]>=22.0
# 네이버 항공권 가격 알리미 봇 🛫

네이버 항공권의 가격을 주기적으로 모니터링하고 텔레그램을 통해 최저가를 알려주는 봇입니다.

## 주요 기능 🌟

- 30분 간격으로 항공권 가격 자동 조회
- 출발/도착 시간대 설정 가능 (시간대 또는 특정 시각 기준)
- 텔레그램을 통한 실시간 가격 알림
- 사용자별 최대 3개 항공권 동시 모니터링
- 관리자 전용 명령어 지원

## 설치 방법 🔧

### 필수 요구사항
- Python 3.10 이상
- Docker (선택사항)
- Selenium Grid/Standalone (Chrome)

### 환경변수 설정
```bash
# 필수 환경변수
BOT_TOKEN=your_telegram_bot_token
SELENIUM_HUB_URL=http://localhost:4444/wd/hub
ADMIN_IDS=admin_telegram_id1,admin_telegram_id2

# 선택적 환경변수
USER_AGENT=your_custom_user_agent
MAX_MONITORS=3  # 사용자당 최대 모니터링 개수
DATA_RETENTION_DAYS=30  # 데이터 보관 기간(일)
```

### Docker로 실행하기
```bash
docker build -t flight-price-checker .
docker run -d \
  -e BOT_TOKEN=your_token \
  -e SELENIUM_HUB_URL=http://selenium:4444/wd/hub \
  -e ADMIN_IDS=your_admin_ids \
  -v /path/to/data:/data \
  flight-price-checker
```

## 사용 방법 📱

### 기본 명령어
- `/start` - 봇 시작
- `/help` - 도움말
- `/monitor` - 새로운 항공권 모니터링 시작
- `/status` - 현재 모니터링 중인 항공권 상태 확인
- `/cancel` - 모니터링 취소
- `/settings` - 시간 설정 확인 및 변경
- `/airport` - 공항 코드 목록 확인

### 시간 설정
1. 시간대로 설정
   - 가는 편: `/set 가는편 시간대 오전1 오전2`
   - 오는 편: `/set 오는편 시간대 오후1 오후2 밤1`

2. 특정 시각으로 설정
   - 가는 편: `/set 가는편 시각 9` (09:00 이전 출발)
   - 오는 편: `/set 오는편 시각 15` (15:00 이후 출발)

### 시간대 구분
- 새벽 (00-06)
- 오전1 (06-09)
- 오전2 (09-12)
- 오후1 (12-15)
- 오후2 (15-18)
- 밤1 (18-21)
- 밤2 (21-24)

## 관리자 전용 기능 👑
- `/allstatus` - 모든 사용자의 모니터링 상태 확인
- `/allcancel` - 모든 모니터링 작업 취소

## 데이터 저장 📁
- 모든 데이터는 `/data` 디렉토리에 저장
- 사용자 설정: `/data/user_configs/`
- 로그 파일: `/data/logs/flight_bot.log`

## 의존성 패키지 📦
- selenium
- requests
- python-telegram-bot[job-queue]>=22.0
