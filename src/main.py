from fastapi import FastAPI, HTTPException, Depends
from models import User, UserUpdate
from auth_handler import verify_jwt_token, get_supabase_client
from dotenv import load_dotenv
import os
import requests


# Load environment variables from .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_GRAPHQL_URL = f"{SUPABASE_URL}/graphql/v1"
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

app = FastAPI()

# Get user by id
@app.get("/users/{user_id}")
async def get_user(user_id: str):
    try:
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

        data = response.json()
        user = data["data"]["users_dataCollection"]["edges"][0]["node"]

        if not user:
            raise HTTPException(
                status_code=404, detail=f"No user found with ID {user_id}."
            )

        return user

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Edit user by id
@app.put("/users/{user_id}")
async def edit_user(user_id: str, user: UserUpdate):
    try:
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
                "set": user.dict(exclude_unset=True),
            },
        }

        response = requests.post(SUPABASE_GRAPHQL_URL, json=payload, headers=headers)

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        data = response.json()
        return data
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    




     
