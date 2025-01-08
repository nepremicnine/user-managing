import psutil
from src.models import HealthComponent

# CPU Health Check
def check_cpu_health() -> HealthComponent:
    try:
        # Get CPU usage percentage
        cpu_usage = psutil.cpu_percent(interval=1)  # 1-second average
        cpu_count = psutil.cpu_count(logical=True)
        load_avg = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0, 0, 0)
        
        # Define thresholds
        MAX_CPU_USAGE = 85  # Example threshold for high CPU usage
        
        if cpu_usage > MAX_CPU_USAGE:
            return HealthComponent(
                status="DOWN",
                details=f"High CPU usage detected: {cpu_usage}%. Load average (1m, 5m, 15m): {load_avg}"
            )
        
        return HealthComponent(
            status="UP",
            details=f"CPU usage at {cpu_usage}%. Load average (1m, 5m, 15m): {load_avg}. Logical CPUs: {cpu_count}"
        )
    
    except Exception as e:
        return HealthComponent(status="DOWN", details=f"Failed to check CPU health: {str(e)}")
