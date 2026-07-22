import logging
import os
import json
from typing import List
from pydantic import BaseModel, Field, ValidationError

from groq import AsyncGroq
from groq import APIConnectionError, APIStatusError, RateLimitError

from src.domain.activity import Activity
from src.domain.readiness_engine import WorkloadAssessment
from src.infrastructure.exceptions import InfrastructureError
from src.domain.biometrics import DailyBiometrics

logger = logging.getLogger("infrastructure.groq_adapter")

class CoachInsight(BaseModel):
    analisis_tecnico: str = Field(..., description="Análisis cruzado de entrenamientos vs. pulso en reposo considerando el objetivo del atleta")
    plan_recuperacion: str = Field(..., description="Acción sugerida para hoy basada en la fatiga sistémica")
    proximo_paso: str = Field(..., description="Sugerencia específica para el próximo entrenamiento alineada al objetivo")

class GroqCoachAdapter:
    def __init__(self) -> None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            logger.critical("Fallo de infraestructura: GROQ_API_KEY no configurada.")
            raise ValueError("GROQ_API_KEY requerida en el archivo .env")
        
        self._client = AsyncGroq(api_key=api_key)
        self._model_id = "llama-3.3-70b-versatile"

    async def generate_personalized_plan(
        self, 
        assessment: WorkloadAssessment, 
        recent_sessions: List[Activity],
        daily_stats: DailyBiometrics,
        user_goal: str  # Dependencia inyectada desde el Frontend
    ) -> CoachInsight:
        
        session_data = "\n".join([
            f"- Fecha: {act.timestamp.strftime('%Y-%m-%d')} | "
            f"Distancia: {round(act.distance_meters / 1000, 2)} km | "
            f"HR Promedio: {act.avg_heart_rate or 'N/A'} bpm"
            for act in recent_sessions[:5]
        ])

        schema_json = json.dumps(CoachInsight.model_json_schema(), indent=2)
        system_prompt = (
            "Actúa como un entrenador de atletismo de élite y especialista en recuperación fisiológica. "
            "Debes analizar las métricas biométricas evaluando la coherencia entre el estado actual del cuerpo "
            "y el objetivo deportivo de resistencia seleccionado por el usuario. "
            "Devuelve tu diagnóstico ESTRICTAMENTE en formato JSON cumpliendo este esquema:\n"
            f"{schema_json}"
        )
        
        user_prompt = (
            f"OBJETIVO DEL ATLETA: {user_goal}\n\n"
            f"MÉTRICA ACWR: {assessment.acwr}\n"
            f"RIESGO: {assessment.risk_category}\n"
            f"DIAGNÓSTICO BASE: {assessment.actionable_insight}\n\n"
            f"BIOMETRÍA DE HOY ({daily_stats.target_date}):\n"
            f"- Pasos: {daily_stats.total_steps}\n"
            f"- FC Reposo: {daily_stats.resting_heart_rate or 'N/A'} bpm\n"
            f"- FC Mín/Máx (24h): {daily_stats.min_heart_rate or 'N/A'} / {daily_stats.max_heart_rate or 'N/A'} bpm\n\n"
            f"ÚLTIMOS ENTRENAMIENTOS:\n{session_data}"
        )

        try:
            logger.info("Enviando telemetría estructurada al motor cognitivo Groq (Llama-3.3)...")
            
            response = await self._client.chat.completions.create(
                model=self._model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2, 
                max_tokens=600,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("El modelo retornó una respuesta vacía.")
            
            return CoachInsight.model_validate_json(content)
            
        except ValidationError as e:
            logger.error("Error de contrato de datos. La IA devolvió un JSON inválido: %s", str(e))
            raise InfrastructureError("Fallo en el procesamiento semántico de los datos cognitivos.") from e
        except (RateLimitError, APIStatusError, APIConnectionError) as e:
            logger.error("Error en la API de Groq: %s", str(e))
            raise InfrastructureError("Error de comunicación de red con la capa cognitiva.") from e
        except Exception as e:
            logger.error("Error crítico inesperado en el adaptador IA: %s", str(e))
            raise InfrastructureError("Error interno en el procesamiento cognitivo.") from e