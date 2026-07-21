import logging
import os
import asyncio
from datetime import datetime
from typing import List
from src.domain.activity import Activity
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.garmin_adapter import GarminAdapter
from src.infrastructure.repository import ActivityRepository
from src.domain.readiness_engine import ReadinessEngine, InsufficientHistoryError
from src.infrastructure.exceptions import InfrastructureError

# Logging estructurado para monitoreo del servicio
logger = logging.getLogger("presentation.telegram_bot")

# 1. Inyección explícita del archivo .env al entorno del sistema operativo
load_dotenv()

# 2. Extracción de credenciales
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")

# 3. Patrón Fail-Fast: Validación estricta de infraestructura antes del arranque
if not TELEGRAM_TOKEN or not GARMIN_EMAIL or not GARMIN_PASSWORD:
    logger.critical("Fallo de arranque: Credenciales de entorno (Telegram o Garmin) incompletas.")
    raise ValueError("Las variables de entorno requeridas no están configuradas en el archivo .env.")

# Configuración estricta del cliente de Telegram
bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

@dp.message(CommandStart())
async def send_welcome(message: Message) -> None:
    """Endpoint de presentación y onboarding del usuario."""
    await message.answer(
        "👋 <b>Bienvenido a Garmin Coach AI</b>\n\n"
        "Soy tu asistente fisiológico automatizado. Utiliza el comando /analizar "
        "para sincronizar tus últimas métricas y obtener un resumen de tu estado de forma."
    )

@dp.message(Command("analizar"))
async def analyze_performance(message: Message) -> None:
    """Orquesta la sincronización, persistencia y análisis de manera asíncrona sin bloquear el Event Loop."""
    if TELEGRAM_TOKEN is None or GARMIN_EMAIL is None or GARMIN_PASSWORD is None:
        await message.answer("⚠️ <b>Fallo de Servidor:</b> Credenciales de entorno corrompidas.")
        return

    # Feedback inmediato para UX
    status_msg = await message.answer("⏳ <i>Sincronizando métricas con Garmin Connect...</i>")
    
    try:
        # 1. Extracción (Offloading con Tipado Estricto y Scope Aislado)
        # Se inyectan los parámetros explícitamente para mantener la garantía de tipos (str)
        def _fetch_garmin_data(email: str, password: str) -> List[Activity]:
            adapter = GarminAdapter(email=email, password=password)
            return adapter.fetch_recent_activities(limit=30)

        # La variable activities asume estrictamente List[Activity]
        activities: List[Activity] = await asyncio.to_thread(
            _fetch_garmin_data, GARMIN_EMAIL, GARMIN_PASSWORD
        )
        
        if not activities:
            await status_msg.edit_text("ℹ️ No se encontraron actividades deportivas recientes.")
            return

        # 2. Persistencia (I/O Asíncrono Nativo)
        async with AsyncSessionLocal() as session:
            repository = ActivityRepository(session=session)
            inserted_count: int = await repository.bulk_upsert_activities(activities)

        # 3. Procesamiento Fisiológico
        assessment = ReadinessEngine.calculate_acwr(
            activities=activities, 
            target_date=datetime.now()
        )

        # 4. Construcción de la Vista
        informe = (
            f"📊 <b>REPORTE DE RENDIMIENTO</b>\n\n"
            f"🏃‍♂️ <b>Sesiones extraídas:</b> {len(activities)}\n"
            f"💾 <b>Nuevas sincronizadas:</b> {inserted_count}\n"
            f"⚡ <b>ACWR (Ratio de Carga):</b> {assessment.acwr}\n"
            f"⚠️ <b>Categoría de Riesgo:</b> {assessment.risk_category}\n\n"
            f"💡 <b>Análisis del Coach:</b>\n<i>{assessment.actionable_insight}</i>"
        )
        
        await status_msg.edit_text(informe)

    except InsufficientHistoryError as e:
        await status_msg.edit_text(f"📉 <b>Historial Insuficiente:</b> {str(e)}")
    except InfrastructureError as e:
        logger.error("Fallo de red en capa de presentación: %s", str(e))
        await status_msg.edit_text("❌ Fallo de conectividad con los servidores de Garmin. Intenta más tarde.")
    except Exception as e:
        logger.error("Excepción no controlada: %s", str(e))
        await status_msg.edit_text("❌ Ocurrió un error crítico al procesar los datos.")

async def main() -> None:
    """Punto de entrada del Event Loop para el microservicio del Bot."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger.info("Iniciando servicio de Telegram Bot (Polling mode)...")
    
    # Ignora mensajes enviados mientras el bot estaba apagado
    await bot.delete_webhook(drop_pending_updates=True) 
    
    logger.info("✅ Conexión establecida. El bot está escuchando eventos. (Presiona Ctrl+C para apagar)")
    
    # type: ignore silencia la advertencia estricta de Pylance por falta de stubs en aiogram
    await dp.start_polling(bot) # type: ignore 

if __name__ == "__main__":
    try:
        # Ejecución del Event Loop principal
        asyncio.run(main())
    except KeyboardInterrupt:
        # Graceful Shutdown: Apagado limpio sin tracebacks ruidosos
        logger.info("🛑 Servicio detenido manualmente por el usuario (SIGINT). Liberando recursos...")
    except Exception as e:
        # Captura de fallos críticos a nivel de sistema (ej. pérdida total de red)
        logger.critical("💥 Colapso crítico del microservicio: %s", str(e))