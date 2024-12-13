import asyncio
import base64
import queue
import threading
from typing import Callable
from elevenlabs.conversational_ai.conversation import AudioInterface
import websockets
import logging

logger = logging.getLogger(__name__)


class TwilioAudioInterface(AudioInterface):
    def __init__(self, websocket):
        self.websocket = websocket
        self.output_queue = queue.Queue()
        self.should_stop = threading.Event()
        self.stream_sid = None
        self.input_callback = None
        self.output_thread = None

    def start(self, input_callback: Callable[[bytes], None]):
        """Start audio processing"""
        self.input_callback = input_callback
        self.output_thread = threading.Thread(target=self._output_thread)
        self.output_thread.daemon = True
        self.output_thread.start()

    def stop(self):
        """Stop audio processing"""
        self.should_stop.set()
        if self.output_thread:
            self.output_thread.join(timeout=5.0)
        self.stream_sid = None

    def output(self, audio: bytes):
        """Queue audio for output"""
        self.output_queue.put(audio)

    def interrupt(self):
        """Clear output queue and send clear message"""
        try:
            while True:
                _ = self.output_queue.get(block=False)
        except queue.Empty:
            pass
        asyncio.run(self._send_clear_message())

    async def handle_twilio_message(self, data):
        """Process incoming Twilio WebSocket messages"""
        try:
            if data.get("event") == "start":
                self.stream_sid = data["start"].get("streamSid")
                logger.info(f"Started stream with stream_sid: {self.stream_sid}")

            if data.get("event") == "media":
                audio_data = base64.b64decode(data["media"]["payload"])
                if self.input_callback:
                    self.input_callback(audio_data)
        except Exception as e:
            logger.error(f"Error processing Twilio message: {e}")

    def _output_thread(self):
        """Background thread for sending audio"""
        while not self.should_stop.is_set():
            asyncio.run(self._send_audio_to_twilio())

    async def _send_audio_to_twilio(self):
        """Send audio payload to Twilio"""
        try:
            audio = self.output_queue.get(timeout=0.2)
            audio_payload = base64.b64encode(audio).decode("utf-8")
            audio_delta = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": audio_payload},
            }
            await self.websocket.send_json(audio_delta)
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error sending audio to Twilio: {e}")

    async def _send_clear_message(self):
        """Send clear message to Twilio"""
        try:
            clear_message = {"event": "clear", "streamSid": self.stream_sid}
            await self.websocket.send_json(clear_message)
        except Exception as e:
            logger.error(f"Error sending clear message: {e}")