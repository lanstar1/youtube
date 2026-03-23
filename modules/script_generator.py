"""
Stage 2: AI-Driven Script & JSON Structuring
Claude API 1회 호출로 Video Notation Schema 기반 전체 스크립트 JSON 생성
"""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from config import (
    ANTHROPIC_API_KEY, SCHEMAS_DIR, PROMPTS_DIR, OUTPUT_DIR,
    BRAND_TONE, VIDEO_SETTINGS, SCRIPT_STRUCTURE, CATEGORIES
)


def load_system_prompt():
    """시스템 프롬프트 + 스키마 로드"""
    with open(PROMPTS_DIR / "script_system.md", "r", encoding="utf-8") as f:
        system_prompt = f.read()

    with open(SCHEMAS_DIR / "video_notation.json", "r", encoding="utf-8") as f:
        schema = json.load(f)

    system_prompt += f"\n\n## Video Notation Schema (출력 형식)\n```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"
    return system_prompt


def generate_script(
    product_name: str,
    product_model: str = "",
    product_features: list = None,
    category: str = "네트워크/서버",
    target_persona: str = "",
    pain_point: str = "",
    additional_context: str = "",
    is_remake: bool = False,
    original_video_id: str = "",
) -> dict:
    """
    Claude API 1회 호출로 전체 Video Notation JSON 생성

    Args:
        product_name: 제품명 (예: "HDMI 분배기")
        product_model: 모델명 (예: "LS-HD2SP")
        product_features: 제품 특징 리스트
        category: 콘텐츠 카테고리
        target_persona: 타겟 시청자
        pain_point: 시청자 고통점
        additional_context: 추가 맥락 (기존 인기 영상 데이터 등)
        is_remake: 리메이크 여부
        original_video_id: 원본 영상 ID (리메이크 시)

    Returns:
        dict: Video Notation Schema에 맞는 JSON
    """

    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY 환경변수를 설정해주세요.")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system_prompt = load_system_prompt()

    # 카테고리별 심리전술 가져오기
    cat_info = CATEGORIES.get(category, {})
    psychology = cat_info.get("psychology", ["Value Compression", "Comprehension Maxing"])

    # 사용자 프롬프트 구성
    user_prompt = f"""다음 제품에 대한 LANstar 유튜브 영상 스크립트를 Video Notation Schema JSON 형식으로 생성해주세요.

## 제품 정보
- **제품명**: {product_name}
- **모델명**: {product_model or '미정'}
- **주요 특징**: {', '.join(product_features) if product_features else '제품 특성에 맞게 작성'}
- **카테고리**: {category}

## 타겟 시청자
- **페르소나**: {target_persona or '일반 IT 사용자 / 재택근무자'}
- **고통점**: {pain_point or '제품 관련 일상적 문제'}

## 적용할 심리전술
{', '.join(psychology)} (필수) + 추가 전술 자유 선택

## 영상 설정
- 목표 길이: {VIDEO_SETTINGS['target_duration']}
- 장면 전환 주기: {VIDEO_SETTINGS['scene_change_interval']}
- 해상도: {VIDEO_SETTINGS['resolution']}

## 브랜드 톤앤매너
- {BRAND_TONE['voice']}
- 금지: {', '.join(BRAND_TONE['prohibited'])}
"""

    if is_remake and original_video_id:
        user_prompt += f"""
## 리메이크 정보
이 영상은 기존 인기 영상의 리메이크입니다.
- 원본 영상 ID: {original_video_id}
- 원본의 성공 요인을 유지하면서 최신 정보와 개선된 스토리텔링으로 업그레이드
"""

    if additional_context:
        user_prompt += f"""
## 추가 맥락
{additional_context}
"""

    user_prompt += """
JSON만 출력하세요. 마크다운 코드블록이나 설명 없이 순수 JSON만 응답합니다.
scenes는 최소 8개 이상 작성하세요. 각 scene의 image_prompt는 영어로 상세하게 작성하세요.
"""

    print(f"🤖 Claude API 호출 중... (제품: {product_name})")

    # 최대 2회 시도 (토큰 부족 시 재시도)
    for attempt in range(2):
        token_limit = 12000 if attempt == 0 else 16000
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=token_limit,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )

        raw_text = response.content[0].text.strip()
        stop_reason = response.stop_reason

        # JSON 추출 (코드블록 감싸인 경우 처리)
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            raw_text = "\n".join(json_lines)

        # 토큰 한도로 잘린 경우 재시도
        if stop_reason == "max_tokens" and attempt == 0:
            print(f"⚠️ 토큰 한도 도달, 더 큰 한도로 재시도 중...")
            continue

        try:
            result = json.loads(raw_text)
            print(f"✅ 스크립트 생성 완료! (장면 수: {len(result.get('scenes', []))})")
            return result
        except json.JSONDecodeError as e:
            # 잘린 JSON 복구 시도
            print(f"⚠️ JSON 파싱 실패, 복구 시도 중... ({e})")
            repaired = _repair_truncated_json(raw_text)
            if repaired:
                print(f"✅ JSON 복구 성공! (장면 수: {len(repaired.get('scenes', []))})")
                return repaired

            if attempt == 0 and stop_reason == "max_tokens":
                continue

            error_path = OUTPUT_DIR / "last_raw_response.txt"
            with open(error_path, "w", encoding="utf-8") as f:
                f.write(raw_text)
            print(f"  원시 응답 저장: {error_path}")
            raise


def _repair_truncated_json(text: str) -> dict | None:
    """잘린 JSON 복구 시도"""
    import re

    # 마지막 완전한 객체/배열까지 자르고 닫기
    # scenes 배열 내에서 잘린 경우가 대부분
    bracket_stack = []
    last_valid_pos = 0

    for i, ch in enumerate(text):
        if ch in ('{', '['):
            bracket_stack.append(ch)
        elif ch == '}':
            if bracket_stack and bracket_stack[-1] == '{':
                bracket_stack.pop()
                if len(bracket_stack) <= 1:  # 최상위 또는 scenes 배열 레벨
                    last_valid_pos = i + 1
        elif ch == ']':
            if bracket_stack and bracket_stack[-1] == '[':
                bracket_stack.pop()
                if len(bracket_stack) <= 1:
                    last_valid_pos = i + 1

    if last_valid_pos > 0:
        truncated = text[:last_valid_pos]
        # 남은 열린 괄호 닫기
        closing = ""
        for bracket in reversed(bracket_stack):
            closing += "]" if bracket == "[" else "}"
        try:
            return json.loads(truncated + closing)
        except:
            pass

    return None


def generate_from_remake_candidate(candidate: dict, analysis_data: dict = None) -> dict:
    """
    리메이크 후보 영상 데이터를 기반으로 스크립트 생성

    Args:
        candidate: lanstar_data.json의 remakeCandidates 항목
        analysis_data: 전체 분석 데이터 (선택)
    """
    # 제목에서 제품 정보 추출
    title = candidate["title"]
    tags = candidate.get("tags", [])

    # 카테고리 감지
    category = candidate.get("category", "기타")
    if category == "기타":
        category = "네트워크/서버"

    additional = f"""
## 원본 영상 성과 데이터
- 원본 제목: {title}
- 조회수: {candidate['viewCount']:,}회
- 좋아요: {candidate['likeCount']:,}개
- 참여도: {candidate.get('engagementRate', 0)}%
- 태그: {', '.join(tags[:15])}
- 원본은 {candidate.get('ageDays', 0)}일 전 게시 (리메이크 적기)

원본 영상의 주제와 핵심 가치를 유지하면서, 최신 제품 정보와 개선된 스토리텔링으로 완전히 새로운 영상을 만들어주세요.
"""

    return generate_script(
        product_name=title,
        category=category,
        additional_context=additional,
        is_remake=True,
        original_video_id=candidate.get("id", ""),
    )


def save_script(script: dict, filename: str = None):
    """생성된 스크립트 JSON 저장"""
    if filename is None:
        title = script.get("metadata", {}).get("title", "untitled")
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
        filename = f"script_{safe_title}.json"

    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print(f"💾 스크립트 저장: {path}")
    return path


def validate_script(script: dict) -> list:
    """생성된 스크립트 유효성 검증"""
    errors = []

    # 필수 필드 확인
    required = ["metadata", "headline", "seo", "scenes", "tts_config", "thumbnail"]
    for field in required:
        if field not in script:
            errors.append(f"❌ 필수 필드 누락: {field}")

    # scenes 검증
    scenes = script.get("scenes", [])
    if len(scenes) < 5:
        errors.append(f"⚠️ 장면 수 부족: {len(scenes)}개 (최소 5개)")

    sections_found = set()
    for i, scene in enumerate(scenes):
        if "narration" not in scene:
            errors.append(f"❌ Scene {i+1}: narration 누락")
        if "visual" not in scene:
            errors.append(f"❌ Scene {i+1}: visual 누락")
        else:
            if scene["visual"].get("type") == "ai_image" and not scene["visual"].get("image_prompt"):
                errors.append(f"⚠️ Scene {i+1}: ai_image 타입인데 image_prompt 없음")
        if "section" in scene:
            sections_found.add(scene["section"])

    # 모든 섹션 포함 확인
    required_sections = {"hook", "problem", "solution", "product", "cta"}
    missing = required_sections - sections_found
    if missing:
        errors.append(f"⚠️ 누락된 섹션: {missing}")

    # SEO 검증
    seo = script.get("seo", {})
    tags = seo.get("tags", [])
    if len(tags) < 10:
        errors.append(f"⚠️ SEO 태그 부족: {len(tags)}개 (최소 10개)")

    # 심리전술 검증
    tactics = script.get("metadata", {}).get("psychology_tactics", [])
    if len(tactics) < 2:
        errors.append(f"⚠️ 심리전술 부족: {len(tactics)}개 (최소 2개)")

    # 썸네일 검증
    thumb = script.get("thumbnail", {})
    if not thumb.get("text_overlay"):
        errors.append("⚠️ 썸네일 텍스트 오버레이 없음")
    if not thumb.get("image_prompt"):
        errors.append("⚠️ 썸네일 이미지 프롬프트 없음")

    if errors:
        print(f"⚠️ 검증 결과: {len(errors)}개 이슈 발견")
        for e in errors:
            print(f"  {e}")
    else:
        print("✅ 스크립트 검증 통과! 모든 필수 요소 포함")

    return errors


# ─── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LANstar 스크립트 생성기")
    parser.add_argument("--product", required=True, help="제품명")
    parser.add_argument("--model", default="", help="모델명")
    parser.add_argument("--category", default="네트워크/서버", help="카테고리")
    parser.add_argument("--persona", default="", help="타겟 페르소나")
    parser.add_argument("--pain", default="", help="고통점")
    parser.add_argument("--remake-id", default="", help="리메이크 원본 영상 ID")
    args = parser.parse_args()

    script = generate_script(
        product_name=args.product,
        product_model=args.model,
        category=args.category,
        target_persona=args.persona,
        pain_point=args.pain,
        is_remake=bool(args.remake_id),
        original_video_id=args.remake_id,
    )

    validate_script(script)
    save_script(script)
