import logging
import os
from typing import List

# Se suprime la advertencia de importación privada/desconocida
# dado que el SDK de Google carece de tipado estricto exportado (PEP 561).
import google.generativeai as genai  # type: ignore

from src.domain.activity import Activity
from src.domain.readiness_engine import WorkloadAssessment
from src.infrastructure.exceptions import InfrastructureError

logger = logging.getLogger("infrastructure.llm_adapter")

class GeminiCoachAdapter:
    """
    Patrón Adapter: Encapsula el SDK de Google Gemini.
    Aísla la lógica cognitiva del resto de la aplicación, permitiendo
    intercambiar el modelo subyacente sin alterar el dominio.
    """
    def __init__(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.critical("Fallo de infraestructura: GEMINI_API_KEY no configurada.")
            raise ValueError("GEMINI_API_KEY requerida en el archivo .env")
        
        # type: ignore silencia la falta de firmas explícitas en el SDK
        genai.configure(api_key=api_key) # type: ignore
        
        # type: ignore requerido porque GenerativeModel se considera importación privada en strict mode
        self._model = genai.GenerativeModel('gemini-1.5-flash') # type: ignore

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
            logger.info("Enviando telemetría al motor cognitivo Gemini...")
            
            # type: ignore suprime la inferencia parcialmente desconocida del objeto Coroutine retornado
            response = await self._model.generate_content_async(prompt) # type: ignore
            
            if not response.text:
                raise ValueError("El modelo retornó una respuesta vacía.")
                
            return str(response.text)
            
        except Exception as e:
            logger.error("Fallo de red al consumir la API de Gemini: %s", str(e))
            raise InfrastructureError("El motor de IA está temporalmente fuera de servicio.") from e