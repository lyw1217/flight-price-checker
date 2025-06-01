FROM python:3.10-slim

# 시스템 패키지 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /app

# 파이썬 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 코드 복사
COPY . .

# 데이터 디렉토리 생성
RUN mkdir -p /data

# 환경변수 기본값 설정
ENV SELENIUM_HUB_URL=http://localhost:4444/wd/hub \
    USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36" \
    MAX_MONITORS=5 \
    MAX_WORKERS=5 \
    FILE_WORKERS=5 \
    DATA_RETENTION_DAYS=30 \
    CONFIG_RETENTION_DAYS=7 \
    LOG_LEVEL=INFO \
    BOT_TOKEN="" \
    ADMIN_IDS=""

# 주의: BOT_TOKEN은 필수 환경변수입니다. 컨테이너 실행 시 반드시 설정해주세요.
# 예: docker run -e BOT_TOKEN=your_actual_token ...

CMD ["python", "flight_checker.py"]