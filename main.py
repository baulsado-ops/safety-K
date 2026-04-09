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
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "12"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """
You are a Korean EHS specialist for manufacturing plants and construction sites.
Analyze the image and return JSON only (no markdown, no extra text).
Write all user-facing text fields in Korean.

Output schema:
{
  "site_type": "manufacturing | construction | unknown",
  "overall_risk_score": 0-100 integer,
  "risk_level": "낮음 | 보통 | 높음 | 매우높음",
  "summary": "한국어 요약",
  "checklist": [
    {
      "category": "PPE | 전기 | 화재폭발 | 중장비 | 추락낙하 | 협착끼임 | 화학물질 | 정리정돈 | 기타",
      "item": "점검 항목",
      "status": "미확인 | 양호 추정 | 미흡 추정 | 필요 | 해당없음",
      "why": "위험 근거",
      "action": "예방대책"
    }
  ],
  "hazards": [
    {
      "title": "위험요인",
      "severity": 1-5,
      "likelihood": 1-5,
      "risk_score": 1-25,
      "warning": "주의사항",
      "prevention": "예방대책"
    }
  ],
  "priority_actions": ["즉시 조치"],
  "legal_notes": ["법적 유의사항"]
}

Rules:
- checklist length must be at least 10.
- hazards length must be at least 5.
- Infer site_type from visible cues whenever possible.
- If uncertain, explicitly mark assumptions.
""".strip()


def risk_level_from_score(score: int) -> str:
    if score >= 80:
        return "매우높음"
    if score >= 60:
        return "높음"
    if score >= 40:
        return "보통"
    return "낮음"


def parse_json(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json", "", 1).strip()
    return json.loads(stripped)


def _base_payload(cv: CvRiskSummary, message: str | None = None) -> dict[str, Any]:
    return {
        "site_type": "unknown",
        "overall_risk_score": cv.overall_risk_score,
        "risk_level": cv.risk_level,
        "summary": message or cv.summary,
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


def _infer_site_type(merged: dict[str, Any], cv: CvRiskSummary) -> str:
    site_type = str(merged.get("site_type", "unknown")).lower().strip()
    if site_type in {"manufacturing", "construction"}:
        return site_type

    text_parts: list[str] = []
    text_parts.append(str(merged.get("summary", "")))

    for hz in merged.get("hazards", []) or []:
        text_parts.append(str(hz.get("title", "")))
        text_parts.append(str(hz.get("warning", "")))

    for ck in merged.get("checklist", []) or []:
        text_parts.append(str(ck.get("item", "")))

    text = " ".join(text_parts).lower()

    construction_keywords = [
        "construction", "건설", "비계", "scaffold", "crane", "excavator", "ladder", "굴착", "거푸집", "타워크레인",
    ]
    manufacturing_keywords = [
        "manufacturing", "factory", "plant", "공장", "제조", "생산", "라인", "conveyor", "press", "cnc", "assembly",
    ]

    c_score = sum(1 for kw in construction_keywords if kw in text)
    m_score = sum(1 for kw in manufacturing_keywords if kw in text)

    # CV counts hint: machinery/height tends to construction, but machine-only indoor can be manufacturing.
    machinery = int((cv.counts or {}).get("machinery", 0))
    height = int((cv.counts or {}).get("height", 0))
    if height > 0:
        c_score += 2
    if machinery > 0:
        c_score += 1
        m_score += 1

    if c_score == 0 and m_score == 0:
        return "unknown"
    return "construction" if c_score >= m_score else "manufacturing"


def _normalize_result(data: dict[str, Any], cv: CvRiskSummary) -> dict[str, Any]:
    merged = dict(data or {})

    merged.setdefault("site_type", "unknown")
    merged.setdefault("summary", cv.summary)
    merged.setdefault("checklist", cv.checklist)
    merged.setdefault("hazards", cv.hazards)
    merged.setdefault("priority_actions", cv.priority_actions)
    merged.setdefault(
        "legal_notes",
        [
            "산업안전보건법 및 관련 고시에 따른 기본 안전조치 준수 필요",
            "구체 법조문 적용은 업종/공정별 안전관리자 검토 필요",
        ],
    )

    if merged.get("overall_risk_score") is None:
        merged["overall_risk_score"] = cv.overall_risk_score

    try:
        merged["overall_risk_score"] = max(0, min(100, int(merged.get("overall_risk_score", cv.overall_risk_score))))
    except Exception:
        merged["overall_risk_score"] = cv.overall_risk_score

    merged["risk_level"] = merged.get("risk_level") or risk_level_from_score(merged["overall_risk_score"])
    merged["site_type"] = _infer_site_type(merged, cv)

    merged["cv_meta"] = {
        "enabled": cv.enabled,
        "engine": cv.engine,
        "counts": cv.counts,
        "detections": cv.detections,
    }

    return merged


def analyze_with_openai(image_data_url: str, extra_context: str, cv: CvRiskSummary) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _normalize_result(_base_payload(cv, "OPENAI_API_KEY 미설정으로 CV/규칙 기반 평가를 표시합니다."), cv)

    client = OpenAI(api_key=api_key)
    cv_hint = {
        "cv_enabled": cv.enabled,
        "cv_engine": cv.engine,
        "cv_counts": cv.counts,
        "cv_summary": cv.summary,
        "cv_hazards": cv.hazards,
    }

    user_instruction = (
        "이미지와 CV 힌트를 종합해 작업시작 전 위험성평가 결과를 JSON으로 작성하세요. "
        f"추가 현장 정보: {extra_context or '없음'}\n"
        f"CV_HINT: {json.dumps(cv_hint, ensure_ascii=False)}"
    )

    response = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_instruction},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            },
        ],
        max_output_tokens=2000,
    )

    data = parse_json(response.output_text)
    return _normalize_result(data, cv)


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_: RequestEntityTooLarge):
    return jsonify({"error": f"업로드 파일이 너무 큽니다. {MAX_UPLOAD_MB}MB 이하 이미지로 다시 시도해주세요."}), 413


@app.get("/")
def home() -> str:
    return render_template("index.html", max_upload_mb=MAX_UPLOAD_MB)


@app.post("/api/analyze")
def analyze() -> Any:
    image = request.files.get("image")
    if image is None:
        return jsonify({"error": "image 파일이 필요합니다."}), 400

    raw = image.read()
    if not raw:
        return jsonify({"error": "빈 파일입니다. 이미지를 다시 업로드해주세요."}), 400

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