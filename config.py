"""
LANstar YouTube 자동화 파이프라인 - 설정 파일
모든 API 키와 설정을 환경변수 또는 .env에서 관리
"""
import os

# ─── API Keys ───────────────────────────────────────────
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
JSON2VIDEO_API_KEY = os.environ.get("JSON2VIDEO_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # DALL-E용

# ─── 채널 정보 ──────────────────────────────────────────
CHANNEL_ID = "UC5flcH9DY01UpoCw3y0QgcA"
CHANNEL_NAME = "LANstar랜스타"
CHANNEL_URL = "https://www.youtube.com/@LANstar"
BRAND_URL = "https://lanstar.co.kr"

# ─── 브랜드 톤앤매너 ────────────────────────────────────
BRAND_TONE = {
    "voice": "친근하고 전문적인, 옆집 형/오빠가 알려주는 느낌",
    "language": "ko",
    "formality": "반말 + 존댓말 혼용 (시청자에게는 존댓말)",
    "personality": "IT 전문가이지만 쉽게 설명하는 사람",
    "prohibited": ["과장 광고 표현", "경쟁사 비하", "확인되지 않은 스펙"],
}

# ─── 영상 제작 설정 ─────────────────────────────────────
VIDEO_SETTINGS = {
    "target_duration": "5-8분",  # 롱폼 기본
    "shorts_duration": "30-60초",  # 숏폼
    "resolution": "1920x1080",
    "fps": 30,
    "scene_change_interval": "3-5초",  # Visual Stun Gun 전술
    "thumbnail_size": "1280x720",
}

# ─── 스크립트 구조 ──────────────────────────────────────
SCRIPT_STRUCTURE = {
    "hook": {"duration": "0-5초", "purpose": "Value Compression - 핵심 가치 즉시 전달"},
    "problem": {"duration": "5-35초", "purpose": "문제 제기 - 시청자 공감 유도"},
    "solution": {"duration": "35-215초", "purpose": "해결책 제시 - Hawkeye Narrative"},
    "product": {"duration": "215-275초", "purpose": "제품 소개 - Comprehension Maxing"},
    "cta": {"duration": "275-300초", "purpose": "CTA - 구독/구매 유도"},
}

# ─── 카테고리 정의 ──────────────────────────────────────
CATEGORIES = {
    "홈오피스/재택": {
        "keywords": ["USB 독", "KVM", "모니터 암", "허브", "재택근무", "데스크 셋업"],
        "psychology": ["Hawkeye", "Value Compression"],
        "hook_template": "재택근무 {n}년차, {topic}이(가) 점점 좋아져야 하는 이유",
    },
    "선정리/인테리어": {
        "keywords": ["랩핑튜브", "매직케이블", "케이블 정리", "선정리"],
        "psychology": ["Contrast", "Visual Matching"],
        "hook_template": "전선지옥에서 {n}분 투자로 탈출하는 법",
    },
    "영상/방송": {
        "keywords": ["HDMI 분배기", "캡쳐보드", "스위치", "방송장비"],
        "psychology": ["Comprehension Maxing"],
        "hook_template": "유튜버 시작할 때 화면 하나로는 부족한 이유",
    },
    "네트워크/서버": {
        "keywords": ["랜", "랜카드", "케이블", "스위칭허브", "패치패널"],
        "psychology": ["Hawkeye", "Storytelling Hook"],
        "hook_template": "소규모 사무실 네트워크, 직접 구축 가능한 이유",
    },
    "트러블슈팅": {
        "keywords": ["테스터기", "컨버터", "문제해결", "인터넷 느림"],
        "psychology": ["Value Compression", "Contrast"],
        "hook_template": "인터넷 느릴 때 원인을 찾는 {n}가지 방법",
    },
}

# ─── TTS 설정 ───────────────────────────────────────────
TTS_SETTINGS = {
    "provider": "elevenlabs",  # elevenlabs | supertone
    "model": "eleven_multilingual_v2",
    "voice_id": os.environ.get("ELEVENLABS_VOICE_ID", "X8It1z772AWCI8PNW8D3"),
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.3,
    "output_format": "mp3_44100_128",
}

# ─── 경로 설정 ──────────────────────────────────────────
import pathlib
BASE_DIR = pathlib.Path(__file__).parent
SCHEMAS_DIR = BASE_DIR / "schemas"
PROMPTS_DIR = BASE_DIR / "prompts"
MODULES_DIR = BASE_DIR / "modules"
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR  # lanstar_data.json 위치
