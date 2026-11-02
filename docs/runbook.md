# 실행 안내

## 처음 한 번
```bash
cp .env.example .env
# GENIO_FERNET_KEY 를 채운다
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
make setup            # make 가 없으면 아래 두 줄
# python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
# cd apps/web && npm install
```

## 검사
```bash
make check            # make 가 없으면: bash scripts/check.sh
```

## 전체 기동 (docker)
```bash
make up               # 또는 docker compose up --build -d
```
- 웹: http://localhost:5173
- API: http://localhost:8000/health
- API 문서: http://localhost:8000/docs
