"""
LANstar YouTube 콘텐츠 자동화 파이프라인 - FastAPI 웹 서버
Render 배포용 진입점
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

# ─── 환경변수에서 config 동적 설정 ─────────────────────────
import config
config.ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
config.YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
config.ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
config.PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
config.JSON2VIDEO_API_KEY = os.environ.get("JSON2VIDEO_API_KEY", "")
config.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

from modules.script_generator import generate_script, validate_script, save_script, generate_from_remake_candidate
from modules.seo_optimizer import optimize_seo, analyze_competition
from modules.publisher import create_upload_schedule, auto_detect_shorts_segments

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ─── Lifespan ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 LANstar YouTube Automation Pipeline 시작")
    yield
    print("👋 서버 종료")


# ─── FastAPI 앱 ──────────────────────────────────────────

app = FastAPI(
    title="LANstar YouTube Automation",
    description="AI 스토리텔링 기반 페이스리스 콘텐츠 자동화 파이프라인",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
static_dir = BASE_DIR / "frontend" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ─── Pydantic 모델 ──────────────────────────────────────

class ScriptRequest(BaseModel):
    product_name: str = Field(..., description="제품명")
    product_model: str = Field("", description="모델명")
    product_features: list[str] = Field(default=[], description="제품 특징")
    category: str = Field("네트워크/서버", description="카테고리")
    target_persona: str = Field("", description="타겟 페르소나")
    pain_point: str = Field("", description="고통점")
    additional_context: str = Field("", description="추가 맥락")
    is_remake: bool = Field(False, description="리메이크 여부")
    original_video_id: str = Field("", description="원본 영상 ID")


class RemakeRequest(BaseModel):
    rank: int = Field(1, description="리메이크 순위 (1~30)", ge=1, le=30)


class CompetitionRequest(BaseModel):
    keyword: str = Field(..., description="분석할 키워드")


class ScheduleRequest(BaseModel):
    script_ids: list[str] = Field(default=[], description="스크립트 파일명 리스트")
    uploads_per_week: int = Field(3, description="주당 업로드 횟수")
    preferred_days: list[int] = Field(default=[1, 3, 5], description="선호 요일 (0=월~6=일)")
    preferred_time: str = Field("18:00", description="업로드 시간")
    start_date: str = Field("", description="시작일 (YYYY-MM-DD)")


# ─── 유틸 ────────────────────────────────────────────────

def load_channel_data() -> dict:
    path = BASE_DIR / "lanstar_data.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def list_scripts() -> list:
    """output 디렉토리의 스크립트 목록"""
    scripts = []
    for f in sorted(OUTPUT_DIR.iterdir()):
        if f.name.startswith("script_") and f.name.endswith(".json"):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                scripts.append({
                    "filename": f.name,
                    "title": data.get("headline", {}).get("main_title", ""),
                    "category": data.get("metadata", {}).get("category", ""),
                    "scenes": len(data.get("scenes", [])),
                    "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
            except Exception:
                pass
    return scripts


# ─── API 엔드포인트 ──────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """프론트엔드 메인 페이지"""
    frontend = BASE_DIR / "frontend" / "index.html"
    if frontend.exists():
        return FileResponse(str(frontend))
    return HTMLResponse("<h1>LANstar YouTube Automation API</h1><p><a href='/docs'>API 문서</a></p>")


@app.get("/api/health")
async def health():
    """헬스체크"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "api_keys": {
            "anthropic": bool(config.ANTHROPIC_API_KEY),
            "youtube": bool(config.YOUTUBE_API_KEY),
            "elevenlabs": bool(config.ELEVENLABS_API_KEY),
            "pexels": bool(config.PEXELS_API_KEY),
            "json2video": bool(config.JSON2VIDEO_API_KEY),
            "openai": bool(config.OPENAI_API_KEY),
        },
    }


# ── 채널 분석 ──

@app.get("/api/channel/stats")
async def channel_stats():
    """채널 기본 통계"""
    data = load_channel_data()
    if not data:
        raise HTTPException(404, "채널 분석 데이터가 없습니다. youtube_analyzer.py를 먼저 실행하세요.")
    return {
        "channelName": data.get("channelName"),
        "subscriberCount": data.get("subscriberCount"),
        "totalVideos": data.get("totalVideos"),
        "totalViews": data.get("totalViews"),
        "avgViews": data.get("avgViews"),
        "avgEngagement": data.get("avgEngagement"),
        "categoryStats": data.get("categoryStats"),
        "dayStats": data.get("dayStats"),
    }


@app.get("/api/channel/top-videos")
async def top_videos(sort: str = "views", limit: int = 20):
    """TOP 영상 목록"""
    data = load_channel_data()
    if not data:
        raise HTTPException(404, "채널 데이터 없음")

    key_map = {"views": "topByViews", "engagement": "topByEngagement", "likes": "topByLikes"}
    key = key_map.get(sort, "topByViews")
    return data.get(key, [])[:limit]


@app.get("/api/channel/remake-candidates")
async def remake_candidates(limit: int = 30):
    """리메이크 후보 목록"""
    data = load_channel_data()
    if not data:
        raise HTTPException(404, "채널 데이터 없음")
    return data.get("remakeCandidates", [])[:limit]


@app.get("/api/channel/dashboard")
async def dashboard():
    """분석 대시보드 HTML"""
    path = BASE_DIR / "lanstar_dashboard.html"
    if path.exists():
        return FileResponse(str(path), media_type="text/html")
    raise HTTPException(404, "대시보드 파일 없음")


# ── 스크립트 생성 ──

@app.post("/api/script/generate")
async def api_generate_script(req: ScriptRequest):
    """AI 스크립트 생성 (Claude API)"""
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY가 설정되지 않았습니다.")

    try:
        script = generate_script(
            product_name=req.product_name,
            product_model=req.product_model,
            product_features=req.product_features or None,
            category=req.category,
            target_persona=req.target_persona,
            pain_point=req.pain_point,
            additional_context=req.additional_context,
            is_remake=req.is_remake,
            original_video_id=req.original_video_id,
        )

        errors = validate_script(script)
        channel_data = load_channel_data()
        seo_result = optimize_seo(script, channel_data)
        script["seo"] = seo_result["seo"]

        path = save_script(script)

        return {
            "success": True,
            "filename": Path(path).name,
            "title": script.get("headline", {}).get("main_title", ""),
            "scenes": len(script.get("scenes", [])),
            "seo_score": seo_result["score"],
            "validation_errors": errors,
            "script": script,
        }
    except Exception as e:
        raise HTTPException(500, f"스크립트 생성 실패: {str(e)}")


@app.post("/api/script/remake")
async def api_remake_script(req: RemakeRequest):
    """리메이크 후보 기반 스크립트 생성"""
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY가 설정되지 않았습니다.")

    data = load_channel_data()
    candidates = data.get("remakeCandidates", [])
    if req.rank > len(candidates):
        raise HTTPException(400, f"리메이크 후보 {req.rank}순위가 없습니다.")

    try:
        candidate = candidates[req.rank - 1]
        script = generate_from_remake_candidate(candidate, data)

        errors = validate_script(script)
        seo_result = optimize_seo(script, data)
        script["seo"] = seo_result["seo"]

        path = save_script(script)

        return {
            "success": True,
            "filename": Path(path).name,
            "original_title": candidate["title"],
            "original_views": candidate["viewCount"],
            "new_title": script.get("headline", {}).get("main_title", ""),
            "scenes": len(script.get("scenes", [])),
            "seo_score": seo_result["score"],
            "script": script,
        }
    except Exception as e:
        raise HTTPException(500, f"리메이크 스크립트 생성 실패: {str(e)}")


@app.get("/api/scripts")
async def api_list_scripts():
    """생성된 스크립트 목록"""
    return list_scripts()


@app.get("/api/scripts/{filename}")
async def api_get_script(filename: str):
    """스크립트 상세 조회"""
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "스크립트를 찾을 수 없습니다.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── SEO & 경쟁분석 ──

@app.post("/api/seo/competition")
async def api_competition(req: CompetitionRequest):
    """키워드 경쟁 분석"""
    data = load_channel_data()
    return analyze_competition(req.keyword, data)


# ── 스케줄 ──

@app.post("/api/schedule/create")
async def api_create_schedule(req: ScheduleRequest):
    """업로드 스케줄 생성"""
    scripts = []
    for sid in req.script_ids:
        path = OUTPUT_DIR / sid
        if path.exists():
            with open(path, encoding="utf-8") as f:
                scripts.append(json.load(f))

    if not scripts:
        raise HTTPException(400, "유효한 스크립트가 없습니다.")

    schedule = create_upload_schedule(
        scripts,
        start_date=req.start_date or None,
        uploads_per_week=req.uploads_per_week,
        preferred_days=req.preferred_days,
        preferred_time=req.preferred_time,
    )
    return schedule


# ── 파이프라인 보고서 ──

@app.get("/api/reports")
async def api_list_reports():
    """파이프라인 실행 보고서 목록"""
    reports = []
    for f in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if f.name.startswith("pipeline_report_") and f.name.endswith(".json"):
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            reports.append({
                "filename": f.name,
                "timestamp": data.get("timestamp", ""),
                "elapsed": data.get("elapsed_seconds", 0),
            })
    return reports


# ─── 프론트엔드 SPA ──────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """채널 분석 대시보드"""
    path = BASE_DIR / "lanstar_dashboard.html"
    if path.exists():
        return FileResponse(str(path), media_type="text/html")
    raise HTTPException(404)


# ─── 실행 ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
