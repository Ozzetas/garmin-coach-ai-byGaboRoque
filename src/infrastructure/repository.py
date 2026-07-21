import logging
from typing import List, Dict, Any, cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy import CursorResult

from src.domain.activity import Activity
from src.infrastructure.models import ActivityModel
from src.infrastructure.exceptions import InfrastructureError

# Logging estructurado para auditoría de base de datos
logger = logging.getLogger("infrastructure.repository")

class ActivityRepository:
    """
    Patrón Repository: Aísla la capa de acceso a datos de la lógica de aplicación.
    Garantiza el principio de Responsabilidad Única (SOLID).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_upsert_activities(self, activities: List[Activity]) -> int:
        """
        Inserta actividades masivamente mediante un comando optimizado.
        Si el activity_id ya existe, ignora la inserción protegiendo la integridad transaccional.
        """
        if not activities:
            return 0

        try:
            # Tipado explícito: Bloquea la degradación a 'Unknown' en el linter
            values: List[Dict[str, Any]] = [
                {
                    "activity_id": act.activity_id,
                    "timestamp": act.timestamp,
                    "distance_meters": act.distance_meters,
                    "duration_seconds": act.duration_seconds,
                    "avg_heart_rate": act.avg_heart_rate
                }
                for act in activities
            ]

            # Sentencia nativa de SQLite: INSERT OR IGNORE
            stmt = insert(ActivityModel).values(values)
            stmt = stmt.on_conflict_do_nothing(index_elements=['activity_id'])
            
            # Ejecución atómica y casteo estricto para exponer el atributo 'rowcount'
            raw_result = await self._session.execute(stmt)
            result = cast(CursorResult[Any], raw_result)
            await self._session.commit()
            
            # Tipado estricto en la asignación final
            inserted_rows: int = int(result.rowcount)
            logger.info("Sincronización DB exitosa: %d nuevas actividades persistidas.", inserted_rows)
            
            return inserted_rows

        except Exception as e:
            # Rollback explícito ante catástrofes (falla de disco, memoria, etc.)
            await self._session.rollback()
            logger.error("Fallo crítico de transacción al persistir actividades: %s", str(e))
            raise InfrastructureError("Fallo de persistencia en disco al guardar datos.") from e