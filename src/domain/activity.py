import logging
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator

# Configuración de logging estructurado (Estándar de producción)
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("domain.activity")

class Activity(BaseModel):
    """
    Entidad Core: Representa una sesión de running inmutable.
    Aplica tipado estricto y validación en tiempo de ejecución.
    """
    activity_id: str = Field(..., description="ID único de Garmin")
    timestamp: datetime = Field(..., description="Fecha de la sesión")
    distance_meters: float = Field(..., description="Distancia total")
    duration_seconds: float = Field(..., gt=0.0, description="Tiempo activo")
    avg_heart_rate: Optional[int] = Field(default=None, description="BPM promedio")

    @field_validator("distance_meters")
    @classmethod
    def validate_gps_distance(cls, value: float) -> float:
        """Valida que los artefactos del GPS no arrojen métricas negativas."""
        if value < 0.0:
            logger.error("Integridad comprometida: Distancia negativa (%s m).", value)
            raise ValueError("La distancia no puede ser negativa.")
        return value

    @field_validator("avg_heart_rate")
    @classmethod
    def validate_biological_limits(cls, value: Optional[int]) -> Optional[int]:
        """Valida umbrales biológicos del sensor cardíaco."""
        if value is not None and (value < 30 or value > 220):
            logger.error("Lectura anómala del sensor: %s BPM.", value)
            raise ValueError("Frecuencia cardíaca fuera de límites biológicos.")
        return value

    @property
    def pace_min_per_km(self) -> float:
        """Calcula el ritmo en minutos por kilómetro."""
        if self.distance_meters == 0.0:
            return 0.0
        return round((self.duration_seconds / 60.0) / (self.distance_meters / 1000.0), 2)