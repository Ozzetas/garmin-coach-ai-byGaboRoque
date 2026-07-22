import logging
import os
import asyncio
from datetime import datetime, date
from typing import List, Callable, Dict, Any, Awaitable, Tuple

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, BaseMiddleware, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, TelegramObject, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.infrastructure.database import AsyncSessionLocal, engine, Base
from src.infrastructure.garmin_adapter import GarminAdapter
from src.infrastructure.repository import ActivityRepository
from src.domain.activity import Activity
from src.domain.biometrics import DailyBiometrics
from src.domain.readiness_engine import ReadinessEngine, InsufficientHistoryError
from src.infrastructure.exceptions import InfrastructureError
from src.infrastructure.groq_adapter import GroqCoachAdapter

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

# --- MÁQUINA DE ESTADOS (FSM) ---
class CoachFlow(StatesGroup):
    """Define los estados transaccionales de la conversación con el usuario."""
    waiting_for_goal = State()

# --- ENDPOINTS ---
@dp.message(CommandStart())
async def send_welcome(message: Message) -> None:
    await message.answer(
        "👋 <b>Bienvenido a Garmin Coach AI</b>\n\n"
        "Soy tu asistente fisiológico automatizado especializado en deportes de resistencia. "
        "Utiliza el comando /analizar para comenzar."
    )

@dp.message(Command("analizar"))
async def start_analysis_flow(message: Message, state: FSMContext) -> None:
    """
    Inicia la FSM. Despliega un teclado restrictivo para evitar inyección de 
    datos no estructurados por parte del usuario.
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏃 5K - 10K (Corta Distancia)")],
            [KeyboardButton(text="🏃 21K - 42K (Larga Distancia)")],
            [KeyboardButton(text="🧘‍♂️ Calidad de Vida / Mantenimiento")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await message.answer(
        "🎯 <b>Definición de Objetivo Estructural</b>\n\n"
        "Para alinear tu biometría con la carga de entrenamiento adecuada, "
        "selecciona tu objetivo actual:",
        reply_markup=keyboard
    )
    await state.set_state(CoachFlow.waiting_for_goal)

@dp.message(CoachFlow.waiting_for_goal, F.text)
async def process_performance_goal(message: Message, state: FSMContext) -> None:
    """
    Endpoint bloqueante: Solo se ejecuta si el usuario seleccionó un objetivo.
    Ejecuta el pipeline ETL y el análisis cognitivo inyectando el objetivo.
    """
    user_goal = str(message.text)
    
    # Liberamos la sesión transaccional del usuario inmediatamente
    await state.clear()
    
    if TELEGRAM_TOKEN is None or GARMIN_EMAIL is None or GARMIN_PASSWORD is None:
        await message.answer("⚠️ <b>Fallo de Servidor:</b> Credenciales de entorno corrompidas.", reply_markup=ReplyKeyboardRemove())
        return

    # DESACOPLAMIENTO DE UI: 
    # 1. Confirmación e instrucción de limpieza de teclado (Fire and Forget)
    await message.answer(
        f"✅ Objetivo registrado: <i>{user_goal}</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # 2. Instanciación del Tracker de Estado (Volátil y Editable)
    status_msg = await message.answer("⏳ <i>Sincronizando telemetría holística con Garmin Connect...</i>")
    
    try:
        def _fetch_garmin_data(email: str, password: str) -> Tuple[List[Activity], DailyBiometrics]:
            adapter = GarminAdapter(email=email, password=password)
            acts = adapter.fetch_recent_activities(limit=30)
            today = date.today()
            bio = adapter.fetch_daily_biometrics(target_date=today)
            return acts, bio

        activities, daily_stats = await asyncio.to_thread(
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

        await status_msg.edit_text("🧠 <i>Analizando biometría cruzada con motor cognitivo Llama-3.3...</i>")
        
        llm_adapter = GroqCoachAdapter()
        
        ai_insight = await llm_adapter.generate_personalized_plan(
            assessment=assessment,
            recent_sessions=activities,
            daily_stats=daily_stats,
            user_goal=user_goal
        )

        recent_sessions = activities[:3]
        sessions_text = ""
        for act in recent_sessions:
            dist_km = round(act.distance_meters / 1000, 2)
            date_str = act.timestamp.strftime("%d/%m/%Y")
            hr = act.avg_heart_rate if act.avg_heart_rate else "N/A"
            sessions_text += f"🔹 {date_str} - {dist_km} km (HR: {hr} bpm)\n"

        informe = (
            f"📊 <b>REPORTE DE RENDIMIENTO HOLÍSTICO</b>\n\n"
            f"🎯 <b>Objetivo:</b> {user_goal}\n"
            f"💾 <b>Registros Sincronizados:</b> {inserted_count}\n"
            f"👟 <b>Pasos de hoy:</b> {daily_stats.total_steps}\n"
            f"🫀 <b>FC Reposo:</b> {daily_stats.resting_heart_rate or '--'} bpm\n"
            f"⚡ <b>ACWR (Ratio de Carga):</b> {assessment.acwr}\n"
            f"⚠️ <b>Riesgo Estructural:</b> {assessment.risk_category}\n\n"
            f"📈 <b>Últimas Sesiones:</b>\n{sessions_text}\n"
            f"💡 <b>Análisis Técnico:</b>\n{ai_insight.analisis_tecnico}\n\n"
            f"🛌 <b>Plan de Recuperación:</b>\n{ai_insight.plan_recuperacion}\n\n"
            f"🏃 <b>Próximo Paso:</b>\n{ai_insight.proximo_paso}"
        )
        
        await status_msg.edit_text(informe)
        logger.info("Reporte fisiológico entregado con éxito al usuario.")

    except InsufficientHistoryError as e:
        await status_msg.edit_text(f"📉 <b>Historial Insuficiente:</b> {str(e)}")
    except InfrastructureError as e:
        logger.error("Fallo de infraestructura: %s", str(e))
        await status_msg.edit_text(f"❌ Fallo de servicio: {str(e)}")
    except Exception as e:
        logger.error("Excepción no controlada: %s", str(e))
        await status_msg.edit_text("❌ Ocurrió un error crítico al procesar los datos.")

# --- INICIALIZACIÓN DEL MICROSERVICIO ---
async def main() -> None:
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