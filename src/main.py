from fastapi import FastAPI, HTTPException, Depends
from models import User, UserUpdate
from auth_handler import verify_jwt_token, get_supabase_client
from dotenv import load_dotenv
import os
import requests
import pybreaker
import re


# Load environment variables from .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_GRAPHQL_URL = f"{SUPABASE_URL}/graphql/v1"
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

app = FastAPI()

# Circuit Breaker 
breaker = pybreaker.CircuitBreaker(
    fail_max=3,  
    reset_timeout=30  #
)

# Helper function with Circuit Breaker for fetching user data
@breaker
def fetch_user_from_supabase(user_id: str):

    #If not a valid UUID regex, raise an HTTP 400 error
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
    response = requests.post(SUPABASE_GRAPHQL_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

# Get user by ID
@app.get("/users/{user_id}")
async def get_user(user_id: str):
    try:
        data = fetch_user_from_supabase(user_id)

        # Check if user exists
        if not data["data"]["users_dataCollection"]["edges"]:
            raise HTTPException(
                status_code=404, detail=f"No user found with ID {user_id}."
            )
        
        user = data["data"]["users_dataCollection"]["edges"][0]["node"]
        return user

    except pybreaker.CircuitBreakerError:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable due to repeated failures."
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Helper function with Circuit Breaker for updating user data
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
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()


# Edit user by ID
@app.put("/users/{user_id}")
async def edit_user(user_id: str, user: UserUpdate):
    try:
        user_data = user.dict(exclude_unset=True)
        data = update_user_in_supabase(user_id, user_data)
        return data

    except pybreaker.CircuitBreakerError:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable due to repeated failures."
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

     
