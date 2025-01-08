import psutil
from src.models import HealthComponent, HealthStatus

def check_disk_health():
    try:
        disk_usage = psutil.disk_usage('/')
        threshold = 90  # Define a threshold percentage for disk health

        if disk_usage.percent >= threshold:
            status = HealthStatus.DOWN
            detail = f"Disk usage is critical: {disk_usage.percent}% used."
        else:
            status = HealthStatus.UP
            detail = f"Disk usage is healthy: {disk_usage.percent}% used."

        return HealthComponent(
            status=status,
            details=detail
        )

    except Exception as e:
        return HealthComponent(
            status=HealthStatus.DOWN,
            details=f"Failed to check disk health: {str(e)}"
        )
