import os
from dotenv import load_dotenv 
from pymongo import MongoClient
import motor.motor_asyncio
import hashlib
import base64
from io import BytesIO
from PIL import Image

load_dotenv()  # Load environment variables from .env

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")

# --- Sync Setup (for regular Django views) ---
client = MongoClient(MONGO_URI)
db = client['chat_new']

users_collection = db['users']
messages_collection = db['messages_websocket']
media_collection = db['media']
groups_collection = db['groups']
group_messages_collection = db['messages_group']
group_seeds_collection = db['group_encrypted_seeds'] 

# --- Async Setup (for WebSocket consumers) ---
async_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
async_db = async_client['chat_new']

async_users_collection = async_db['users']
async_messages_collection = async_db['messages_websocket']
async_media_collection = async_db['media']
async_groups_collection = async_db['groups']
async_group_messages_collection = async_db['messages_group']
async_group_seeds_collection = async_db['group_encrypted_seeds']

# Password hashing
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def compress_image(image_file, max_size=(300, 300), quality=70):
    """
    Compress and resize an image from a file-like object, return base64 string.
    """
    try:
        img = Image.open(image_file)
        
        # Convert to RGB if necessary (e.g. for PNG with alpha)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        # Resize using thumbnail (preserves aspect ratio)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Save to buffer
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        
        # Encode to base64
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"Error compressing image: {str(e)}")
        # If compression fails, try raw base64 as fallback
        try:
            image_file.seek(0)
            return base64.b64encode(image_file.read()).decode('utf-8')
        except:
            return ""
