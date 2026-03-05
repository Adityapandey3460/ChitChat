import os
import uuid
from datetime import datetime
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from .common import messages_collection, media_collection
from bson import ObjectId

@csrf_exempt
@require_POST
def upload_media(request):
    """Upload encrypted media file and return its ID"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    if 'file' not in request.FILES:
        return JsonResponse({"error": "No file uploaded"}, status=400)
    
    file_obj = request.FILES['file']
    
    # Store encrypted media directly in MongoDB
    media_id = str(uuid.uuid4())
    try:
        # Read the uploaded file into memory (encrypted binary)
        file_bytes = b''.join(chunk for chunk in file_obj.chunks())
        
        # Insert into the media collection as binary data
        media_collection.insert_one({
            "_id": media_id,
            "data": file_bytes,
            "content_type": file_obj.content_type or "application/octet-stream",
            "uploaded_at": datetime.utcnow()
        })
        
        return JsonResponse({
            "success": True,
            "media_id": media_id
        })
    except Exception as e:
        print(f"Error saving media to MongoDB: {e}")
        return JsonResponse({"error": "Failed to save media"}, status=500)

def download_media(request, media_id):
    """Download encrypted media file by ID"""
    if 'user_id' not in request.session:
        return HttpResponse("Unauthorized", status=401)
    
    # Sanitize media_id to prevent path traversal
    # UUIDs only contain alphanumeric and hyphens
    if not all(c.isalnum() or c == '-' for c in media_id):
        return HttpResponse("Invalid media ID", status=400)
    
    # Retrieve the encrypted media from MongoDB
    try:
        doc = media_collection.find_one({"_id": media_id})
        
        if doc:
            data = doc.get("data")
            content_type = doc.get("content_type", "application/octet-stream")
            return HttpResponse(data, content_type=content_type)
        else:
            return HttpResponse("Media not found", status=404)
    except Exception as e:
        print(f"Error fetching media from MongoDB: {e}")
        return HttpResponse("Server error", status=500)
