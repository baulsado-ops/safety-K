import os
from dataclasses import dataclass
from typing import Any


TARGET_CLASSES = [
    "person",
    "hard hat",
    "helmet",
    "safety helmet",
    "safety vest",
    "reflective vest",
    "forklift",
    "truck",
    "excavator",
    "crane",
    "machine",
    "ladder",
    "scaffold",
    "scaffolding",
    "fire",
    "smoke",
    "spark",
    "cable",
    "wire",
]


@dataclass
class CvRiskSummary:
    enabled: bool
    engine: str
    detections: list[dict[str, Any]]
    counts: dict[str, int]
    overall_risk_score: int
    risk_level: str
    summary: str
    checklist: list[dict[str, str]]
    hazards: list[dict[str, Any]]
    priority_actions: list[str]


ALIASES = {
    "person": ["person", "worker", "human"],
    "helmet": ["helmet", "hard hat", "safety helmet"],
    "vest": ["safety vest", "reflective vest", "vest"],
    "machinery": ["forklift", "truck", "excavator", "crane", "machine"],
    "height": ["ladder", "scaffold", "scaffolding"],
    "fire": ["fire", "smoke", "spark"],
    "electrical": ["cable", "wire"],
}


def _risk_level(score: int) -> str:
    if score >= 80:
        return "매우높음"
    if score >= 60:
        return "높음"
    if score >= 40:
        return "보통"
    return "낮음"


def _count_groups(labels: list[str]) -> dict[str, int]:
    lower_labels = [x.lower().strip() for x in labels]
    grouped: dict[str, int] = {}
    for key, words in ALIASES.items():
        grouped[key] = sum(1 for label in lower_labels if label in words)
    return grouped


def _score_and_actions(counts: dict[str, int]) -> tuple[int, list[dict[str, Any]], list[str], list[dict[str, str]], str]:
    persons = counts.get("person", 0)
    helmets = counts.get("helmet", 0)
    vests = counts.get("vest", 0)
    machinery = counts.get("machinery", 0)
    height = counts.get("height", 0)
    fire = counts.get("fire", 0)
    electrical = counts.get("electrical", 0)

    score = 20
    hazards: list[dict[str, Any]] = []
    priority_actions: list[str] = []

    if persons > 0 and helmets < persons:
        missing = persons - helmets
        score += min(28, missing * 7)
        hazards.append(
            {
                "title": "보호구(안전모) 미착용 추정",
                "severity": 4,
                "likelihood": 4 if missing >= 2 else 3,
                "risk_score": 16 if missing >= 2 else 12,
                "warning": f"작업 인원 {persons}명 대비 안전모 감지 {helmets}개로 미착용 가능성이 있습니다.",
                "prevention": "작업 전 전원 PPE 착용 확인, 미착용자 현장 진입 통제",
            }
        )
        priority_actions.append("안전모/보안경/안전화 착용 상태 즉시 점검")

    if persons > 0 and vests < persons:
        score += min(15, (persons - vests) * 4)
        hazards.append(
            {
                "title": "고시인성 조끼 착용 미흡 추정",
                "severity": 3,
                "likelihood": 3,
                "risk_score": 9,
                "warning": "장비 운행 구역에서 작업자 식별이 늦어질 수 있습니다.",
                "prevention": "고시인성 조끼 착용 의무화 및 출입구 사전 확인",
            }
        )

    if persons > 0 and machinery > 0:
        score += 16
        hazards.append(
            {
                "title": "중장비-작업자 동선 간섭 위험",
                "severity": 5,
                "likelihood": 3,
                "risk_score": 15,
                "warning": "사람과 장비가 같은 구역에서 작업할 가능성이 보입니다.",
                "prevention": "신호수 배치, 작업반경 출입통제, 보행로 분리",
            }
        )
        priority_actions.append("장비 작업반경 라바콘/바리케이드로 즉시 분리")

    if persons > 0 and height > 0:
        score += 14
        hazards.append(
            {
                "title": "고소작업(추락/낙하) 위험",
                "severity": 5,
                "likelihood": 3,
                "risk_score": 15,
                "warning": "사다리/비계 관련 고소작업 가능성이 있습니다.",
                "prevention": "안전대 체결, 난간/개구부 덮개, 작업허가제 적용",
            }
        )
        priority_actions.append("고소작업 구역 안전난간/안전대 체결 여부 확인")

    if fire > 0:
        score += 20
        hazards.append(
            {
                "title": "화재/폭발 징후 위험",
                "severity": 5,
                "likelihood": 4,
                "risk_score": 20,
                "warning": "화기 또는 연기/불꽃 징후가 감지되었습니다.",
                "prevention": "가연물 제거, 소화기 비치, 화재감시자 지정",
            }
        )
        priority_actions.append("화기작업 허가 및 소화기 배치 상태 즉시 확인")

    if electrical > 0:
        score += 10
        hazards.append(
            {
                "title": "임시배선/전기위험",
                "severity": 4,
                "likelihood": 3,
                "risk_score": 12,
                "warning": "노출 배선/케이블로 인한 감전·걸림 위험이 있습니다.",
                "prevention": "배선 정리, 피복 손상 교체, 누전차단기 점검",
            }
        )

    score = max(0, min(100, score))

    checklist = [
        {
            "category": "PPE",
            "item": "안전모 착용 확인",
            "status": "미흡 추정" if persons > helmets else "양호 추정",
            "why": "미착용 시 두부 손상 가능성 증가",
            "action": "작업 전 착용확인 후 미착용자 출입 통제",
        },
        {
            "category": "PPE",
            "item": "고시인성 조끼 착용 확인",
            "status": "미흡 추정" if persons > vests else "양호 추정",
            "why": "장비 운행 구역 시인성 확보 필요",
            "action": "조끼 미착용자 즉시 착용 조치",
        },
        {
            "category": "중장비",
            "item": "장비 작업반경 출입 통제",
            "status": "필요" if machinery > 0 else "해당없음",
            "why": "사람-장비 충돌 위험 감소",
            "action": "신호수/유도원 배치 및 동선 분리",
        },
        {
            "category": "추락낙하",
            "item": "고소작업 보호조치(난간/안전대)",
            "status": "필요" if height > 0 else "미확인",
            "why": "고소작업 중 추락은 중대재해로 이어질 수 있음",
            "action": "난간, 개구부 덮개, 안전대 체결 점검",
        },
        {
            "category": "화재폭발",
            "item": "화기작업 통제 및 소화기 배치",
            "status": "필요" if fire > 0 else "미확인",
            "why": "불꽃/연기 징후는 화재 확산 위험",
            "action": "화재감시자 배치 및 가연물 제거",
        },
        {
            "category": "전기",
            "item": "케이블/임시배선 정리",
            "status": "필요" if electrical > 0 else "미확인",
            "why": "감전·걸림·화재 위험",
            "action": "피복 손상 교체, 누전차단기 확인",
        },
        {
            "category": "정리정돈",
            "item": "작업통로 적치물 제거",
            "status": "미확인",
            "why": "넘어짐·충돌 사고 예방",
            "action": "통로 폭 확보 및 적치물 즉시 정리",
        },
        {
            "category": "협착끼임",
            "item": "가동부 방호장치 상태",
            "status": "미확인",
            "why": "노출 가동부는 협착 위험",
            "action": "방호커버 및 인터록 상태 점검",
        },
        {
            "category": "기타",
            "item": "작업 전 TBM 실시",
            "status": "필요",
            "why": "당일 위험요인 공유로 인적오류 감소",
            "action": "핵심 위험 3가지와 통제방안 브리핑",
        },
        {
            "category": "기타",
            "item": "비상대피 동선/연락체계 점검",
            "status": "필요",
            "why": "사고 시 초기 대응시간 단축",
            "action": "대피로 표시 및 비상연락망 확인",
        },
    ]

    summary = (
        f"작업자 {persons}명, 안전모 {helmets}개, 조끼 {vests}개, 장비 {machinery}개, "
        f"고소작업 요소 {height}개, 화재징후 {fire}개, 전기요소 {electrical}개가 감지되었습니다."
    )

    if not priority_actions:
        priority_actions = [
            "작업 시작 전 TBM으로 위험요인 공유",
            "PPE 착용/작업허가 상태 최종 점검",
            "작업구역 정리정돈 및 비상대응체계 확인",
        ]

    return score, hazards, priority_actions, checklist, summary


def analyze_cv(image_bytes: bytes) -> CvRiskSummary:
    fallback_counts = {
        "person": 1,
        "helmet": 0,
        "vest": 0,
        "machinery": 0,
        "height": 0,
        "fire": 0,
        "electrical": 0,
    }
    fb_score, fb_hazards, fb_actions, fb_checklist, fb_summary = _score_and_actions(fallback_counts)

    try:
        import cv2
        import numpy as np
        from ultralytics import YOLO
    except Exception:
        return CvRiskSummary(
            enabled=False,
            engine="unavailable",
            detections=[],
            counts=fallback_counts,
            overall_risk_score=max(45, fb_score),
            risk_level=_risk_level(max(45, fb_score)),
            summary=(
                "CV 라이브러리(ultralytics/opencv)를 사용할 수 없어 일반 작업 착수 위험 기준으로 평가했습니다. "
                + fb_summary
            ),
            checklist=fb_checklist,
            hazards=fb_hazards,
            priority_actions=fb_actions,
        )

    model_name = os.getenv("VISION_MODEL", "yolov8s-worldv2.pt")
    conf = float(os.getenv("VISION_CONF", "0.20"))

    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("이미지 디코딩 실패")

        model = YOLO(model_name)

        # YOLO-World 모델인 경우 텍스트 클래스를 지정해 현장 안전 객체를 우선 탐지
        if hasattr(model, "set_classes"):
            try:
                model.set_classes(TARGET_CLASSES)
            except Exception:
                pass

        result = model.predict(source=img, conf=conf, verbose=False)[0]

        names = result.names if hasattr(result, "names") else {}
        detections: list[dict[str, Any]] = []
        labels: list[str] = []

        boxes = getattr(result, "boxes", None)
        if boxes is not None:
            for box in boxes:
                cls_id = int(box.cls[0])
                label = str(names.get(cls_id, cls_id))
                confidence = float(box.conf[0])
                xyxy = box.xyxy[0].tolist()
                labels.append(label)
                detections.append(
                    {
                        "label": label,
                        "confidence": round(confidence, 4),
                        "bbox": [round(v, 1) for v in xyxy],
                    }
                )

        counts = _count_groups(labels)
        score, hazards, actions, checklist, summary = _score_and_actions(counts)

        return CvRiskSummary(
            enabled=True,
            engine=f"ultralytics:{model_name}",
            detections=detections,
            counts=counts,
            overall_risk_score=score,
            risk_level=_risk_level(score),
            summary=summary,
            checklist=checklist,
            hazards=hazards,
            priority_actions=actions,
        )

    except Exception as exc:
        return CvRiskSummary(
            enabled=False,
            engine=f"error:{model_name}",
            detections=[],
            counts=fallback_counts,
            overall_risk_score=max(45, fb_score),
            risk_level=_risk_level(max(45, fb_score)),
            summary=f"객체 인식 분석 실패({exc})로 일반 작업 착수 위험 기준으로 평가했습니다. {fb_summary}",
            checklist=fb_checklist,
            hazards=fb_hazards,
            priority_actions=fb_actions,
        )
