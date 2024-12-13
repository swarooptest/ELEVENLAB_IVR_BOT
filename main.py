import json
import traceback
import os
import logging
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.rest import Client as TwilioClient

from elevenlabs import ElevenLabs
from elevenlabs.core.api_error import ApiError
from elevenlabs.conversational_ai.conversation import Conversation

from audio_interface import TwilioAudioInterface
from config import Settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize configuration
settings = Settings()

# Initialize Twilio Client
try:
    twilio_client = TwilioClient(
        settings.twilio_account_sid,
        settings.twilio_auth_token
    )
except Exception as e:
    logger.error(f"Twilio Client Initialization Error: {e}")
    raise

# Initialize ElevenLabs Client
try:
    eleven_labs_client = ElevenLabs(
        api_key=settings.elevenlabs_api_key
    )
except Exception as e:
    logger.error(f"ElevenLabs Client Initialization Error: {e}")
    raise

# Create FastAPI app
app = FastAPI(title="Twilio-ElevenLabs Voice Integration")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint for health check"""
    return {"status": "Server is running", "message": "Twilio-ElevenLabs Voice Integration"}


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    try:
        # Check ElevenLabs connectivity
        agents = eleven_labs_client.conversational_ai.list_agents()

        # Check Twilio connectivity
        twilio_client.calls.list(limit=1)

        return {
            "status": "healthy",
            "elevenlabs": {
                "status": "connected",
                "agents_count": len(agents)
            },
            "twilio": {
                "status": "connected"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "unhealthy",
                "error": str(e)
            }
        )


@app.api_route("/incoming-call-eleven", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio call and return TwiML"""
    try:
        host = request.url.hostname
        response = VoiceResponse()
        connect = Connect()
        connect.stream(url=f"wss://{host}/media-stream")
        response.append(connect)
        return HTMLResponse(content=str(response), media_type="application/xml")
    except Exception as e:
        logger.error(f"Error handling incoming call: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to process incoming call"}
        )


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """WebSocket handler for media streaming"""
    await websocket.accept()
    logger.info("WebSocket connection established")

    audio_interface: Optional[TwilioAudioInterface] = None
    conversation: Optional[Conversation] = None

    try:
        audio_interface = TwilioAudioInterface(websocket)

        conversation = Conversation(
            client=eleven_labs_client,
            agent_id=settings.agent_id,
            requires_auth=True,
            audio_interface=audio_interface,
            callback_agent_response=lambda text: logger.info(f"Agent Response: {text}"),
            callback_user_transcript=lambda text: logger.info(f"User Transcript: {text}")
        )

        logger.info("Starting conversation session")
        conversation.start_session()

        async for message in websocket.iter_text():
            if not message:
                continue

            try:
                data = json.loads(message)
                await audio_interface.handle_twilio_message(data)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON message: {message}")
            except Exception as message_error:
                logger.error(f"Error processing WebSocket message: {message_error}")
                logger.error(traceback.format_exc())

    except ApiError as api_error:
        logger.error(f"ElevenLabs API Error: {api_error}")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"Unexpected error in media stream: {e}")
        logger.error(traceback.format_exc())
    finally:
        if conversation:
            try:
                conversation.end_session()
                conversation.wait_for_session_end()
            except Exception as end_session_error:
                logger.error(f"Error ending conversation session: {end_session_error}")

        logger.info("Media stream handler completed")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )