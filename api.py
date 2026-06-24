from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request

from config import WEBHOOK_SECRET
from sleep_analysis import SleepApkPayload, build_sleep_report


def verify_secret(request: Request) -> None:
    if not WEBHOOK_SECRET:
        return

    query_secret = request.query_params.get("secret")
    header_secret = request.headers.get("X-Webhook-Secret")
    if WEBHOOK_SECRET not in (query_secret, header_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


async def parse_sleep_payload(request: Request) -> SleepApkPayload:
    try:
        raw_data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if not isinstance(raw_data, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    try:
        return SleepApkPayload(**raw_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}") from exc


def create_app(bot: Bot) -> FastAPI:
    app = FastAPI(title="Somnus Sleep Bot")

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/webhook/sleep-apk")
    async def sleep_apk_webhook(request: Request) -> dict[str, bool | str]:
        verify_secret(request)
        payload = await parse_sleep_payload(request)
        report = build_sleep_report(payload)
        await bot.send_message(chat_id=payload.telegram_id, text=report, parse_mode="HTML")
        return {"ok": True, "message": "Sleep APK report sent"}

    @app.post("/webhook/sleep")
    async def sleep_webhook_alias(request: Request) -> dict[str, bool | str]:
        return await sleep_apk_webhook(request)

    return app
