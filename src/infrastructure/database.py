import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

# Logging estructurado para auditoría de transacciones
logger = logging.getLogger("infrastructure.database")

# Cadena de conexión SQLite asíncrono.
# La arquitectura permite migrar a PostgreSQL en el futuro cambiando solo esta constante.
DATABASE_URL = "sqlite+aiosqlite:///./garmin_coach.db"

# Motor asíncrono (echo=False prohíbe imprimir las consultas SQL crudas en producción)
engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=False)

# Fábrica de sesiones fuertemente tipada
AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

class Base(DeclarativeBase):
    """Clase base estandarizada para los modelos ORM en SQLAlchemy 2.0"""
    pass

async def get_db_session():
    """
    Dependencia inyectable para FastAPI.
    Garantiza el cierre de la conexión y ejecuta rollbacks automáticos.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error("Fallo crítico en transacción de base de datos: %s", str(e))
            await session.rollback()
            raise
        finally:
            await session.close()