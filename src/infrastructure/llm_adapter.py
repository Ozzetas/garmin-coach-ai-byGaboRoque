import logging
import os
from typing import List

from google import genai
from google.genai.errors import APIError

from src.domain.activity import Activity
from src.domain.readiness_engine import WorkloadAssessment
from src.infrastructure.exceptions import InfrastructureError

logger = logging.getLogger("infrastructure.llm_adapter")

class GeminiCoachAdapter:
    """
    Patrón Adapter: Encapsula el nuevo SDK oficial (google-genai).
    Aísla la lógica cognitiva del resto de la aplicación y utiliza un cliente 
    instanciable para garantizar Thread-Safety en entornos asíncronos.
    """
    def __init__(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.critical("Fallo de infraestructura: GEMINI_API_KEY no configurada.")
            raise ValueError("GEMINI_API_KEY requerida en el archivo .env")
        
        # Versionado Estricto: Forzamos el uso de la API 'v1' estable.
        # Esto previene errores 404 causados por la inestabilidad de los entornos 'v1beta'.
        self._client = genai.Client(
            api_key=api_key,
            http_options={'api_version': 'v1'}
        )
        self._model_id = 'gemini-1.5-flash'

    async def generate_personalized_plan(
        self, 
        assessment: WorkloadAssessment, 
        recent_sessions: List[Activity]
    ) -> str:
        """
        Orquesta la generación de un análisis fisiológico basado en métricas duras.
        """
        # Estructuración de datos crudos para inyectar contexto duro al LLM (Prompt Engineering)
        session_data = "\n".join([
            f"- Fecha: {act.timestamp.strftime('%Y-%m-%d')} | "
            f"Distancia: {round(act.distance_meters / 1000, 2)} km | "
            f"HR Promedio: {act.avg_heart_rate or 'N/A'} bpm"
            for act in recent_sessions[:5]
        ])

        prompt = (
            "Actúa como un entrenador de atletismo de élite y especialista en recuperación fisiológica. "
            "Tu objetivo es analizar las siguientes métricas de un corredor y redactar un reporte breve y directo "
            "dirigido al atleta. Debes utilizar un tono motivador pero profesional.\n\n"
            f"MÉTRICA ACWR (Riesgo de Lesión): {assessment.acwr}\n"
            f"CATEGORÍA DE RIESGO: {assessment.risk_category}\n"
            f"DIAGNÓSTICO BASE DEL ALGORITMO: {assessment.actionable_insight}\n\n"
            f"ÚLTIMAS SESIONES REGISTRADAS:\n{session_data}\n\n"
            "Por favor, devuelve estrictamente el siguiente formato sin introducciones extra:\n"
            "📋 ANÁLISIS TÉCNICO: [Tu análisis de cómo se relacionan sus ritmos cardíacos con la carga]\n"
            "🛌 PLAN DE RECUPERACIÓN: [Qué debe hacer hoy]\n"
            "🏃 PRÓXIMO PASO: [Sugerencia para su próximo entrenamiento]"
        )

        try:
            logger.info("Enviando telemetría al motor cognitivo Gemini (google-genai SDK)...")
            
            # type: ignore aplicado exclusivamente a la llamada externa para silenciar
            # la inferencia parcialmente desconocida del objeto GenerateContentResponse
            response = await self._client.aio.models.generate_content( # type: ignore
                model=self._model_id,
                contents=prompt
            )
            
            if not response.text:
                raise ValueError("El modelo retornó una respuesta vacía.")
                
            return str(response.text)
            
        except APIError as e:
            logger.error("Error en la API de Gemini (Código %s): %s", e.code, e.message)
            raise InfrastructureError("El motor de IA rechazó la petición o está fuera de servicio.") from e
        except Exception as e:
            logger.error("Fallo crítico de red o error interno al consumir Gemini: %s", str(e))
            raise InfrastructureError("Error de comunicación con la capa cognitiva.") from e