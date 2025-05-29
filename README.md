# 항공권 최저가 조회 봇

텔레그램 봇을 통해 항공권 최저가를 주기적으로 조회하고 가격 하락 시 알림을 보내주는 서비스입니다.

## 주요 기능

- 30분마다 항공권 가격 자동 조회
- 가격 하락 시 텔레그램으로 알림
- 시간대 또는 시각 기반의 항공편 필터링
- 사용자별 다중 모니터링 지원
- 관리자 기능 (전체 현황 조회, 일괄 취소)

## 설치 방법

1. Python 3.8 이상 설치
2. 필요한 패키지 설치:
```bash
pip install -r requirements.txt
```

## 환경 변수 설정

필수 환경변수:
- `BOT_TOKEN`: Telegram 봇 토큰
- `SELENIUM_HUB_URL`: Selenium Hub 주소 (기본: http://localhost:4444/wd/hub)
- `ADMIN_IDS`: 관리자 ID 목록 (쉼표 구분)

선택 환경변수:
- `USER_AGENT`: Selenium 헤드리스 브라우저용 User-Agent
- `MAX_MONITORS`: 사용자당 최대 모니터링 개수 (기본: 3)
- `DATA_RETENTION_DAYS`: 모니터링 데이터 보관 기간 (일, 기본: 30)
- `CONFIG_RETENTION_DAYS`: 사용자 설정 파일 보관 기간 (일, 기본: 7)

## 실행 방법

```bash
python flight_checker.py
```

## 봇 명령어

기본 명령어:
- `/monitor` - 새로운 모니터링 시작
- `/status` - 모니터링 현황 확인
- `/cancel` - 모니터링 취소
- `/settings` - 시간 제한 설정
- `/airport` - 공항 코드 목록
- `/help` - 도움말

관리자 명령어:
- `/allstatus` - 전체 모니터링 현황
- `/allcancel` - 전체 모니터링 취소

## 테스트

프로젝트는 다음과 같은 구조로 테스트 코드가 구성되어 있습니다:

```
flight-price-checker/
├── flight_checker.py      # 메인 코드
└── tests/                 # 테스트 코드 디렉토리
    ├── __init__.py       # 테스트 패키지 초기화 파일
    └── test_flight_checker.py  # 테스트 코드
```

### 테스트 실행 방법

1. 전체 테스트 실행:
```bash
python -m unittest discover tests
```

2. 특정 테스트 파일 실행:
```bash
python -m unittest tests/test_flight_checker.py
```

3. 특정 테스트 클래스나 메소드 실행:
```bash
python -m unittest tests.test_flight_checker.TestFlightChecker
python -m unittest tests.test_flight_checker.TestFlightChecker.test_valid_date
```

### 테스트 범위

현재 구현된 테스트:
- URL 유효성 검증
- 항공편 정보 파싱
- 시간 제한 조건 체크
- 날짜 유효성 검사
- 공항 코드 유효성 검사

## 데이터 저장

- 모니터링 데이터: `/data/price_*.json`
- 사용자 설정: `/data/user_configs/config_*.json`
- 로그 파일: `/data/logs/flight_bot.log`

## 주의사항

1. 데이터 보관 기간
   - 모니터링 데이터: `DATA_RETENTION_DAYS`일 후 자동 삭제
   - 사용자 설정: 마지막 활동으로부터 `CONFIG_RETENTION_DAYS`일 후 자동 삭제

2. 시간 제한 설정
   - 시간대 설정: 새벽(00-06), 오전1(06-09), 오전2(09-12), 오후1(12-15), 오후2(15-18), 밤1(18-21), 밤2(21-24)
   - 시각 설정: 가는 편은 설정 시각 이전, 오는 편은 설정 시각 이후 항공편 검색

## 라이선스

MIT License
