from dataclasses import dataclass
from datetime import date
from typing import Optional

@dataclass(frozen=True)
class DailyBiometrics:
    """
    Entidad de Dominio: Representa el estado fisiológico general del atleta 
    fuera de las ventanas de entrenamiento activo.
    """
    target_date: date
    total_steps: int
    resting_heart_rate: Optional[int]
    max_heart_rate: Optional[int]
    min_heart_rate: Optional[int]