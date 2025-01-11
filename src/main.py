from fastapi import FastAPI, HTTPException, Depends, Request
from src.models import User, UserUpdate, UserCreate, HealthResponse, HealthComponent, HealthStatus
from src.auth_handler import verify_jwt_token, get_supabase_client
from dotenv import load_dotenv
import os
import requests
import pybreaker
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError
from src.cpuhealth import check_cpu_health
from src.diskhealth import check_disk_health
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Summary
from time import time

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_GRAPHQL_URL = f"{SUPABASE_URL}/graphql/v1"
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
USER_MANAGING_SERVER_PORT = os.getenv("USER_MANAGING_SERVER_PORT", "8080")
USER_MANAGING_SERVER_MODE = os.getenv("USER_MANAGING_SERVER_MODE", "development")
USER_MANAGING_PREFIX = f"/user-managing" if USER_MANAGING_SERVER_MODE == "release" else ""
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080")

app = FastAPI(
    title="User Management API",
    description="API to manage user data in Supabase",
    version="1.0.0",
    openapi_url=f"{USER_MANAGING_PREFIX}/openapi.json",
    docs_url=f"{USER_MANAGING_PREFIX}/docs",
    redoc_url=f"{USER_MANAGING_PREFIX}/redoc",
)

origins = [
    FRONTEND_URL,
    BACKEND_URL,
    "http://localhost",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Circuit Breaker Configuration
breaker = pybreaker.CircuitBreaker(
    fail_max=3,  
    reset_timeout=30  
)

# Retry Configuration
def is_transient_error(exception):
    """Define what qualifies as a transient error."""
    return isinstance(exception, requests.exceptions.RequestException)

retry_strategy = retry(
    stop=stop_after_attempt(3),  # Retry up to 3 times
    wait=wait_exponential(multiplier=1, min=2, max=6),  # Exponential backoff: 2s, 4s, 6s
    retry=retry_if_exception_type(requests.exceptions.RequestException)  # Retry only on network-related errors
)

# Initialize Prometheus instrumentator
Instrumentator().instrument(app).expose(app, endpoint=f"{USER_MANAGING_PREFIX}/metrics")

# Additional custom metrics
REQUEST_COUNT = Counter('request_count', 'Total number of requests', ['method', 'endpoint', 'status_code'])
REQUEST_LATENCY = Summary('request_latency_seconds', 'Latency of requests in seconds')

@app.middleware("http")
async def add_prometheus_metrics(request: Request, call_next):
    start_time = time()
    response = await call_next(request)
    process_time = time() - start_time

    # Record custom metrics
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code
    ).inc()

    REQUEST_LATENCY.observe(process_time)

    return response



# Helper function with Retry + Circuit Breaker for fetching user data
@retry_strategy
@breaker
def fetch_user_from_supabase(user_id: str):

    # If not a valid UUID regex, raise an HTTP 400 error
    if not re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", user_id):
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    graphql_query = """
        query GetUserById($id: UUID!){ 
            users_dataCollection(filter: { id: { eq: $id } }){
                edges {
                    node {
                        first_name last_name id email created_at latitude longitude location
                    } 
                } 
            } 
        }
    """
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "apikey": SUPABASE_KEY,
    }

    payload = {"query": graphql_query, "variables": {"id": user_id}}
    print(SUPABASE_GRAPHQL_URL)
    response = requests.post(SUPABASE_GRAPHQL_URL, json=payload, headers=headers)
    
    if response.status_code != 200:
        raise requests.exceptions.RequestException("Failed to fetch data from Supabase")

    return response.json()


# Get user by ID
@app.get(f"{USER_MANAGING_PREFIX}"+"/users/{user_id}")
async def get_user(user_id: str):
    try:
        data = fetch_user_from_supabase(user_id)

        if not data["data"]["users_dataCollection"]["edges"]:
            raise HTTPException(
                status_code=404, detail=f"No user found with ID {user_id}."
            )
        
        user = data["data"]["users_dataCollection"]["edges"][0]["node"]
        return user
    
    except RetryError as retry_error:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable after multiple retry attempts. Please try again later."
        )

    except pybreaker.CircuitBreakerError:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable due to repeated failures."
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    


# Helper function with Retry + Circuit Breaker for updating user data
@retry_strategy
@breaker
def update_user_in_supabase(user_id: str, user_data: dict):

    # If not a valid UUID regex, raise an HTTP 400 error
    if not re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", user_id):
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    
    graphql_query = """
        mutation UpdateUser($id: UUID!, $set: users_dataUpdateInput!) {
            updateusers_dataCollection(
                filter: { id: { eq: $id } }
                set: $set
                atMost: 1
            ) {
                records{
                    first_name
                    last_name
                    location
                    longitude
                    latitude
                }
            }
        }
    """
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "apikey": SUPABASE_KEY,
    }

    payload = {
        "query": graphql_query,
        "variables": {
            "id": user_id,
            "set": user_data,
        },
    }

    response = requests.post(SUPABASE_GRAPHQL_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise requests.exceptions.RequestException("Failed to update user in Supabase")

    return response.json()


# Edit user by ID
@app.put(f"{USER_MANAGING_PREFIX}"+"/users/{user_id}")
async def edit_user(user_id: str, user: UserUpdate):
    try:
        user_data = user.model_dump(exclude_unset=True)
        data = update_user_in_supabase(user_id, user_data)
        return data
    
    except RetryError as retry_error:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable after multiple retry attempts. Please try again later."
        )

    except pybreaker.CircuitBreakerError:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable due to repeated failures."
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

# Helper function with Retry + Circuit Breaker for inserting user data
@retry_strategy
@breaker
def insert_user_in_supabase(user_data: dict):
    # Validate UUID format for user ID
    if not re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", user_data.get("id", "")):
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    graphql_query = """
        mutation InsertUser($id: UUID!, $email: String!, $first_name: String!, $last_name: String!, $location: String!, $latitude: Float!, $longitude: Float!) {
            insertIntousers_dataCollection(objects: {
                id: $id,
                email: $email,
                first_name: $first_name,
                last_name: $last_name,
                location: $location,
                latitude: $latitude,
                longitude: $longitude
            }) {
                records {
                    id
                    email
                    first_name
                    last_name
                    location
                    latitude
                    longitude
                }
            }
        }
    """
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "apikey": SUPABASE_KEY,
    }

    payload = {
        "query": graphql_query,
        "variables": user_data,
    }

    # print(payload)
    response = requests.post(SUPABASE_GRAPHQL_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise requests.exceptions.RequestException("Failed to insert user in Supabase")

    return response.json()


# Create user endpoint
@app.post(f"{USER_MANAGING_PREFIX}/users")
async def create_user(user: UserCreate):
    try:
        user_data = user.model_dump()

        data = insert_user_in_supabase(user_data)
        return data['data']['insertIntousers_dataCollection']['records'][0]
    
    except RetryError as retry_error:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable after multiple retry attempts. Please try again later."
        )

    except pybreaker.CircuitBreakerError:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable due to repeated failures."
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

# Health check endpoint
@app.get(f"{USER_MANAGING_PREFIX}/health/general")
async def health_check():
    return {"status": "ok"}

# SUpabase health check endpoint
@app.get(f"{USER_MANAGING_PREFIX}/health/database")
async def supabase_health_check():
    try:
        # > curl https://<project-ref>.supabase.co/customer/v1/privileged/metrics --user 'service_role:<service-role-jwt>'
        response = requests.get(f"{SUPABASE_URL}/customer/v1/privileged/metrics", auth=("service_role", SUPABASE_SERVICE_ROLE_KEY))
                
        if response.status_code != 200:
            raise HTTPException(
                status_code=503,
                detail="Supabase service is unavailable."
            )
        return {"status": "ok"}
    
    except requests.exceptions.RequestException:
        # Print the original exception
        
        raise HTTPException(
            status_code=503,
            detail="Supabase service is unavailable."
        )
    
@app.get(f"{USER_MANAGING_PREFIX}/health/cpu", response_model=HealthResponse)
async def cpu_health_check():
    cpu_health = check_cpu_health()
    return HealthResponse(status=cpu_health.status, components={"cpu": cpu_health})

@app.get(f"{USER_MANAGING_PREFIX}/health/disk", response_model=HealthResponse)
async def disk_health_check():
    """
    Check the health of the disk.
    """
    disk_health = check_disk_health()
    return HealthResponse(
        status=disk_health.status,
        components={"disk": disk_health}
    )
    
@app.get(f"{USER_MANAGING_PREFIX}/health/readiness", response_model=HealthResponse)
async def readiness_check():
    """
    Check the readiness of the service.
    """
    try:
        # Perform all health checks
        cpu_health = check_cpu_health()
        disk_health = check_disk_health()
        
        # Call supabase health logic directly, avoiding the async route call
        response = requests.get(
            f"{SUPABASE_URL}/customer/v1/privileged/metrics",
            auth=("service_role", SUPABASE_SERVICE_ROLE_KEY)
        )
        
        if response.status_code != 200:
            database_health = HealthComponent(status=HealthStatus.DOWN, details="Supabase service is unavailable.")
        else:
            database_health = HealthComponent(status=HealthStatus.UP, details="Supabase service is operational.")
        
        return HealthResponse(
            status=HealthStatus.UP,
            components={
                "cpu": cpu_health,
                "database": database_health,
                "disk": disk_health
            }
        )
    
    except Exception as e:
        return HealthResponse(
            status=HealthStatus.DOWN,
            components={
                "error": HealthComponent(status=HealthStatus.DOWN, details=str(e))
            }
        )
        

