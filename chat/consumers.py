
# # consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from pymongo import MongoClient
from bson import ObjectId
from django.utils.timezone import now

MONGO_URI = "mongodb+srv://adityapandey:12345@chat-cluster.7qiiw2q.mongodb.net/?retryWrites=true&w=majority&appName=chat-cluster"
client = MongoClient(MONGO_URI)
db = client['chat']
messages_collection = db['messages_websocket']
users_collection = db['users']

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user_id = str(self.scope['session'].get('user_id'))
        if not self.user_id:
            await self.close()
            return

        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'

        # mark online
        users_collection.update_one(
            {"_id": ObjectId(self.user_id)},
            {"$set": {"status": "online", "last_seen": now()}}
        )

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        except Exception:
            pass

        users_collection.update_one(
            {"_id": ObjectId(self.user_id)},
            {"$set": {"status": "offline", "last_seen": now()}}
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            t = data.get("type")

            if t == "chat_message":
                await self.chat_message_handler(data)
            elif t == "edit_message":
                await self.edit_message_handler(data)
            elif t == "delete_message":
                await self.delete_message_handler(data)
            elif t == "clear_chat":
                await self.clear_chat_handler(data)
            elif t == "read_receipt":
                await self.read_receipt_handler(data)
            elif t == "typing":
                await self.typing_handler(data)
            else:
                # unknown type - ignore or log
                pass
        except Exception as e:
            print("receive error:", e)

    async def chat_message_handler(self, data):
        """
        Stores message, broadcasts to group and includes temp_id if provided
        so sender can match optimistic message -> real id.
        """
        msg = (data.get("message") or "").strip()
        recv = data.get("receiver_id")
        temp_id = data.get("temp_id")  # may be None

        if not msg or not recv:
            return

        ts = now()
        room = "_".join(sorted([self.user_id, recv]))

        doc = {
            "room": room,
            "sender_id": self.user_id,
            "receiver_id": recv,
            "message": msg,
            "timestamp": ts,
            "read": False,
            "edited": False,
            "deleted": False
        }
        result = messages_collection.insert_one(doc)
        mid = str(result.inserted_id)

        event = {
            # "type" here is the channel handler name called on group consumers
            "type": "chat_message",
            "message_id": mid,
            "message": msg,
            "sender_id": self.user_id,
            "receiver_id": recv,
            "timestamp": ts.isoformat(),
            "read": False,
            # "status": "sent",
            # echo temp_id back so sender can map temp->real
            "temp_id": temp_id
        }

        await self.channel_layer.group_send(self.room_group_name, event)
        # no extra send needed because group_send will deliver to all including sender

    async def edit_message_handler(self, data):
        mid = data.get("message_id")
        new = data.get("new_content", "").strip()
        if not mid or not new:
            return

        try:
            messages_collection.update_one(
                {"_id": ObjectId(mid), "sender_id": self.user_id},
                {"$set": {"message": new, "edited": True, "edit_timestamp": now()}}
            )
        except Exception as e:
            print(f"Error editing message: {e}")
            return

        # Send edit notification to room group - Match JavaScript expected format
        await self.channel_layer.group_send(self.room_group_name, {
            "type": "message_edited",
            "message_id": mid,
            "new_content": new,
            "timestamp": now().isoformat(),
            "editor_id": self.user_id  # JavaScript expects editor_id, not sender_id
        })


    async def delete_message_handler(self, data):
        mid = data.get("message_id")
        if not mid:
            return

        try:
            # Handle both temp IDs (for queued operations) and real IDs
            if isinstance(mid, str) and mid.startswith('temp_'):
                # This is a temp ID from a queued operation - we should have the real ID by now
                # Look up real ID from your database tracking system if needed
                print(f"Received delete for temp ID {mid} - should have real ID by now")
                return
                
            # Convert to ObjectId for real messages
            result = messages_collection.update_one(
                {"_id": ObjectId(mid), "sender_id": self.user_id},
                {"$set": {
                    "message": "This message was deleted", 
                    "deleted": True,
                    "delete_timestamp": now()
                }}
            )
            
            if result.modified_count == 0:
                print(f"Message {mid} not found or not authorized for deletion")
                return
                
        except Exception as e:
            print(f"Error in delete_message_handler: {e}")
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "message_deleted",
            "message_id": mid,
            "deleter_id": self.user_id
        })
        
    async def clear_chat_handler(self, data):
        recv = data.get("receiver_id")
        if not recv:
            return
        room = "_".join(sorted([self.user_id, recv]))

        try:
            # Permanently delete all messages from the database
            result = messages_collection.delete_many({"room": room})
            print(f"Deleted {result.deleted_count} messages from room {room}")
        except Exception as e:
            print(f"Error deleting messages: {e}")
            pass

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "chat_cleared",
            "room": room,
            "cleared_by": self.user_id,
            "permanent_delete": True  # Indicate that messages were permanently deleted
        })


    async def read_receipt_handler(self, data):
        """
        data: { message_ids: [id1, id2, ...] }
        We'll set read=True for those docs and include a message_map (id->text)
        in the event to help senders map temp messages.
        """
        mids = data.get("message_ids", [])
        if not mids:
            return

        # try update DB
        obj_ids = []
        valid_mids = []
        for mid in mids:
            try:
                # Skip temporary IDs (they can't be updated in DB)
                if isinstance(mid, str) and mid.startswith('temp_'):
                    continue
                    
                obj_ids.append(ObjectId(mid))
                valid_mids.append(mid)
            except Exception:
                # Handle invalid ObjectId format
                continue

        if obj_ids:
            # Update only valid messages in database
            result = messages_collection.update_many(
                {"_id": {"$in": obj_ids}},
                {"$set": {"read": True, "read_timestamp": now()}}
            )
            print(f"Marked {result.modified_count} messages as read")

        # Send read receipt to ALL clients in the room
        await self.channel_layer.group_send(self.room_group_name, {
            "type": "read_receipt",
            "message_ids": valid_mids,  # Only send valid message IDs
            "reader_id": self.user_id,
            "timestamp": now().isoformat()
        })

    async def typing_handler(self, data):
        recv = data.get("receiver_id")
        is_typing = bool(data.get("is_typing", False))
        if not recv:
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "typing_indicator",
            "sender_id": self.user_id,
            "is_typing": is_typing
        })

    # Group event handlers — these send JSON directly to websocket clients
    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    async def message_edited(self, event):
        await self.send(text_data=json.dumps(event))

    async def message_deleted(self, event):
        await self.send(text_data=json.dumps(event))

    async def chat_cleared(self, event):
        await self.send(text_data=json.dumps(event))

    async def read_receipt(self, event):
        await self.send(text_data=json.dumps(event))

    async def typing_indicator(self, event):
        await self.send(text_data=json.dumps(event))



