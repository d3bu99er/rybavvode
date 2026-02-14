import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.admin import router as admin_router
from app.api.public import router as public_router
from app.config import get_settings
from app.database import SessionLocal
from app.services.sync_service import SyncService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
app = FastAPI(title="Fishing Map MVP")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=False, same_site="lax")

app.include_router(public_router)
app.include_router(admin_router)

scheduler = AsyncIOScheduler()
sync_service = SyncService()


async def scrape_job():
    db = SessionLocal()
    try:
        await sync_service.run(db)
    except Exception:
        logger.exception("Scheduled scraping failed")
        db.rollback()
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    scheduler.add_job(scrape_job, "interval", seconds=settings.fetch_interval_seconds, id="scrape_forum", replace_existing=True)
    scheduler.start()
    asyncio.create_task(scrape_job())


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown(wait=False)
