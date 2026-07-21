class InfrastructureError(Exception):
    """Excepción base para la capa de infraestructura."""
    pass

class GarminAuthenticationError(InfrastructureError):
    """Lanzada cuando las credenciales o el token de sesión son inválidos."""
    pass

class GarminRateLimitError(InfrastructureError):
    """Lanzada cuando la IP ha sido bloqueada temporalmente por la API."""
    pass

class DataParsingError(InfrastructureError):
    """Lanzada cuando el JSON de respuesta muta o contiene datos corruptos."""
    pass