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
ENV DATA_RETENTION_DAYS=30 \
    MAX_MONITORS=3

CMD ["python", "flight_checker.py"]