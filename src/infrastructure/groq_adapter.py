import logging
import os
from typing import List

from groq import AsyncGroq
from groq import APIConnectionError, APIStatusError, RateLimitError

from src.domain.activity import Activity
from src.domain.readiness_engine import WorkloadAssessment
from src.infrastructure.exceptions import InfrastructureError
from src.domain.biometrics import DailyBiometrics

logger = logging.getLogger("infrastructure.groq_adapter")

class GroqCoachAdapter:
    """
    Patrón Adapter: Encapsula el SDK de Groq (Llama-3).
    Demuestra la adherencia al Principio Abierto/Cerrado (OCP) de SOLID.
    """
    def __init__(self) -> None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            logger.critical("Fallo de infraestructura: GROQ_API_KEY no configurada.")
            raise ValueError("GROQ_API_KEY requerida en el archivo .env")
        
        # Cliente asíncrono nativo para operaciones I/O no bloqueantes
        self._client = AsyncGroq(api_key=api_key)
        
        # ACTUALIZACIÓN DE INFRAESTRUCTURA (Resolución EOL):
        # El modelo original fue decomisado. Migramos a la versión 3.3 de soporte 
        # extendido, garantizando alta velocidad de inferencia y razonamiento avanzado.
        self._model_id = "llama-3.3-70b-versatile"

    async def generate_personalized_plan(
        self, 
        assessment: WorkloadAssessment, 
        recent_sessions: List[Activity],
        daily_stats: DailyBiometrics  # Nueva dependencia inyectada
    ) -> str:
        """
        Genera el reporte cognitivo cruzando carga aguda (actividades) 
        con estrés sistémico (biometría diaria).
        """
        session_data = "\n".join([
            f"- Fecha: {act.timestamp.strftime('%Y-%m-%d')} | "
            f"Distancia: {round(act.distance_meters / 1000, 2)} km | "
            f"HR Promedio: {act.avg_heart_rate or 'N/A'} bpm"
            for act in recent_sessions[:5]
        ])

        system_prompt = (
            "Actúa como un entrenador de atletismo de élite y especialista en recuperación fisiológica. "
            "Redacta un reporte breve y directo dirigido al atleta. Tono motivador pero profesional.\n"
            "Analiza no solo los entrenamientos, sino cómo el pulso en reposo y la actividad basal (pasos) "
            "indican el estado del sistema nervioso central.\n"
            "Devuelve estrictamente el siguiente formato sin introducciones extra ni markdown de bloques de código:\n"
            "📋 ANÁLISIS TÉCNICO: [Análisis cruzado de entrenamientos vs. pulso en reposo]\n"
            "🛌 PLAN DE RECUPERACIÓN: [Acción para hoy basada en la fatiga sistémica]\n"
            "🏃 PRÓXIMO PASO: [Sugerencia de entrenamiento]"
        )
        
        user_prompt = (
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
            logger.info("Enviando telemetría al motor cognitivo Groq (Llama-3.3)...")
            
            response = await self._client.chat.completions.create(
                model=self._model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3, 
                max_tokens=600
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("El modelo retornó una respuesta vacía.")
                
            return str(content)
            
        except RateLimitError as e:
            logger.error("Límite de cuota excedido en Groq: %s", str(e))
            raise InfrastructureError("El motor de IA está saturado por límite de peticiones.") from e
        except APIStatusError as e:
            logger.error("Groq devolvió un error HTTP %d: %s", e.status_code, e.response.json())
            raise InfrastructureError("El proveedor de IA rechazó la petición.") from e
        except APIConnectionError as e:
            logger.error("Fallo de red al conectar con los servidores de Groq: %s", str(e))
            raise InfrastructureError("Error de comunicación de red con la capa cognitiva.") from e