import logging
import os
import asyncio
from datetime import datetime
from typing import List, Callable, Dict, Any, Awaitable

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, TelegramObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from src.infrastructure.database import AsyncSessionLocal, engine, Base
from src.infrastructure.garmin_adapter import GarminAdapter
from src.infrastructure.repository import ActivityRepository
from src.domain.activity import Activity
from src.domain.readiness_engine import ReadinessEngine, InsufficientHistoryError
from src.infrastructure.exceptions import InfrastructureError

# 1. Configuración de Loggers
logger = logging.getLogger("presentation.telegram_bot")

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")

if not TELEGRAM_TOKEN or not GARMIN_EMAIL or not GARMIN_PASSWORD:
    logger.critical("Fallo de arranque: Credenciales de entorno incompletas.")
    raise ValueError("Las variables de entorno requeridas no están configuradas.")

bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# --- CAPA DE OBSERVABILIDAD (MIDDLEWARE) ---
class RequestLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message) and event.text:
            user_id = event.from_user.id if event.from_user else "Unknown"
            logger.info("📩 Tráfico entrante - Usuario: %s | Comando: %s", user_id, event.text)
        return await handler(event, data)

dp.message.middleware(RequestLoggingMiddleware())

# --- ENDPOINTS ---
@dp.message(CommandStart())
async def send_welcome(message: Message) -> None:
    await message.answer(
        "👋 <b>Bienvenido a Garmin Coach AI</b>\n\n"
        "Soy tu asistente fisiológico automatizado. Utiliza el comando /analizar "
        "para sincronizar tus últimas métricas."
    )

@dp.message(Command("analizar"))
async def analyze_performance(message: Message) -> None:
    if TELEGRAM_TOKEN is None or GARMIN_EMAIL is None or GARMIN_PASSWORD is None:
        await message.answer("⚠️ <b>Fallo de Servidor:</b> Credenciales de entorno corrompidas.")
        return

    status_msg = await message.answer("⏳ <i>Sincronizando métricas con Garmin Connect...</i>")
    
    try:
        def _fetch_garmin_data(email: str, password: str) -> List[Activity]:
            adapter = GarminAdapter(email=email, password=password)
            return adapter.fetch_recent_activities(limit=30)

        activities: List[Activity] = await asyncio.to_thread(
            _fetch_garmin_data, GARMIN_EMAIL, GARMIN_PASSWORD
        )
        
        if not activities:
            await status_msg.edit_text("ℹ️ No se encontraron actividades deportivas recientes.")
            return

        async with AsyncSessionLocal() as session:
            repository = ActivityRepository(session=session)
            inserted_count: int = await repository.bulk_upsert_activities(activities)

        assessment = ReadinessEngine.calculate_acwr(
            activities=activities, 
            target_date=datetime.now()
        )

        # Mapeo de datos crudos para visualización (Prueba de extracción real)
        recent_sessions = activities[:3]
        sessions_text = ""
        for act in recent_sessions:
            dist_km = round(act.distance_meters / 1000, 2)
            date_str = act.timestamp.strftime("%d/%m/%Y")
            hr = act.avg_heart_rate if act.avg_heart_rate else "N/A"
            sessions_text += f"🔹 {date_str} - {dist_km} km (HR: {hr} bpm)\n"

        informe = (
            f"📊 <b>REPORTE DE RENDIMIENTO</b>\n\n"
            f"🏃‍♂️ <b>Sesiones extraídas:</b> {len(activities)}\n"
            f"💾 <b>Nuevas sincronizadas:</b> {inserted_count}\n"
            f"⚡ <b>ACWR (Ratio de Carga):</b> {assessment.acwr}\n"
            f"⚠️ <b>Categoría de Riesgo:</b> {assessment.risk_category}\n\n"
            f"📈 <b>Últimas Sesiones Registradas:</b>\n{sessions_text}\n"
            f"💡 <b>Análisis del Coach:</b>\n<i>{assessment.actionable_insight}</i>"
        )
        
        await status_msg.edit_text(informe)
        logger.info("Reporte fisiológico entregado con éxito al usuario.")

    except InsufficientHistoryError as e:
        await status_msg.edit_text(f"📉 <b>Historial Insuficiente:</b> {str(e)}")
    except InfrastructureError as e:
        logger.error("Fallo de red en capa de presentación: %s", str(e))
        await status_msg.edit_text("❌ Fallo de conectividad con los servidores de Garmin. Intenta más tarde.")
    except Exception as e:
        logger.error("Excepción no controlada: %s", str(e))
        await status_msg.edit_text("❌ Ocurrió un error crítico al procesar los datos.")

# --- INICIALIZACIÓN DEL MICROSERVICIO ---
async def main() -> None:
    # force=True toma el control absoluto del flujo de logs superando cualquier configuración previa
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True
    )
    
    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    logging.getLogger("aiohttp").setLevel(logging.CRITICAL)
    
    logger.info("Inicializando infraestructura de base de datos...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    logger.info("Iniciando servicio de Telegram Bot (Polling mode)...")
    await bot.delete_webhook(drop_pending_updates=True) 
    logger.info("✅ Conexión establecida. El bot está escuchando eventos. (Presiona Ctrl+C para apagar)")
    
    await dp.start_polling(bot) # type: ignore 

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Servicio detenido manualmente por el usuario (SIGINT). Liberando recursos...")
    except Exception as e:
        logger.critical("💥 Colapso crítico del microservicio: %s", str(e))