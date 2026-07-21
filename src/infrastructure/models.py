from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base

class ActivityModel(Base):
    """
    Mapeo Objeto-Relacional (ORM) con tipado estricto para la tabla de actividades.
    """
    __tablename__ = "activities"

    # Uso de Mapped[T] elimina la ambigüedad de tipos para Pylance y Mypy
    activity_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Optional[int] documenta explícitamente que el sensor HR pudo haber fallado
    avg_heart_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)