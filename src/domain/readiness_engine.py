import logging
from datetime import datetime, timedelta
from typing import List
from pydantic import BaseModel, Field

from src.domain.activity import Activity

# Logging estructurado para auditoría analítica
logger = logging.getLogger("domain.readiness_engine")

class DomainError(Exception):
    """Excepción base para violaciones de reglas de negocio."""
    pass

class InsufficientHistoryError(DomainError):
    """Lanzada cuando el algoritmo carece de datos crónicos suficientes."""
    pass

class WorkloadAssessment(BaseModel):
    """Objeto de valor (Value Object) que encapsula el resultado del análisis."""
    acwr: float = Field(..., description="Acute-to-Chronic Workload Ratio")
    risk_category: str = Field(..., description="Clasificación del riesgo físico")
    actionable_insight: str = Field(..., description="Recomendación automatizada")

class ReadinessEngine:
    """Motor estático de análisis fisiológico."""

    @staticmethod
    def _calculate_session_load(activity: Activity) -> float:
        """
        Calcula la carga interna (TRIMP básico) si hay datos cardíacos, 
        o recae en la carga externa (volumen/distancia) como mecanismo de fallback.
        """
        if activity.avg_heart_rate is not None:
            duration_minutes: float = activity.duration_seconds / 60.0
            return duration_minutes * activity.avg_heart_rate
        
        # Fallback: Normalización arbitraria del volumen en metros
        return activity.distance_meters / 100.0

    @staticmethod
    def calculate_acwr(activities: List[Activity], target_date: datetime) -> WorkloadAssessment:
        """
        Procesa el histórico inmutable de sesiones para predecir picos de forma
        o vulnerabilidad a lesiones tisulares.
        """
        seven_days_prior = target_date - timedelta(days=7)
        twenty_eight_days_prior = target_date - timedelta(days=28)

        acute_load: float = 0.0
        chronic_load: float = 0.0

        for activity in activities:
            if seven_days_prior <= activity.timestamp <= target_date:
                acute_load += ReadinessEngine._calculate_session_load(activity)
            if twenty_eight_days_prior <= activity.timestamp <= target_date:
                chronic_load += ReadinessEngine._calculate_session_load(activity)

        chronic_weekly_average: float = chronic_load / 4.0

        # Manejo explícito de borde: División por cero o falta de datos
        if chronic_weekly_average == 0.0:
            logger.warning("Fallo analítico: Historial insuficiente para target_date %s", target_date)
            raise InsufficientHistoryError("Se requieren al menos 28 días de registro para asimilar carga crónica.")

        acwr: float = round(acute_load / chronic_weekly_average, 2)

        # Matriz de reglas de negocio (Sweet Spot: 0.8 - 1.3)
        if acwr > 1.5:
            risk = "ALTO_RIESGO_LESION"
            insight = "Sobrecarga aguda detectada. Priorizar recuperación pasiva inmediatamente."
        elif 0.8 <= acwr <= 1.3:
            risk = "ZONA_OPTIMA"
            insight = "Progresión de carga estructural correcta. Mantener el volumen actual."
        else:
            risk = "SUBENTRENAMIENTO"
            insight = "Pérdida de adaptaciones aeróbicas. Ventana abierta para incrementar volumen."

        logger.info("Análisis ACWR completado: %f (%s)", acwr, risk)
        
        return WorkloadAssessment(
            acwr=acwr,
            risk_category=risk,
            actionable_insight=insight
        )