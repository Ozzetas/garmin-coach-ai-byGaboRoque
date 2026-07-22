import logging
from typing import List, Dict, Any, cast
from datetime import datetime
from src.domain.biometrics import DailyBiometrics
from datetime import date

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from src.domain.activity import Activity
from src.infrastructure.exceptions import (
    GarminAuthenticationError,
    GarminRateLimitError,
    InfrastructureError,
)

# Logging estructurado para trazabilidad
logger = logging.getLogger("infrastructure.garmin_adapter")

class GarminAdapter:
    """
    Actúa como Facade para la librería garminconnect.
    Aisla a nuestra lógica de negocio de los detalles de bajo nivel de la API externa.
    """

    def __init__(self, email: str, password: str) -> None:
        self._email: str = email
        self._password: str = password
        self._client: Garmin = Garmin(email, password)
        self._authenticate()

    def _authenticate(self) -> None:
        """Autentica la sesión. Falla rápidamente si hay problemas de red o credenciales."""
        try:
            self._client.login()
            logger.info("Autenticación con Garmin Connect exitosa.")
        except GarminConnectAuthenticationError as e:
            logger.error("Credenciales inválidas para Garmin Connect.")
            raise GarminAuthenticationError("Fallo de autenticación al iniciar sesión.") from e
        except GarminConnectConnectionError as e:
            logger.error("Error de conectividad TCP/IP o DNS al intentar alcanzar Garmin.")
            raise InfrastructureError("Servicio de Garmin inalcanzable.") from e

    def fetch_recent_activities(self, limit: int = 30) -> List[Activity]:
        """
        Extrae el histórico reciente limitando el volumen para evitar baneos de IP.
        """
        try:
            # Casteo estricto: Le afirmamos al Linter que el payload será una lista de diccionarios
            raw_activities = cast(List[Dict[str, Any]], self._client.get_activities(0, limit))
            return self._parse_to_domain(raw_activities)
        except GarminConnectTooManyRequestsError as e:
            logger.error("HTTP 429: Rate limit excedido en la API de Garmin.")
            raise GarminRateLimitError("Demasiadas peticiones. Bloqueo temporal activo.") from e
        except Exception as e:
            logger.error("Error no controlado en la ingesta de datos: %s", str(e))
            raise InfrastructureError("Error inesperado en la red.") from e

    def _parse_to_domain(self, raw_data: List[Dict[str, Any]]) -> List[Activity]:
        """
        Mapea el JSON crudo e inseguro de Garmin hacia nuestra entidad de Dominio inmutable.
        Realiza extracción defensiva para prevenir TypeErrors por valores nulos.
        """
        parsed_activities: List[Activity] = []
        
        for item in raw_data:
            try:
                # Extracción y validación de fecha
                raw_date = item.get("startTimeLocal")
                timestamp = datetime.strptime(str(raw_date), "%Y-%m-%d %H:%M:%S") if raw_date else datetime.now()

                # Extracción defensiva: Verificar nulidad antes de castear a float/int
                raw_distance = item.get("distance")
                distance_meters = float(raw_distance) if raw_distance is not None else 0.0

                raw_duration = item.get("duration")
                duration_seconds = float(raw_duration) if raw_duration is not None else 0.0

                raw_hr = item.get("averageHR")
                avg_hr = int(raw_hr) if raw_hr is not None else None

                activity = Activity(
                    activity_id=str(item.get("activityId")),
                    timestamp=timestamp,
                    distance_meters=distance_meters,
                    duration_seconds=duration_seconds,
                    avg_heart_rate=avg_hr
                )
                parsed_activities.append(activity)
                
            except (ValueError, TypeError) as e:
                # Si falla el casteo o Pydantic rechaza los datos por reglas de dominio, se ignora limpiamente
                logger.warning(
                    "Actividad ignorada (ID: %s) por violación de integridad: %s", 
                    item.get("activityId", "UNKNOWN"), str(e)
                )
                continue
                
        logger.info("Ingesta finalizada: %d actividades parseadas con éxito.", len(parsed_activities))
        return parsed_activities
    
    def fetch_daily_biometrics(self, target_date: date) -> DailyBiometrics:
        """
        Extrae la telemetría diaria general del usuario (pasos, pulso basal).
        """
        try:
            # garminconnect requiere la fecha en formato ISO (YYYY-MM-DD)
            stats = self._client.get_stats(target_date.isoformat())
            
            return DailyBiometrics(
                target_date=target_date,
                total_steps=stats.get("totalSteps", 0),
                resting_heart_rate=stats.get("restingHeartRate"),
                max_heart_rate=stats.get("maxHeartRate"),
                min_heart_rate=stats.get("minHeartRate")
            )
        except Exception as e:
            # Manejo explícito sin derribar la aplicación si Garmin falla un día particular
            logger.error("Fallo al extraer métricas diarias de Garmin: %s", str(e))
            raise InfrastructureError("Error de extracción de biometría diaria desde Garmin Connect.") from e