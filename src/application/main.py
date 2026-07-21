import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

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

# Configuración de logger para la capa de aplicación
logger = logging.getLogger("application.api")

app = FastAPI(
    title="Garmin Coach AI",
    description="Motor de análisis fisiológico basado en métricas de Garmin Connect.",
    version="1.0.0"
)

# --- SCHEMAS DE ENTRADA Y SALIDA (Tipado Estricto) ---

class SyncRequest(BaseModel):
    """Payload seguro para recibir credenciales sin exponerlas en la URL."""
    email: str = Field(..., description="Correo electrónico de la cuenta Garmin")
    password: str = Field(..., description="Contraseña de la cuenta Garmin")
    limit: int = Field(default=30, le=100, description="Límite de actividades a procesar")

class ReadinessResponse(BaseModel):
    """Estructura de respuesta validada para el cliente."""
    assessment: WorkloadAssessment
    activities_analyzed: int
    timestamp: datetime = Field(default_factory=datetime.now)

# --- ENDPOINTS ---

@app.post(
    "/api/v1/sync-and-analyze", 
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincroniza actividades recientes y calcula el ACWR"
)
async def sync_and_analyze_readiness(payload: SyncRequest) -> ReadinessResponse:
    """
    Orquesta la extracción de datos desde infraestructura y delega 
    el análisis de carga aguda/crónica al motor de dominio.
    """
    logger.info("Iniciando solicitud de sincronización para el usuario: %s", payload.email)
    
    try:
        # 1. Ingesta de datos (Infraestructura)
        adapter = GarminAdapter(email=payload.email, password=payload.password)
        activities = adapter.fetch_recent_activities(limit=payload.limit)

        if not activities:
            logger.warning("Sincronización exitosa pero sin actividades registradas.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontraron actividades deportivas recientes en esta cuenta."
            )

        # 2. Análisis fisiológico (Dominio)
        assessment = ReadinessEngine.calculate_acwr(
            activities=activities, 
            target_date=datetime.now()
        )

        return ReadinessResponse(
            assessment=assessment,
            activities_analyzed=len(activities)
        )

    # 3. Manejo de Errores Estructurado y Traducción a HTTP
    except GarminAuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail=str(e)
        )
    except GarminRateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, 
            detail=str(e)
        )
    except InsufficientHistoryError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
            detail=str(e)
        )
    except InfrastructureError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Fallo de conectividad con los servidores de Garmin. Intente más tarde."
        )