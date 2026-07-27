import json
from channels.generic.websocket import AsyncWebsocketConsumer


class TestConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data=None, bytes_data=None):
        # Echo back the received text data
        if text_data:
            await self.send(text_data=json.dumps({
                'message': text_data
            }))
        # Echo back the received bytes data
        elif bytes_data:
            await self.send(bytes_data=bytes_data)
