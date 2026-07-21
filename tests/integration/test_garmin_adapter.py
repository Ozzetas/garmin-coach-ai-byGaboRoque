import pytest
from pytest_mock import MockerFixture
from datetime import datetime
from typing import List, Dict, Any

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from src.infrastructure.garmin_adapter import GarminAdapter
from src.infrastructure.exceptions import (
    GarminAuthenticationError,
    GarminRateLimitError,
)

DUMMY_EMAIL = "test@example.com"
DUMMY_PASSWORD = "secure_password123"


def test_adapter_successful_authentication_and_fetch(mocker: MockerFixture) -> None:
    """
    Verifica que el adaptador procese correctamente un payload JSON válido
    y lo transforme en la entidad de dominio Activity con tipado estricto.
    """
    mock_login = mocker.patch("garminconnect.Garmin.login", return_value=True)
    
    # Tipado explícito: Elimina la inferencia "Unknown" de Pylance
    mock_payload: List[Dict[str, Any]] = [{
        "activityId": 123456789,
        "startTimeLocal": "2023-10-15 08:30:00",
        "distance": 5000.5,
        "duration": 1500.0,
        "averageHR": 155
    }]
    
    mock_get_activities = mocker.patch("garminconnect.Garmin.get_activities", return_value=mock_payload)

    adapter = GarminAdapter(email=DUMMY_EMAIL, password=DUMMY_PASSWORD)
    activities = adapter.fetch_recent_activities(limit=1)

    mock_login.assert_called_once()
    mock_get_activities.assert_called_once_with(0, 1)
    
    assert len(activities) == 1
    assert activities[0].activity_id == "123456789"
    assert activities[0].distance_meters == 5000.5
    assert activities[0].avg_heart_rate == 155
    assert isinstance(activities[0].timestamp, datetime)


def test_adapter_authentication_failure(mocker: MockerFixture) -> None:
    """
    Garantiza que una credencial inválida levante nuestra excepción
    personalizada de dominio y no un error genérico de terceros.
    """
    mocker.patch(
        "garminconnect.Garmin.login", 
        side_effect=GarminConnectAuthenticationError("Invalid credentials")
    )

    with pytest.raises(GarminAuthenticationError) as exc_info:
        GarminAdapter(email=DUMMY_EMAIL, password=DUMMY_PASSWORD)
    
    assert "Fallo de autenticación" in str(exc_info.value)


def test_adapter_rate_limit_handling(mocker: MockerFixture) -> None:
    """
    Valida que el bloqueo temporal de IP por parte de Garmin
    sea capturado y transformado en un error de infraestructura manejable.
    """
    mocker.patch("garminconnect.Garmin.login", return_value=True)
    mocker.patch(
        "garminconnect.Garmin.get_activities", 
        side_effect=GarminConnectTooManyRequestsError("HTTP 429")
    )

    adapter = GarminAdapter(email=DUMMY_EMAIL, password=DUMMY_PASSWORD)

    with pytest.raises(GarminRateLimitError) as exc_info:
        adapter.fetch_recent_activities()

    assert "Bloqueo temporal activo" in str(exc_info.value)