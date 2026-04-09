import base64
import json
import os
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI

load_dotenv()

app = Flask(__name__)
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """
당신은 대한민국 제조업/건설현장 산업안전 전문 컨설턴트입니다.
입력 이미지를 보고 작업 시작 전(TBM/작업전 안전점검) 관점으로 위험요인을 분석하세요.
반드시 JSON만 출력하세요. 설명 문장, 마크다운, 코드블록을 출력하면 안 됩니다.

출력 스키마:
{
  "site_type": "manufacturing | construction | unknown",
  "overall_risk_score": 0-100 정수,
  "risk_level": "낮음 | 보통 | 높음 | 매우높음",
  "summary": "한 문단 요약",
  "checklist": [
    {
      "category": "PPE | 전기 | 화재폭발 | 중장비 | 추락낙하 | 협착끼임 | 화학물질 | 정리정돈 | 기타",
      "item": "점검 항목",
      "status": "미확인",
      "why": "위험 근거",
      "action": "즉시 조치/예방대책"
    }
  ],
  "hazards": [
    {
      "title": "위험요인명",
      "severity": 1-5 정수,
      "likelihood": 1-5 정수,
      "risk_score": 1-25 정수,
      "warning": "주의사항",
      "prevention": "예방대책"
    }
  ],
  "priority_actions": ["즉시 실행 우선조치"],
  "legal_notes": ["적용 가능한 일반 안전수칙/법적 유의사항(구체 조문 번호 단정 금지)"]
}

규칙:
- checklist는 최소 10개 이상, hazards는 최소 5개 이상 작성.
- 사진에서 명확하지 않은 내용은 추정이라고 명시하거나 보수적으로 작성.
- 위험도 점수는 현장 가시위험 + 통제수단 부재 가능성을 반영.
- 한국어로 작성.
""".strip()

MOCK_RESULT = {
    "site_type": "unknown",
    "overall_risk_score": 67,
    "risk_level": "높음",
    "summary": "OPENAI_API_KEY 미설정으로 데모 분석 결과를 표시합니다. 배포 환경 변수에 API 키를 설정하면 실제 이미지 분석이 동작합니다.",
    "checklist": [
        {
            "category": "PPE",
            "item": "안전모/보안경/안전화 착용 여부",
            "status": "미확인",
            "why": "기본 보호구 미착용 시 두부/안구/족부 부상 위험이 큼",
            "action": "작업자 전원 PPE 착용 후 미착용자 출입 통제",
        },
        {
            "category": "정리정돈",
            "item": "통로 및 작업구역 장애물 제거",
            "status": "미확인",
            "why": "통로 적치물은 걸림/넘어짐 사고 유발",
            "action": "통로 폭 확보, 불필요 자재 즉시 반출",
        },
        {
            "category": "전기",
            "item": "임시 배선 피복 손상/누전차단기 확인",
            "status": "미확인",
            "why": "손상 배선은 감전/화재 위험",
            "action": "손상 케이블 교체 및 누전차단기 시험",
        },
        {
            "category": "중장비",
            "item": "장비 작업반경 출입통제",
            "status": "미확인",
            "why": "장비 선회/후진 시 충돌 위험",
            "action": "작업반경 라바콘/신호수 배치",
        },
        {
            "category": "추락낙하",
            "item": "고소부 안전난간/개구부 덮개 설치",
            "status": "미확인",
            "why": "고소·개구부 주변은 중대재해 가능성 높음",
            "action": "난간 기준 준수 및 개구부 잠금식 덮개 설치",
        },
        {
            "category": "화재폭발",
            "item": "용접·절단 작업 시 화기관리",
            "status": "미확인",
            "why": "비산불티로 인한 화재 가능",
            "action": "소화기 비치, 가연물 제거, 화재감시자 지정",
        },
        {
            "category": "협착끼임",
            "item": "회전체/가동부 방호장치 확인",
            "status": "미확인",
            "why": "노출된 회전체는 협착·절단 사고 유발",
            "action": "방호커버 복구 후 시운전",
        },
        {
            "category": "화학물질",
            "item": "용기 라벨 및 MSDS 비치 여부",
            "status": "미확인",
            "why": "물질 오인 사용 시 중독/화재 위험",
            "action": "표준 라벨 부착, 취급자 교육",
        },
        {
            "category": "기타",
            "item": "신규 작업자 안전 브리핑(TBM) 실시",
            "status": "미확인",
            "why": "작업 절차 미숙지로 인적오류 증가",
            "action": "작업 전 10분 TBM 시행",
        },
        {
            "category": "기타",
            "item": "비상대피 동선 및 연락체계 점검",
            "status": "미확인",
            "why": "사고 시 초기 대응 지연 위험",
            "action": "대피로 표지/비상연락망 재확인",
        },
    ],
    "hazards": [
        {
            "title": "보호구 미착용 가능성",
            "severity": 4,
            "likelihood": 3,
            "risk_score": 12,
            "warning": "작업자 상해 발생 가능성이 높습니다.",
            "prevention": "작업 시작 전 PPE 착용 점검표 확인 및 현장 순찰",
        },
        {
            "title": "통로 장애물",
            "severity": 3,
            "likelihood": 4,
            "risk_score": 12,
            "warning": "넘어짐 및 운반 중 2차 사고 우려",
            "prevention": "정리정돈 담당자 지정, 2시간 주기 점검",
        },
        {
            "title": "전기 위험",
            "severity": 5,
            "likelihood": 2,
            "risk_score": 10,
            "warning": "감전/화재로 중대사고로 이어질 수 있습니다.",
            "prevention": "절연 상태 확인, 누전차단기 시험, 임시배선 최소화",
        },
        {
            "title": "장비 충돌 위험",
            "severity": 4,
            "likelihood": 3,
            "risk_score": 12,
            "warning": "장비-근로자 동선 간섭이 의심됩니다.",
            "prevention": "동선 분리, 신호수 배치, 후진경보 점검",
        },
        {
            "title": "추락/낙하 위험",
            "severity": 5,
            "likelihood": 3,
            "risk_score": 15,
            "warning": "고소 작업 또는 개구부 주변 작업 시 중대재해 위험",
            "prevention": "난간/안전대/개구부 덮개 적용 및 작업허가제 운용",
        },
    ],
    "priority_actions": [
        "작업 시작 전 10분 TBM으로 핵심 위험 3가지 공유",
        "PPE 미착용자 즉시 작업 배제",
        "고위험 구역 출입통제 및 책임자 지정",
    ],
    "legal_notes": [
        "산업안전보건법 및 관련 고시에 따른 기본 안전조치 준수 필요",
        "구체 법조문 적용은 현장 업종/공정별 안전관리자 검토가 필요",
    ],
}


def parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json", "", 1).strip()
    return json.loads(stripped)


def analyze_with_openai(image_data_url: str, extra_context: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return MOCK_RESULT

    client = OpenAI(api_key=api_key)

    user_instruction = (
        "이미지를 분석해 작업시작 전 위험성평가 결과를 JSON으로 작성하세요."
        f" 추가 현장 정보: {extra_context or '없음'}"
    )

    response = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_instruction},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            },
        ],
        max_output_tokens=1800,
    )
    return parse_json(response.output_text)


@app.get("/")
def home() -> str:
    return render_template("index.html")


@app.post("/api/analyze")
def analyze() -> Any:
    image = request.files.get("image")
    if image is None:
        return jsonify({"error": "image 파일이 필요합니다."}), 400

    mime = image.mimetype or "image/jpeg"
    encoded = base64.b64encode(image.read()).decode("utf-8")
    image_data_url = f"data:{mime};base64,{encoded}"
    extra_context = request.form.get("extra_context", "")

    try:
        result = analyze_with_openai(image_data_url, extra_context)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True)
