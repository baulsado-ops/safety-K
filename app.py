import base64
import json
import os
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


@dataclass
class RiskResult:
    site_type: str
    overall_risk_score: int
    risk_level: str
    summary: str
    checklist: list[dict[str, Any]]
    hazards: list[dict[str, Any]]
    priority_actions: list[str]
    legal_notes: list[str]
    raw_json: dict[str, Any]


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
    "summary": "API 키가 없어 데모 분석 결과를 표시합니다. 실제 현장 적용 시에는 이미지 기반 AI 분석을 활성화하세요.",
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


def image_to_data_url(uploaded_file) -> str:
    img_bytes = uploaded_file.getvalue()
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    mime = uploaded_file.type or "image/jpeg"
    return f"data:{mime};base64,{b64}"


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json", "", 1).strip()
    return json.loads(text)


def analyze_with_openai(image_data_url: str, extra_context: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return MOCK_RESULT

    client = OpenAI(api_key=api_key)

    user_instruction = (
        "이미지를 분석해 작업시작 전 위험성평가 결과를 JSON으로 작성하세요."
        f"추가 현장 정보: {extra_context or '없음'}"
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
                    {
                        "type": "input_image",
                        "image_url": image_data_url,
                    },
                ],
            },
        ],
        max_output_tokens=1800,
    )

    raw_text = response.output_text
    return parse_json(raw_text)


def normalize_result(data: dict[str, Any]) -> RiskResult:
    return RiskResult(
        site_type=str(data.get("site_type", "unknown")),
        overall_risk_score=max(0, min(100, int(data.get("overall_risk_score", 0)))),
        risk_level=str(data.get("risk_level", "보통")),
        summary=str(data.get("summary", "")),
        checklist=list(data.get("checklist", [])),
        hazards=list(data.get("hazards", [])),
        priority_actions=list(data.get("priority_actions", [])),
        legal_notes=list(data.get("legal_notes", [])),
        raw_json=data,
    )


def risk_color(score: int) -> str:
    if score >= 80:
        return "#c92a2a"
    if score >= 60:
        return "#e8590c"
    if score >= 40:
        return "#f08c00"
    return "#2b8a3e"


def build_markdown_report(result: RiskResult) -> str:
    lines = [
        "# 작업 시작 전 위험성 평가 리포트",
        f"- 사업장 유형: {result.site_type}",
        f"- 종합 위험도 점수: {result.overall_risk_score} / 100 ({result.risk_level})",
        "",
        "## 요약",
        result.summary,
        "",
        "## 작업 전 체크리스트",
    ]

    for idx, item in enumerate(result.checklist, start=1):
        lines.append(
            f"{idx}. [{item.get('category','기타')}] {item.get('item','-')} | 근거: {item.get('why','-')} | 조치: {item.get('action','-')}"
        )

    lines.append("")
    lines.append("## 주요 위험요인")
    for idx, hazard in enumerate(result.hazards, start=1):
        lines.append(
            f"{idx}. {hazard.get('title','-')} (S:{hazard.get('severity','-')}, L:{hazard.get('likelihood','-')}, R:{hazard.get('risk_score','-')})"
        )
        lines.append(f"   - 주의사항: {hazard.get('warning','-')}")
        lines.append(f"   - 예방대책: {hazard.get('prevention','-')}")

    lines.append("")
    lines.append("## 우선 조치")
    for idx, action in enumerate(result.priority_actions, start=1):
        lines.append(f"{idx}. {action}")

    lines.append("")
    lines.append("## 법적 유의사항")
    for idx, note in enumerate(result.legal_notes, start=1):
        lines.append(f"{idx}. {note}")

    return "\n".join(lines)


st.set_page_config(page_title="현장 위험성 체크리스트 생성기", page_icon="🦺", layout="wide")

st.title("현장 위험성 체크리스트 생성기")
st.caption("제조업 사업장/건설현장 사진 기반 작업 전 위험성 평가 도우미")

with st.sidebar:
    st.subheader("설정")
    st.write(f"모델: `{DEFAULT_MODEL}`")
    if os.getenv("OPENAI_API_KEY"):
        st.success("OPENAI_API_KEY 감지됨: 실분석 모드")
    else:
        st.warning("OPENAI_API_KEY 미설정: 데모 분석 모드")

col1, col2 = st.columns([1, 1])

with col1:
    uploaded_file = st.file_uploader(
        "현장 사진 업로드", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=False
    )
    extra_context = st.text_area(
        "추가 현장 정보(선택)",
        placeholder="예: 야간작업, 용접작업 포함, 지게차 상시 운행, 협력업체 2개 동시작업",
        height=120,
    )

    analyze_btn = st.button("위험성 분석 시작", type="primary", use_container_width=True)

with col2:
    st.markdown(
        """
### 출력 항목
- 작업 시작 전 체크리스트 자동 생성
- 종합 위험도 점수(0~100) 및 위험등급
- 주요 위험요인별 주의사항
- 즉시 실행 가능한 예방대책/우선조치
"""
    )

if analyze_btn:
    if not uploaded_file:
        st.error("사진을 먼저 업로드해주세요.")
        st.stop()

    with st.spinner("이미지 분석 중..."):
        try:
            image = Image.open(BytesIO(uploaded_file.getvalue()))
            st.image(image, caption="업로드 이미지", use_container_width=True)

            image_data_url = image_to_data_url(uploaded_file)
            raw_result = analyze_with_openai(image_data_url, extra_context)
            result = normalize_result(raw_result)

        except Exception as exc:
            st.exception(exc)
            st.stop()

    st.subheader("분석 결과")
    score_color = risk_color(result.overall_risk_score)
    st.markdown(
        f"""
<div style=\"padding:14px;border-radius:12px;background:#fff4e6;border:1px solid #ffd8a8;\">
  <div style=\"font-size:14px;opacity:.8;\">사업장 유형</div>
  <div style=\"font-size:20px;font-weight:700;\">{result.site_type}</div>
  <div style=\"margin-top:8px;font-size:14px;opacity:.8;\">종합 위험도</div>
  <div style=\"font-size:36px;font-weight:800;color:{score_color};\">{result.overall_risk_score} / 100</div>
  <div style=\"font-size:16px;font-weight:600;\">위험등급: {result.risk_level}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("### 현장 요약")
    st.write(result.summary)

    st.markdown("### 작업 시작 전 체크리스트")
    checklist_rows = []
    for item in result.checklist:
        checklist_rows.append(
            {
                "분류": item.get("category", "기타"),
                "점검항목": item.get("item", "-"),
                "상태": item.get("status", "미확인"),
                "위험근거": item.get("why", "-"),
                "예방대책": item.get("action", "-"),
            }
        )
    st.dataframe(checklist_rows, use_container_width=True, hide_index=True)

    st.markdown("### 주요 위험요인")
    for hazard in result.hazards:
        st.markdown(
            f"""
- **{hazard.get("title", "-")}**
  - 위험도(5x5): S {hazard.get("severity", "-")} x L {hazard.get("likelihood", "-")} = **{hazard.get("risk_score", "-")}**
  - 주의사항: {hazard.get("warning", "-")}
  - 예방대책: {hazard.get("prevention", "-")}
"""
        )

    st.markdown("### 우선 조치")
    for idx, action in enumerate(result.priority_actions, start=1):
        st.write(f"{idx}. {action}")

    st.markdown("### 법적 유의사항")
    for idx, note in enumerate(result.legal_notes, start=1):
        st.write(f"{idx}. {note}")

    report_md = build_markdown_report(result)
    st.download_button(
        label="리포트 다운로드 (.md)",
        data=report_md.encode("utf-8"),
        file_name="risk_assessment_report.md",
        mime="text/markdown",
        use_container_width=True,
    )

    with st.expander("원본 JSON 보기"):
        st.json(result.raw_json)
