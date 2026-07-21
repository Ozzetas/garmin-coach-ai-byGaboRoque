import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_db_session, engine, Base
from src.infrastructure.repository import ActivityRepository
from src.infrastructure.garmin_adapter import GarminAdapter
from src.infrastructure.exceptions import (
    GarminAuthenticationError,
    GarminRateLimitError,
    InfrastructureError,
)
from src.domain.readiness_engine import (
    ReadinessEngine,
    WorkloadAssessment,
    InsufficientHistoryError,
)

logger = logging.getLogger("application.api")

# --- EVENTOS DE CICLO DE VIDA (STARTUP / SHUTDOWN) ---
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Genera el esquema físico de la base de datos de forma asíncrona al iniciar el servidor."""
    logger.info("Inicializando infraestructura de persistencia...")
    async with engine.begin() as conn:
        # En producción corporativa se usa Alembic; para MVP/Portfolio, create_all es óptimo
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Liberación de conexiones al apagar el servidor
    await engine.dispose()
    logger.info("Recursos de base de datos liberados exitosamente.")

# Inicialización de la aplicación con gestor de contexto
app = FastAPI(
    title="Garmin Coach AI",
    description="Motor de análisis fisiológico basado en métricas de Garmin Connect.",
    version="1.0.0",
    lifespan=lifespan
)

# --- SCHEMAS DE ENTRADA Y SALIDA ---
class SyncRequest(BaseModel):
    email: str = Field(..., description="Correo electrónico de la cuenta Garmin")
    password: str = Field(..., description="Contraseña de la cuenta Garmin")
    limit: int = Field(default=30, le=100, description="Límite de actividades a procesar")

class ReadinessResponse(BaseModel):
    assessment: WorkloadAssessment
    activities_analyzed: int
    new_activities_saved: int = Field(..., description="Cantidad de actividades nuevas agregadas a la BD local")
    timestamp: datetime = Field(default_factory=datetime.now)

# --- ENDPOINTS ---
@app.post(
    "/api/v1/sync-and-analyze", 
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincroniza actividades recientes, persiste los deltas y calcula el ACWR"
)
async def sync_and_analyze_readiness(
    payload: SyncRequest,
    db_session: AsyncSession = Depends(get_db_session)
) -> ReadinessResponse:
    """
    Orquesta la extracción (Infraestructura), la persistencia (Repositorio) 
    y el análisis de carga deportiva (Dominio).
    """
    logger.info("Iniciando solicitud de sincronización para el usuario: %s", payload.email)
    
    try:
        # 1. Ingesta de datos (Garmin Connect)
        adapter = GarminAdapter(email=payload.email, password=payload.password)
        activities = adapter.fetch_recent_activities(limit=payload.limit)

        if not activities:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontraron actividades deportivas recientes."
            )

        # 2. Persistencia Segura (Capa de Datos)
        repository = ActivityRepository(session=db_session)
        inserted_count = await repository.bulk_upsert_activities(activities)

        # 3. Análisis Fisiológico (Motor de Negocio)
        assessment = ReadinessEngine.calculate_acwr(
            activities=activities, 
            target_date=datetime.now()
        )

        return ReadinessResponse(
            assessment=assessment,
            activities_analyzed=len(activities),
            new_activities_saved=inserted_count
        )

    # 4. Manejo Estricto de Errores a HTTP Status
    except GarminAuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except GarminRateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except InsufficientHistoryError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except InfrastructureError as e:
        logger.error("Error estructural en el backend: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Error interno al procesar los datos de salud."
        )