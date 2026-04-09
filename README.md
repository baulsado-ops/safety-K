# 현장 위험성 체크리스트 생성기

제조업 사업장/건설현장 사진을 업로드하면, 작업 시작 전 위험성 체크리스트와 위험도 점수, 주의사항, 예방대책을 자동으로 생성하는 도구입니다.

## 적용 라이브러리

- 웹/API: `Flask`
- LLM 분석: `openai`
- 객체 인식(선택): `Ultralytics YOLO-World` + `OpenCV`

객체 인식 라이브러리를 설치하면 업로드 이미지에서 작업자/안전모/조끼/장비/고소작업 요소 등을 먼저 탐지하고, 그 결과를 기반으로 위험성 체크리스트와 위험도 점수를 산출합니다.

## 배포 (Vercel)

이 프로젝트는 `main.py`(Flask 엔트리포인트) 기준으로 Vercel Python Runtime에서 동작합니다.

1. GitHub 연동 후 Vercel에 Import
2. 프로젝트 환경 변수 설정
   - `OPENAI_API_KEY` (필수: 실분석)
   - `OPENAI_MODEL` (선택, 기본: `gpt-4.1-mini`)
3. Deploy

`OPENAI_API_KEY`가 없으면 데모 분석 결과를 반환합니다.

참고: Vercel Serverless 환경에서는 `ultralytics/opencv` 추론이 제한될 수 있습니다. 이 경우 앱은 자동으로 일반 위험성 체크리스트 기준(보수적 점수)으로 폴백합니다.

## 로컬 실행 (Flask)

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env
# .env에 OPENAI_API_KEY 입력
python main.py
```

브라우저에서 `http://127.0.0.1:5000` 접속

### 객체 인식 엔진까지 사용하려면 (권장)

```bash
pip install -r vision_requirements.txt
```

환경 변수(선택):

- `VISION_MODEL` 기본값: `yolov8s-worldv2.pt`
- `VISION_CONF` 기본값: `0.20`

## 기존 Streamlit 앱

초기 Streamlit 버전은 `app.py`에 유지되어 있으며, 필요 시 아래로 실행할 수 있습니다.

```bash
streamlit run app.py
```

## 주요 기능

- 사진 기반 위험요인 분석
- 객체 인식 기반 자동 카운팅(작업자/PPE/장비/고소작업 요소 등)
- 작업 전 체크리스트 자동 생성(10개 이상)
- 종합 위험도 점수(0~100) 및 위험등급 산출
- 위험요인별 주의사항 + 예방대책 제시

## 주의

- 본 도구는 안전관리자 판단을 보조하는 용도입니다.
- 실제 작업 허가/통제는 현장 책임자 및 법적 기준에 따라 최종 검토가 필요합니다.
