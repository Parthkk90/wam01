from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import os
import logging
from pathlib import Path
from app.database import init_db
from app.routes import calls

# Resolve project paths once so startup is stable from any launch directory.
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"

# 1. Load environment variables first
load_dotenv(dotenv_path=ENV_FILE)

# 2. Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
STATIC_DIR = APP_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

# 3. Create FastAPI app
app = FastAPI(title="BrainBack.AI", description="Loan Officer Memory System")

# 4. Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Startup event
@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("✅ BrainBack.AI started — Ready to serve")

# 6. CONFIG API — served BEFORE static files
@app.get("/api/config")
async def get_config():
    return {
        "publicKey": os.getenv("VAPI_PUBLIC_KEY", ""),
        "assistantId": os.getenv("VAPI_ASSISTANT_ID", "")
    }

# 7. Include business logic routes
app.include_router(calls.router, prefix="/api")

# 8. Serve health status
@app.get("/health")
async def health():
    return {"status": "ok"}

# 9. Serve the frontend UI (index.html)
@app.get("/")
async def root():
    return FileResponse(str(INDEX_FILE))

# 10. Mount the static directory for and other assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")