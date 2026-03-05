from django.http import JsonResponse
from django.utils import timezone
from bson import ObjectId
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

# Import DB collections
from .common import users_collection

@csrf_exempt
@require_http_methods(["GET"])
def check_user_keys(request):
    """Check if user has existing encryption keys in users collection"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'User ID not found'}, status=400)
        
        print(f"🔐 CHECK_KEYS - User: {user_id}")
        
        # Check if user has keys in users collection
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        # Check if encryption keys exist
        encryption_keys = user.get('encryption_keys')
        has_keys = encryption_keys is not None and \
                  'encrypted_private_key' in encryption_keys and \
                  'public_key' in encryption_keys
        
        print(f"🔐 KEYS STATUS - User {user_id}: {'Has keys' if has_keys else 'No keys'}")
        
        response_data = {
            'has_keys': has_keys,
            'user_id': user_id
        }
        
        if has_keys:
            response_data['keys'] = {
                'encrypted_private_key': encryption_keys['encrypted_private_key'],
                'public_key': encryption_keys['public_key'],
                'iv': encryption_keys['iv'],
                'salt': encryption_keys['salt'],
                'iterations': encryption_keys['iterations']
            }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error checking user keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_user_keys(request):
    """Get user's encrypted keys from users collection"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'User ID not found'}, status=400)
        
        print(f"🔐 GET_KEYS - User: {user_id}")
        
        # Get user from database
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        if 'encryption_keys' not in user or not user['encryption_keys']:
            print(f"❌ No encryption keys found for user: {user_id}")
            return JsonResponse({'error': 'No encryption keys found'}, status=404)
        
        encryption_keys = user['encryption_keys']
        
        response_data = {
            'encrypted_private_key': encryption_keys['encrypted_private_key'],
            'public_key': encryption_keys['public_key'],
            'iv': encryption_keys['iv'],
            'salt': encryption_keys['salt'],
            'iterations': encryption_keys['iterations'],
            'user_id': user_id,
            'created_at': encryption_keys.get('created_at', timezone.now()).isoformat()
        }
        
        print(f"✅ Successfully retrieved keys for user: {user_id}")
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error getting user keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def store_user_keys(request):
    """Store user's encrypted keys in users collection"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'User ID not found'}, status=400)
        
        data = json.loads(request.body)
        
        required_fields = ['encrypted_private_key', 'iv', 'salt', 'iterations', 'public_key']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Missing required field: {field}'}, status=400)
        
        print(f"🔐 STORE_KEYS - User: {user_id}")
        
        # Prepare encryption keys data
        encryption_data = {
            'encrypted_private_key': data['encrypted_private_key'],
            'public_key': data['public_key'],
            'iv': data['iv'],
            'salt': data['salt'],
            'iterations': data['iterations'],
            'created_at': timezone.now(),
            'updated_at': timezone.now()
        }
        
        # Update user document with encryption keys
        result = users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$set': {
                    'encryption_keys': encryption_data,
                    'encryption_enabled': True,
                    'encryption_setup_at': timezone.now()
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"✅ Successfully stored encryption keys for user: {user_id}")
            return JsonResponse({
                'success': True,
                'message': 'Encryption keys stored successfully',
                'user_id': user_id
            })
        else:
            print(f"❌ Failed to store keys for user: {user_id}")
            return JsonResponse({'error': 'Failed to store encryption keys'}, status=500)
        
    except Exception as e:
        print(f"❌ Error storing user keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_contact_public_key(request):
    """Get a contact's public key for encryption"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        contact_id = request.GET.get('user_id')
        if not contact_id:
            return JsonResponse({'error': 'Contact ID required'}, status=400)
        
        print(f"🔐 GET_PUBLIC_KEY - Contact: {contact_id}")
        
        # Get contact from database
        contact = users_collection.find_one({'_id': ObjectId(contact_id)})
        
        if not contact:
            return JsonResponse({'error': 'Contact not found'}, status=404)
        
        if 'encryption_keys' not in contact or not contact['encryption_keys']:
            return JsonResponse({'error': 'Contact does not have encryption setup'}, status=404)
        
        public_key = contact['encryption_keys']['public_key']
        
        return JsonResponse({
            'public_key': public_key,
            'user_id': contact_id,
            'user_name': contact.get('full_name', 'User')
        })
        
    except Exception as e:
        print(f"❌ Error getting contact public key: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def reset_encryption_keys(request):
    """Reset user's encryption keys (for testing or re-setup)"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        
        print(f"🔐 RESET_KEYS - User: {user_id}")
        
        # Remove encryption keys from user document
        result = users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$unset': {
                    'encryption_keys': "",
                    'encryption_enabled': "",
                    'encryption_setup_at': ""
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"✅ Successfully reset encryption keys for user: {user_id}")
            return JsonResponse({
                'success': True,
                'message': 'Encryption keys reset successfully',
                'user_id': user_id
            })
        else:
            print(f"❌ No keys to reset for user: {user_id}")
            return JsonResponse({'error': 'No encryption keys found to reset'}, status=404)
        
    except Exception as e:
        print(f"❌ Error resetting encryption keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_encryption_status(request):
    """Get comprehensive encryption status for the user"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        has_keys = 'encryption_keys' in user and user['encryption_keys'] is not None
        encryption_enabled = user.get('encryption_enabled', False)
        setup_at = user.get('encryption_setup_at')
        
        status_data = {
            'has_keys': has_keys,
            'encryption_enabled': encryption_enabled,
            'user_id': user_id,
            'setup_completed': has_keys and encryption_enabled
        }
        
        if setup_at:
            status_data['setup_at'] = setup_at.isoformat()
        
        if has_keys:
            keys = user['encryption_keys']
            status_data['keys_created'] = keys.get('created_at', timezone.now()).isoformat()
            status_data['keys_updated'] = keys.get('updated_at', timezone.now()).isoformat()
        
        return JsonResponse(status_data)
        
    except Exception as e:
        print(f"❌ Error getting encryption status: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)
