FROM apify/actor-python:3.11

# a_bogus 서명은 순수 Python(SM3 + RC4) — Node.js 의존 없음.
# TikTok 액터의 xbogus.js Node 서브프로세스 패턴과 다른 점.

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

CMD ["python", "src/main.py"]
