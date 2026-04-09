import base64
import json
import os
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI
from werkzeug.exceptions import RequestEntityTooLarge

from vision_risk import CvRiskSummary, analyze_cv

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "4")) * 1024 * 1024
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """
당신은 대한민국 제조업/건설현장 작업전 위험성평가 전문가입니다.
입력 이미지와 CV 사전분석 결과를 종합해 JSON만 출력하세요.
마크다운/코드블록/설명문을 출력하면 안 됩니다.

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
      "status": "미확인 | 양호 추정 | 미흡 추정 | 필요 | 해당없음",
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
  "legal_notes": ["적용 가능한 일반 안전수칙/법적 유의사항"]
}

규칙:
- checklist 최소 10개 이상, hazards 최소 5개 이상
- 불확실한 내용은 추정으로 표기
- 한국어로 작성
""".strip()


def parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json", "", 1).strip()
    return json.loads(stripped)


def _rule_based_payload(cv: CvRiskSummary) -> dict[str, Any]:
    return {
        "site_type": "unknown",
        "overall_risk_score": cv.overall_risk_score,
        "risk_level": cv.risk_level,
        "summary": cv.summary,
        "checklist": cv.checklist,
        "hazards": cv.hazards,
        "priority_actions": cv.priority_actions,
        "legal_notes": [
            "산업안전보건법 및 관련 고시에 따른 기본 안전조치 준수 필요",
            "구체 법조문 적용은 업종/공정별 안전관리자 검토 필요",
        ],
        "cv_meta": {
            "enabled": cv.enabled,
            "engine": cv.engine,
            "counts": cv.counts,
            "detections": cv.detections,
        },
    }


def analyze_with_openai(image_data_url: str, extra_context: str, cv: CvRiskSummary) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _rule_based_payload(cv)

    client = OpenAI(api_key=api_key)
    cv_hint = {
        "cv_engine": cv.engine,
        "cv_enabled": cv.enabled,
        "cv_counts": cv.counts,
        "cv_summary": cv.summary,
        "cv_hazards": cv.hazards,
    }

    user_instruction = (
        "이미지와 CV 사전분석 결과를 종합해 작업시작 전 위험성평가 결과를 JSON으로 작성하세요."
        f" 추가 현장 정보: {extra_context or '없음'}"
        f"\nCV 힌트(JSON): {json.dumps(cv_hint, ensure_ascii=False)}"
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

    data = parse_json(response.output_text)
    data["cv_meta"] = {
        "enabled": cv.enabled,
        "engine": cv.engine,
        "counts": cv.counts,
        "detections": cv.detections,
    }

    if not data.get("checklist"):
        data["checklist"] = cv.checklist
    if not data.get("hazards"):
        data["hazards"] = cv.hazards
    if not data.get("priority_actions"):
        data["priority_actions"] = cv.priority_actions
    if "overall_risk_score" not in data:
        data["overall_risk_score"] = cv.overall_risk_score
    if "risk_level" not in data:
        data["risk_level"] = cv.risk_level

    return data


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_: RequestEntityTooLarge):
    max_mb = int(os.getenv("MAX_UPLOAD_MB", "4"))
    return jsonify({"error": f"업로드 파일이 너무 큽니다. {max_mb}MB 이하 이미지로 다시 시도해주세요."}), 413


@app.get("/")
def home() -> str:
    return render_template("index.html")


@app.post("/api/analyze")
def analyze() -> Any:
    image = request.files.get("image")
    if image is None:
        return jsonify({"error": "image 파일이 필요합니다."}), 400

    raw = image.read()
    mime = image.mimetype or "image/jpeg"
    encoded = base64.b64encode(raw).decode("utf-8")
    image_data_url = f"data:{mime};base64,{encoded}"
    extra_context = request.form.get("extra_context", "")

    try:
        cv = analyze_cv(raw)
        result = analyze_with_openai(image_data_url, extra_context, cv)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True)