#!/usr/bin/env python3
"""
LANstar YouTube 콘텐츠 자동화 파이프라인 오케스트레이터
5단계를 순차/선택적으로 실행하며 Human-in-the-Loop 검수 포함

사용법:
  # 전체 파이프라인 (스크립트부터 업로드까지)
  python pipeline.py --product "HDMI 분배기" --model "LS-HD2SP" --category "영상/방송"

  # 리메이크 모드 (기존 인기 영상 기반)
  python pipeline.py --remake --top 3

  # 특정 단계만 실행
  python pipeline.py --script output/script_xxx.json --stage tts
  python pipeline.py --script output/script_xxx.json --stage media
  python pipeline.py --script output/script_xxx.json --stage compose
  python pipeline.py --script output/script_xxx.json --stage publish

  # 배치 모드 (여러 영상 한번에)
  python pipeline.py --batch batch_config.json
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import OUTPUT_DIR, DATA_DIR
from modules.script_generator import generate_script, generate_from_remake_candidate, validate_script, save_script
from modules.tts_engine import generate_from_script as tts_generate
from modules.media_generator import generate_from_script as media_generate
from modules.video_composer import compose_video, create_video_recipe
from modules.seo_optimizer import optimize_seo, analyze_competition
from modules.publisher import upload_from_script, extract_shorts_clips, create_upload_schedule


class Pipeline:
    """LANstar 콘텐츠 자동화 파이프라인"""

    def __init__(self, voice_id: str = None, image_provider: str = "dalle"):
        self.voice_id = voice_id
        self.image_provider = image_provider
        self.channel_data = self._load_channel_data()
        self.results = {}

    def _load_channel_data(self) -> dict:
        """채널 분석 데이터 로드"""
        data_path = DATA_DIR / "lanstar_data.json"
        if data_path.exists():
            with open(data_path) as f:
                return json.load(f)
        return {}

    # ─── Stage 1: 스크립트 생성 ─────────────────────────

    def stage_script(
        self,
        product_name: str,
        product_model: str = "",
        product_features: list = None,
        category: str = "네트워크/서버",
        target_persona: str = "",
        pain_point: str = "",
        is_remake: bool = False,
        original_video_id: str = "",
        additional_context: str = "",
    ) -> dict:
        """Stage 2: Claude API로 스크립트 JSON 생성"""
        print("\n" + "="*60)
        print("📝 STAGE 2: AI 스크립트 생성")
        print("="*60)

        script = generate_script(
            product_name=product_name,
            product_model=product_model,
            product_features=product_features,
            category=category,
            target_persona=target_persona,
            pain_point=pain_point,
            is_remake=is_remake,
            original_video_id=original_video_id,
            additional_context=additional_context,
        )

        # 검증
        errors = validate_script(script)

        # SEO 최적화
        seo_result = optimize_seo(script, self.channel_data)
        script["seo"] = seo_result["seo"]

        # 저장
        path = save_script(script)
        self.results["script"] = script
        self.results["script_path"] = str(path)
        self.results["seo_score"] = seo_result["score"]

        # 리포트
        print(f"\n📋 스크립트 요약:")
        print(f"  제목: {script.get('headline',{}).get('main_title','')}")
        print(f"  장면 수: {len(script.get('scenes', []))}")
        print(f"  SEO 점수: {seo_result['score']}/100")
        print(f"  심리전술: {script.get('metadata',{}).get('psychology_tactics',[])}")

        return script

    def stage_script_from_remake(self, rank: int = 1) -> dict:
        """리메이크 후보에서 스크립트 생성"""
        candidates = self.channel_data.get("remakeCandidates", [])
        if rank > len(candidates):
            raise ValueError(f"리메이크 후보 {rank}순위가 없습니다. (총 {len(candidates)}개)")

        candidate = candidates[rank - 1]
        print(f"\n🔄 리메이크 대상: [{rank}순위] {candidate['title']}")
        print(f"   조회수: {candidate['viewCount']:,} | 경과: {candidate.get('ageDays',0)}일")

        script = generate_from_remake_candidate(candidate, self.channel_data)
        errors = validate_script(script)
        seo_result = optimize_seo(script, self.channel_data)
        script["seo"] = seo_result["seo"]

        path = save_script(script)
        self.results["script"] = script
        self.results["script_path"] = str(path)
        return script

    # ─── Stage 2: TTS 음성 생성 ─────────────────────────

    def stage_tts(self, script: dict = None) -> dict:
        """Stage 3-A: ElevenLabs TTS 음성 생성"""
        script = script or self.results.get("script")
        if not script:
            raise ValueError("스크립트가 없습니다. stage_script()를 먼저 실행하세요.")

        print("\n" + "="*60)
        print("🎤 STAGE 3-A: TTS 음성 생성")
        print("="*60)

        tts_result = tts_generate(script, voice_id=self.voice_id)
        self.results["tts"] = tts_result

        print(f"\n📋 TTS 요약:")
        print(f"  생성 파일: {len(tts_result.get('files', []))}개")
        print(f"  총 글자수: {tts_result.get('total_chars', 0):,}자")

        return tts_result

    # ─── Stage 3: 미디어 생성 ───────────────────────────

    def stage_media(self, script: dict = None) -> dict:
        """Stage 3-B: AI 이미지 + 스톡 미디어 생성"""
        script = script or self.results.get("script")
        if not script:
            raise ValueError("스크립트가 없습니다.")

        print("\n" + "="*60)
        print("🎨 STAGE 3-B: 미디어 소스 생성")
        print("="*60)

        media_result = media_generate(script, image_provider=self.image_provider)
        self.results["media"] = media_result

        print(f"\n📋 미디어 요약:")
        print(f"  생성 파일: {len(media_result.get('files', []))}개")
        print(f"  오류: {len(media_result.get('errors', []))}개")

        return media_result

    # ─── Stage 4: 영상 합성 ─────────────────────────────

    def stage_compose(self, script: dict = None) -> str:
        """Stage 4: JSON2Video 영상 합성"""
        script = script or self.results.get("script")
        tts_result = self.results.get("tts")
        media_result = self.results.get("media")

        if not script:
            raise ValueError("스크립트가 없습니다.")

        print("\n" + "="*60)
        print("🎬 STAGE 4: 영상 합성")
        print("="*60)

        video_path = compose_video(
            script,
            tts_result=tts_result,
            media_result=media_result,
        )
        self.results["video_path"] = video_path

        return video_path

    # ─── Stage 5: 배포 ──────────────────────────────────

    def stage_publish(
        self,
        script: dict = None,
        video_path: str = None,
        thumbnail_path: str = None,
        privacy: str = "private",
        scheduled_time: str = None,
        create_shorts: bool = True,
    ) -> dict:
        """Stage 5: YouTube 업로드 + 숏폼 리퍼포징"""
        script = script or self.results.get("script")
        video_path = video_path or self.results.get("video_path")

        if not script or not video_path:
            raise ValueError("스크립트와 영상이 필요합니다.")

        print("\n" + "="*60)
        print("📤 STAGE 5: 배포 & 리퍼포징")
        print("="*60)

        # 업로드
        upload_result = upload_from_script(
            script, video_path, thumbnail_path, privacy, scheduled_time
        )
        self.results["upload"] = upload_result

        # 숏폼 추출
        if create_shorts:
            shorts = extract_shorts_clips(script, video_path)
            self.results["shorts"] = shorts

        return upload_result

    # ─── 전체 파이프라인 ─────────────────────────────────

    def run_full(
        self,
        product_name: str = None,
        remake_rank: int = None,
        skip_tts: bool = False,
        skip_media: bool = False,
        skip_compose: bool = False,
        skip_publish: bool = True,  # 기본: 업로드 건너뜀 (Human-in-the-Loop)
        **kwargs,
    ) -> dict:
        """
        전체 파이프라인 실행

        Args:
            product_name: 제품명 (신규 영상)
            remake_rank: 리메이크 순위 (리메이크 모드)
            skip_*: 단계 건너뛰기
        """
        start_time = time.time()
        print("\n" + "🚀"*20)
        print("  LANstar 콘텐츠 자동화 파이프라인 시작")
        print("🚀"*20)

        # Stage 2: 스크립트 생성
        if remake_rank:
            script = self.stage_script_from_remake(remake_rank)
        elif product_name:
            script = self.stage_script(product_name=product_name, **kwargs)
        else:
            raise ValueError("product_name 또는 remake_rank를 지정해주세요.")

        # Human-in-the-Loop 검수 포인트
        print("\n" + "⚠️"*20)
        print("  📋 HUMAN-IN-THE-LOOP 검수 시점")
        print("  스크립트를 확인하고 수정이 필요하면 JSON을 직접 편집하세요.")
        print(f"  파일: {self.results.get('script_path', '')}")
        print("⚠️"*20)

        # Stage 3-A: TTS
        if not skip_tts:
            try:
                self.stage_tts(script)
            except Exception as e:
                print(f"⚠️ TTS 건너뜀: {e}")

        # Stage 3-B: 미디어
        if not skip_media:
            try:
                self.stage_media(script)
            except Exception as e:
                print(f"⚠️ 미디어 건너뜀: {e}")

        # Stage 4: 영상 합성
        if not skip_compose:
            try:
                self.stage_compose(script)
            except Exception as e:
                print(f"⚠️ 영상합성 건너뜀: {e}")

        # Stage 5: 배포
        if not skip_publish:
            try:
                self.stage_publish(script)
            except Exception as e:
                print(f"⚠️ 업로드 건너뜀: {e}")

        elapsed = time.time() - start_time

        # 최종 리포트
        print("\n" + "="*60)
        print("📊 파이프라인 실행 결과")
        print("="*60)
        print(f"  ⏱️ 총 소요시간: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
        print(f"  📝 스크립트: {'✅' if self.results.get('script') else '❌'}")
        print(f"  🎤 TTS: {'✅ ' + str(len(self.results.get('tts',{}).get('files',[]))) + '개' if self.results.get('tts') else '⏭️ 건너뜀'}")
        print(f"  🎨 미디어: {'✅ ' + str(len(self.results.get('media',{}).get('files',[]))) + '개' if self.results.get('media') else '⏭️ 건너뜀'}")
        print(f"  🎬 영상: {'✅' if self.results.get('video_path') else '⏭️ 건너뜀'}")
        print(f"  📤 업로드: {'✅' if self.results.get('upload') else '⏭️ 건너뜀'}")
        print(f"  📊 SEO 점수: {self.results.get('seo_score', '-')}/100")
        print("="*60)

        # 결과 저장
        report_path = OUTPUT_DIR / f"pipeline_report_{int(time.time())}.json"
        report = {k: v for k, v in self.results.items() if k != "script"}  # 스크립트는 이미 별도 저장
        report["elapsed_seconds"] = elapsed
        report["timestamp"] = datetime.now().isoformat()
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n📄 리포트 저장: {report_path}")

        return self.results


# ─── CLI ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LANstar YouTube 콘텐츠 자동화 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 신규 영상 생성
  python pipeline.py --product "HDMI 분배기" --model "LS-HD2SP" --category "영상/방송"

  # 리메이크 모드 (1순위 인기 영상)
  python pipeline.py --remake --top 1

  # 스크립트만 생성
  python pipeline.py --product "USB 독" --skip-tts --skip-media --skip-compose

  # 기존 스크립트로 TTS만 실행
  python pipeline.py --script output/script_xxx.json --stage tts --voice YOUR_VOICE_ID
        """
    )

    # 모드 선택
    parser.add_argument("--product", help="제품명 (신규 영상)")
    parser.add_argument("--model", default="", help="모델명")
    parser.add_argument("--category", default="네트워크/서버",
                        choices=["홈오피스/재택", "선정리/인테리어", "영상/방송", "네트워크/서버", "트러블슈팅"])
    parser.add_argument("--persona", default="", help="타겟 페르소나")
    parser.add_argument("--pain", default="", help="고통점")
    parser.add_argument("--features", nargs="+", help="제품 특징")

    # 리메이크 모드
    parser.add_argument("--remake", action="store_true", help="리메이크 모드")
    parser.add_argument("--top", type=int, default=1, help="리메이크 순위")

    # 단계별 실행
    parser.add_argument("--script", help="기존 스크립트 JSON 경로")
    parser.add_argument("--stage", choices=["tts", "media", "compose", "publish"], help="특정 단계만 실행")

    # 옵션
    parser.add_argument("--voice", help="ElevenLabs Voice ID")
    parser.add_argument("--image-provider", choices=["dalle", "flux"], default="dalle")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--skip-media", action="store_true")
    parser.add_argument("--skip-compose", action="store_true")
    parser.add_argument("--publish", action="store_true", help="업로드까지 실행")
    parser.add_argument("--privacy", default="private", choices=["public", "unlisted", "private"])

    args = parser.parse_args()
    pipe = Pipeline(voice_id=args.voice, image_provider=args.image_provider)

    # 기존 스크립트 + 특정 단계
    if args.script and args.stage:
        with open(args.script) as f:
            script = json.load(f)
        pipe.results["script"] = script

        if args.stage == "tts":
            pipe.stage_tts(script)
        elif args.stage == "media":
            pipe.stage_media(script)
        elif args.stage == "compose":
            pipe.stage_compose(script)
        elif args.stage == "publish":
            video_path = input("영상 파일 경로: ").strip()
            pipe.stage_publish(script, video_path)
        return

    # 전체 파이프라인
    if args.remake:
        pipe.run_full(
            remake_rank=args.top,
            skip_tts=args.skip_tts,
            skip_media=args.skip_media,
            skip_compose=args.skip_compose,
            skip_publish=not args.publish,
        )
    elif args.product:
        pipe.run_full(
            product_name=args.product,
            product_model=args.model,
            product_features=args.features,
            category=args.category,
            target_persona=args.persona,
            pain_point=args.pain,
            skip_tts=args.skip_tts,
            skip_media=args.skip_media,
            skip_compose=args.skip_compose,
            skip_publish=not args.publish,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
