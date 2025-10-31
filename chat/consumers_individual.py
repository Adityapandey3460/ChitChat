# consumers_individual.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from pymongo import MongoClient
from bson import ObjectId
from django.utils.timezone import now
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client['chat_new']

users_collection = db['users']
messages_collection = db['messages_websocket']

class IndividualChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get string IDs from frontend
        self.user_id = self.scope['session'].get('user_id')  # String
        if not self.user_id:
            await self.close()
            return

        # Convert to ObjectId for database operations
        self.user_object_id = ObjectId(self.user_id)

        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'

        # Get user data with encryption status
        user_data = await self.get_user_encryption_status()
        if not user_data:
            await self.close()
            return

        self.user_name = user_data['full_name']
        self.user_has_encryption = user_data.get('has_encryption', False)

        # Mark user as online using ObjectId
        users_collection.update_one(
            {"_id": self.user_object_id},
            {"$set": {"status": "online", "last_seen": now()}}
        )

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        # Send connection confirmation with encryption status
        await self.send(text_data=json.dumps({
            "type": "connection_established",
            "user_id": self.user_id,  # Send string to frontend
            "has_encryption": self.user_has_encryption,
            "timestamp": now().isoformat()
        }))

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        except Exception:
            pass

        # Mark user as offline using ObjectId
        users_collection.update_one(
            {"_id": self.user_object_id},
            {"$set": {"status": "offline", "last_seen": now()}}
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get("type")

            if message_type == "chat_message":
                await self.chat_message_handler(data)
            elif message_type == "edit_message":
                await self.edit_message_handler(data)
            elif message_type == "delete_message":
                await self.delete_message_handler(data)
            elif message_type == "clear_chat":
                await self.clear_chat_handler(data)
            elif message_type == "read_receipt":
                await self.read_receipt_handler(data)
            elif message_type == "typing":
                await self.typing_handler(data)
            elif message_type == "request_public_key":
                await self.request_public_key_handler(data)
            elif message_type == "share_public_key":
                await self.share_public_key_handler(data)
            elif message_type == "encryption_status":
                await self.encryption_status_handler(data)
            elif message_type == "key_exchange":
                await self.key_exchange_handler(data)
            else:
                print(f"Unknown message type: {message_type}")
        except Exception as e:
            print("Individual chat receive error:", e)

    async def get_user_encryption_status(self):
        """Get user data with encryption status"""
        try:
            user = users_collection.find_one({"_id": self.user_object_id})
            if not user:
                return None
            
            has_encryption = 'encryption_keys' in user and user['encryption_keys'] is not None
            
            return {
                'full_name': user.get('full_name', 'Unknown User'),
                'has_encryption': has_encryption
            }
        except Exception as e:
            print(f"Error getting user encryption status: {e}")
            return None

    async def chat_message_handler(self, data):
        """
        Stores individual message with encryption support, broadcasts to room
        """
        message_content = (data.get("message") or "").strip()
        encrypted_content = data.get("encrypted_content")  # Encrypted message
        iv = data.get("iv")  # Initialization vector
        receiver_id = data.get("receiver_id")  # String from frontend
        temp_id = data.get("temp_id")

        # Require either plaintext or encrypted content
        if (not message_content and not encrypted_content) or not receiver_id:
            return

        # Convert receiver_id to ObjectId for database
        receiver_object_id = ObjectId(receiver_id)

        timestamp = now()
        room = "_".join(sorted([self.user_id, receiver_id]))

        # Check if receiver has encryption using ObjectId
        receiver = users_collection.find_one({"_id": receiver_object_id})
        receiver_has_encryption = receiver and 'encryption_keys' in receiver and receiver['encryption_keys'] is not None
        
        # Determine if this message is encrypted
        is_encrypted = encrypted_content is not None and receiver_has_encryption

        # Create message document with ObjectIds
        message_doc = {
            "room": room,
            "sender_id": self.user_object_id,  # ObjectId
            "receiver_id": receiver_object_id,  # ObjectId
            "message": message_content,  # Plaintext (for fallback/search)
            "encrypted_content": encrypted_content,  # Encrypted content
            "iv": iv,  # IV for decryption
            "timestamp": timestamp,
            "read": False,
            "edited": False,
            "deleted": False,
            "message_type": "individual",
            "is_encrypted": is_encrypted,
            "encryption_enabled": receiver_has_encryption
        }
        
        result = messages_collection.insert_one(message_doc)
        message_id = str(result.inserted_id)

        # Prepare event for broadcasting (send strings to frontend)
        event = {
            "type": "individual_message",
            "message_id": message_id,
            "message": message_content,
            "encrypted_content": encrypted_content,
            "iv": iv,
            "sender_id": self.user_id,  # String for frontend
            "receiver_id": receiver_id,  # String for frontend
            "timestamp": timestamp.isoformat(),
            "read": False,
            "temp_id": temp_id,
            "message_type": "individual",
            "is_encrypted": is_encrypted,
            "encryption_enabled": receiver_has_encryption,
            "sender_has_encryption": self.user_has_encryption
        }

        await self.channel_layer.group_send(self.room_group_name, event)

    async def edit_message_handler(self, data):
        """Edit individual message with encryption support"""
        message_id = data.get("message_id")
        new_content = data.get("new_content", "").strip()
        encrypted_content = data.get("encrypted_content")
        iv = data.get("iv")
        receiver_id = data.get("receiver_id")
        
        if not message_id or (not new_content and not encrypted_content):
            return

        try:
            update_data = {
                "edited": True, 
                "edit_timestamp": now()
            }
            
            # Update both plaintext and encrypted content
            if new_content:
                update_data["message"] = new_content
            if encrypted_content:
                update_data["encrypted_content"] = encrypted_content
            if iv:
                update_data["iv"] = iv
            
            result = messages_collection.update_one(
                {
                    "_id": ObjectId(message_id), 
                    "sender_id": self.user_object_id  # ObjectId comparison
                },
                {"$set": update_data}
            )
            
            if result.modified_count == 0:
                print("Individual message not found or not authorized to edit")
                return
                
        except Exception as e:
            print(f"Error editing individual message: {e}")
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "individual_message_edited",
            "message_id": message_id,
            "new_content": new_content,
            "encrypted_content": encrypted_content,
            "iv": iv,
            "timestamp": now().isoformat(),
            "editor_id": self.user_id,  # String for frontend
            "is_encrypted": encrypted_content is not None
        })

    async def delete_message_handler(self, data):
        """Delete individual message"""
        message_id = data.get("message_id")
        receiver_id = data.get("receiver_id")
        
        if not message_id:
            return

        try:
            # Handle temp IDs
            if isinstance(message_id, str) and message_id.startswith('temp_'):
                return
                
            result = messages_collection.update_one(
                {
                    "_id": ObjectId(message_id), 
                    "sender_id": self.user_object_id  # ObjectId comparison
                },
                {"$set": {
                    "message": "This message was deleted", 
                    "encrypted_content": None,  # Clear encrypted content
                    "deleted": True,
                    "delete_timestamp": now()
                }}
            )
            
            if result.modified_count == 0:
                print(f"Individual message {message_id} not found or not authorized")
                return
                
        except Exception as e:
            print(f"Error deleting individual message: {e}")
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "individual_message_deleted",
            "message_id": message_id,
            "deleter_id": self.user_id,  # String for frontend
            "receiver_id": receiver_id  # String for frontend
        })
        
    async def clear_chat_handler(self, data):
        """Clear entire chat history"""
        receiver_id = data.get("receiver_id")  # String from frontend
        if not receiver_id:
            return
            
        room = "_".join(sorted([self.user_id, receiver_id]))

        try:
            # Delete all individual messages in this room
            result = messages_collection.delete_many({
                "room": room,
                "message_type": "individual"
            })
            print(f"Deleted {result.deleted_count} individual messages from room {room}")
        except Exception as e:
            print(f"Error clearing individual chat: {e}")
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "individual_chat_cleared",
            "room": room,
            "cleared_by": self.user_id,  # String for frontend
            "permanent_delete": True
        })

    async def read_receipt_handler(self, data):
        """Handle read receipts for individual messages"""
        message_ids = data.get("message_ids", [])
        receiver_id = data.get("receiver_id")
        
        if not message_ids:
            return

        # Process valid message IDs
        object_ids = []
        valid_message_ids = []
        
        for msg_id in message_ids:
            try:
                if isinstance(msg_id, str) and msg_id.startswith('temp_'):
                    continue
                object_ids.append(ObjectId(msg_id))
                valid_message_ids.append(msg_id)
            except Exception:
                continue

        if object_ids:
            result = messages_collection.update_many(
                {
                    "_id": {"$in": object_ids},
                    "receiver_id": self.user_object_id  # ObjectId comparison
                },
                {"$set": {"read": True, "read_timestamp": now()}}
            )
            print(f"Marked {result.modified_count} individual messages as read")

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "individual_read_receipt",
            "message_ids": valid_message_ids,
            "reader_id": self.user_id,  # String for frontend
            "receiver_id": receiver_id,  # String for frontend
            "timestamp": now().isoformat()
        })

    async def typing_handler(self, data):
        """Handle typing indicators"""
        receiver_id = data.get("receiver_id")  # String from frontend
        is_typing = bool(data.get("is_typing", False))
        
        if not receiver_id:
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "individual_typing_indicator",
            "sender_id": self.user_id,  # String for frontend
            "sender_name": self.user_name,
            "receiver_id": receiver_id,  # String for frontend
            "is_typing": is_typing
        })

    async def request_public_key_handler(self, data):
        """Handle requests for public key exchange"""
        try:
            contact_id = data.get("contact_id")  # String from frontend
            
            if not contact_id:
                return

            print(f"🔐 PUBLIC KEY REQUEST - From: {self.user_id}, To: {contact_id}")
            
            # Get contact's encryption status using ObjectId
            contact = users_collection.find_one({"_id": ObjectId(contact_id)})
            if not contact:
                return

            contact_has_encryption = 'encryption_keys' in contact and contact['encryption_keys'] is not None
            
            if contact_has_encryption:
                # Send public key request to contact
                await self.channel_layer.send(
                    f"user_{contact_id}",  # Send to contact's personal channel
                    {
                        "type": "public_key_request",
                        "requester_id": self.user_id,  # String
                        "requester_name": self.user_name,
                        "timestamp": now().isoformat()
                    }
                )

                # Notify requester that request was sent
                await self.send(text_data=json.dumps({
                    "type": "public_key_request_sent",
                    "contact_id": contact_id,  # String
                    "contact_name": contact.get('full_name', 'User'),
                    "timestamp": now().isoformat()
                }))
            else:
                # Contact doesn't have encryption
                await self.send(text_data=json.dumps({
                    "type": "public_key_request_failed",
                    "contact_id": contact_id,  # String
                    "reason": "Contact does not have encryption setup",
                    "timestamp": now().isoformat()
                }))

        except Exception as e:
            print(f"❌ Error in request_public_key_handler: {e}")

    async def share_public_key_handler(self, data):
        """Handle sharing public key with contacts"""
        try:
            contact_id = data.get("contact_id")  # String from frontend
            public_key = data.get("public_key")
            
            if not contact_id or not public_key:
                return

            print(f"🔐 SHARE PUBLIC KEY - From: {self.user_id}, To: {contact_id}")
            
            # Verify sender has encryption
            if not self.user_has_encryption:
                await self.send(text_data=json.dumps({
                    "type": "public_key_share_failed",
                    "reason": "You don't have encryption setup",
                    "timestamp": now().isoformat()
                }))
                return

            # Send public key to contact
            await self.channel_layer.send(
                f"user_{contact_id}",
                {
                    "type": "public_key_shared",
                    "sender_id": self.user_id,  # String
                    "sender_name": self.user_name,
                    "public_key": public_key,
                    "timestamp": now().isoformat()
                }
            )

            # Confirm to sender
            await self.send(text_data=json.dumps({
                "type": "public_key_shared_confirmation",
                "contact_id": contact_id,  # String
                "timestamp": now().isoformat()
            }))

        except Exception as e:
            print(f"❌ Error in share_public_key_handler: {e}")

    async def encryption_status_handler(self, data):
        """Handle encryption status updates"""
        try:
            contact_id = data.get("contact_id")  # String from frontend
            status = data.get("status")  # 'enabled', 'disabled', 'error'
            message = data.get("message", "")
            
            if not contact_id:
                return

            # Send encryption status to the specific contact
            await self.channel_layer.send(
                f"user_{contact_id}",
                {
                    "type": "encryption_status_update",
                    "user_id": self.user_id,  # String
                    "user_name": self.user_name,
                    "status": status,
                    "message": message,
                    "timestamp": now().isoformat()
                }
            )

        except Exception as e:
            print(f"❌ Error in encryption_status_handler: {e}")

    async def key_exchange_handler(self, data):
        """Handle secure key exchange for establishing encrypted sessions"""
        try:
            contact_id = data.get("contact_id")  # String from frontend
            encrypted_session_key = data.get("encrypted_session_key")
            key_type = data.get("key_type")  # 'init', 'response', 'confirm'
            
            if not contact_id or not encrypted_session_key:
                return

            print(f"🔐 KEY EXCHANGE - Type: {key_type}, From: {self.user_id}, To: {contact_id}")

            # Forward key exchange data to the contact
            await self.channel_layer.send(
                f"user_{contact_id}",
                {
                    "type": "key_exchange",
                    "sender_id": self.user_id,  # String
                    "sender_name": self.user_name,
                    "encrypted_session_key": encrypted_session_key,
                    "key_type": key_type,
                    "timestamp": now().isoformat()
                }
            )

        except Exception as e:
            print(f"❌ Error in key_exchange_handler: {e}")

    # =============================================
    # EVENT HANDLERS - Send messages to WebSocket
    # =============================================

    async def individual_message(self, event):
        await self.send(text_data=json.dumps(event))

    async def individual_message_edited(self, event):
        await self.send(text_data=json.dumps(event))

    async def individual_message_deleted(self, event):
        await self.send(text_data=json.dumps(event))

    async def individual_chat_cleared(self, event):
        await self.send(text_data=json.dumps(event))

    async def individual_read_receipt(self, event):
        await self.send(text_data=json.dumps(event))

    async def individual_typing_indicator(self, event):
        await self.send(text_data=json.dumps(event))

    # Encryption-related event handlers
    async def public_key_request(self, event):
        """Receive public key request from another user"""
        await self.send(text_data=json.dumps(event))

    async def public_key_shared(self, event):
        """Receive public key from another user"""
        await self.send(text_data=json.dumps(event))

    async def encryption_status_update(self, event):
        """Receive encryption status update from another user"""
        await self.send(text_data=json.dumps(event))

    async def key_exchange(self, event):
        """Receive key exchange data from another user"""
        await self.send(text_data=json.dumps(event))

    async def public_key_request_sent(self, event):
        """Confirmation that public key request was sent"""
        await self.send(text_data=json.dumps(event))

    async def public_key_request_failed(self, event):
        """Notification that public key request failed"""
        await self.send(text_data=json.dumps(event))

    async def public_key_shared_confirmation(self, event):
        """Confirmation that public key was shared"""
        await self.send(text_data=json.dumps(event))

    async def public_key_share_failed(self, event):
        """Notification that public key share failed"""
        await self.send(text_data=json.dumps(event))