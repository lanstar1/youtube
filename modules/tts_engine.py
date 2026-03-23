"""
Stage 3-A: TTS 음성 생성 모듈
ElevenLabs API 연동 - 본인 목소리 클론 TTS로 내레이션 생성
각 scene의 narration을 개별 MP3로 생성 후 병합
"""

import os
import sys
import json
import time
import requests
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ELEVENLABS_API_KEY, TTS_SETTINGS, OUTPUT_DIR

BASE_URL = "https://api.elevenlabs.io/v1"


def get_headers():
    return {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }


# ─── 보이스 관리 ─────────────────────────────────────────

def list_voices():
    """사용 가능한 보이스 목록 조회"""
    res = requests.get(f"{BASE_URL}/voices", headers=get_headers())
    res.raise_for_status()
    voices = res.json()["voices"]
    for v in voices:
        print(f"  [{v['voice_id'][:8]}...] {v['name']} - {v.get('labels', {})}")
    return voices


def clone_voice(name: str, audio_files: list, description: str = "LANstar 채널 내레이터"):
    """
    본인 목소리 클론 생성 (10초+ 음성 샘플 필요)

    Args:
        name: 보이스 이름
        audio_files: 음성 파일 경로 리스트 (mp3/wav)
        description: 보이스 설명
    """
    files = [("files", (os.path.basename(f), open(f, "rb"))) for f in audio_files]
    data = {"name": name, "description": description}

    res = requests.post(
        f"{BASE_URL}/voices/add",
        headers={"xi-api-key": ELEVENLABS_API_KEY},
        data=data,
        files=files,
    )
    res.raise_for_status()
    voice_id = res.json()["voice_id"]
    print(f"✅ 보이스 클론 완료! voice_id: {voice_id}")
    return voice_id


# ─── TTS 생성 ────────────────────────────────────────────

def generate_speech(
    text: str,
    voice_id: str = None,
    emotion: str = "neutral",
    pace: str = "normal",
    output_path: str = None,
) -> str:
    """
    텍스트 → 음성 파일 생성

    Args:
        text: 내레이션 텍스트
        voice_id: ElevenLabs 보이스 ID (없으면 config 기본값)
        emotion: 감정 톤
        pace: 말하기 속도
        output_path: 저장 경로

    Returns:
        생성된 음성 파일 경로
    """
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY 환경변수를 설정해주세요.")

    voice_id = voice_id or TTS_SETTINGS.get("voice_id")
    if not voice_id:
        raise ValueError("voice_id를 설정해주세요. (config.py 또는 함수 인자)")

    # 감정/속도에 따른 파라미터 조정
    stability, similarity, style = _get_voice_params(emotion, pace)

    payload = {
        "text": text,
        "model_id": TTS_SETTINGS["model"],
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity,
            "style": style,
            "use_speaker_boost": True,
        },
    }

    res = requests.post(
        f"{BASE_URL}/text-to-speech/{voice_id}",
        headers=get_headers(),
        json=payload,
    )
    res.raise_for_status()

    if output_path is None:
        output_path = str(OUTPUT_DIR / f"tts_{int(time.time())}.mp3")

    with open(output_path, "wb") as f:
        f.write(res.content)

    return output_path


def _get_voice_params(emotion: str, pace: str):
    """감정/속도에 따른 TTS 파라미터 매핑"""
    # 기본값
    stability = TTS_SETTINGS["stability"]
    similarity = TTS_SETTINGS["similarity_boost"]
    style = TTS_SETTINGS["style"]

    emotion_map = {
        "neutral":  (0.50, 0.75, 0.20),
        "excited":  (0.35, 0.80, 0.60),
        "serious":  (0.65, 0.70, 0.15),
        "curious":  (0.40, 0.75, 0.40),
        "warm":     (0.55, 0.80, 0.35),
        "urgent":   (0.30, 0.75, 0.55),
    }

    if emotion in emotion_map:
        stability, similarity, style = emotion_map[emotion]

    # 속도 조정 (stability로 간접 조절)
    if pace == "fast":
        stability = max(0.2, stability - 0.1)
    elif pace == "slow":
        stability = min(0.8, stability + 0.15)

    return stability, similarity, style


# ─── 배치 생성 (스크립트 전체) ─────────────────────────────

def generate_from_script(
    script: dict,
    voice_id: str = None,
    output_dir: str = None,
) -> dict:
    """
    Video Notation JSON의 모든 scene 내레이션을 TTS로 생성

    Args:
        script: Video Notation Schema JSON
        voice_id: 보이스 ID
        output_dir: 출력 디렉토리

    Returns:
        scene별 음성 파일 경로 매핑
    """
    scenes = script.get("scenes", [])
    if not scenes:
        raise ValueError("스크립트에 scenes가 없습니다.")

    if output_dir is None:
        title = script.get("metadata", {}).get("title", "untitled")
        safe = "".join(c for c in title if c.isalnum() or c in " -_")[:30].strip()
        output_dir = str(OUTPUT_DIR / f"tts_{safe}")

    os.makedirs(output_dir, exist_ok=True)
    results = {"files": [], "total_chars": 0, "scenes": {}}

    for scene in scenes:
        sid = scene.get("scene_id", 0)
        narration = scene.get("narration", {})
        text = narration.get("text", "")
        if not text:
            continue

        emotion = narration.get("emotion", "neutral")
        pace = narration.get("pace", "normal")
        filename = f"scene_{sid:02d}_{scene.get('section', 'unknown')}.mp3"
        filepath = os.path.join(output_dir, filename)

        print(f"  🎤 Scene {sid} ({scene.get('section', '')}) - {len(text)}자...")
        try:
            generate_speech(text, voice_id, emotion, pace, filepath)
            results["files"].append(filepath)
            results["scenes"][sid] = {
                "file": filepath,
                "text": text,
                "emotion": emotion,
                "duration_est": len(text) * 0.08,  # 한글 기준 ~0.08초/자
            }
            results["total_chars"] += len(text)
            time.sleep(0.5)  # API rate limit 대응
        except Exception as e:
            print(f"  ❌ Scene {sid} 실패: {e}")
            results["scenes"][sid] = {"error": str(e)}

    # 전체 스크립트 음성 (연결)
    full_text = script.get("tts_config", {}).get("full_script", "")
    if full_text:
        full_path = os.path.join(output_dir, "full_narration.mp3")
        print(f"  🎤 전체 내레이션 생성 ({len(full_text)}자)...")
        try:
            generate_speech(full_text, voice_id, "neutral", "normal", full_path)
            results["full_narration"] = full_path
        except Exception as e:
            print(f"  ❌ 전체 내레이션 실패: {e}")

    print(f"\n✅ TTS 생성 완료! 총 {len(results['files'])}개 파일, {results['total_chars']}자")
    return results


# ─── 유틸리티 ────────────────────────────────────────────

def get_voice_info(voice_id: str) -> dict:
    """보이스 상세 정보 조회"""
    res = requests.get(f"{BASE_URL}/voices/{voice_id}", headers=get_headers())
    res.raise_for_status()
    return res.json()


def get_usage():
    """API 사용량 조회"""
    res = requests.get(f"{BASE_URL}/user/subscription", headers=get_headers())
    res.raise_for_status()
    sub = res.json()
    print(f"  📊 Plan: {sub.get('tier', 'N/A')}")
    print(f"  📊 Characters: {sub.get('character_count', 0):,} / {sub.get('character_limit', 0):,}")
    return sub


# ─── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LANstar TTS 엔진")
    sub = parser.add_subparsers(dest="command")

    # voices 명령
    sub.add_parser("voices", help="보이스 목록")

    # clone 명령
    clone_p = sub.add_parser("clone", help="보이스 클론")
    clone_p.add_argument("--name", required=True)
    clone_p.add_argument("--files", nargs="+", required=True)

    # generate 명령
    gen_p = sub.add_parser("generate", help="스크립트 TTS 생성")
    gen_p.add_argument("--script", required=True, help="스크립트 JSON 경로")
    gen_p.add_argument("--voice", required=True, help="보이스 ID")

    # usage 명령
    sub.add_parser("usage", help="API 사용량")

    args = parser.parse_args()

    if args.command == "voices":
        list_voices()
    elif args.command == "clone":
        clone_voice(args.name, args.files)
    elif args.command == "generate":
        with open(args.script) as f:
            script = json.load(f)
        generate_from_script(script, args.voice)
    elif args.command == "usage":
        get_usage()
    else:
        parser.print_help()
