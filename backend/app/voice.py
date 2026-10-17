import os
import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/voice", tags=["voice"])

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)

@router.get('/status')
def status():
    return {"available": bool(os.getenv('ELEVENLABS_API_KEY') and os.getenv('ELEVENLABS_VOICE_ID'))}

@router.post('/speech')
async def speech(body: SpeechRequest):
    key, voice = os.getenv('ELEVENLABS_API_KEY'), os.getenv('ELEVENLABS_VOICE_ID')
    if not key or not voice:
        raise HTTPException(503, 'Voice is not configured. You can still read and type your answers.')
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            result = await client.post(f'https://api.elevenlabs.io/v1/text-to-speech/{voice}',
                headers={'xi-api-key': key, 'Accept': 'audio/mpeg'},
                json={'text': body.text, 'model_id': 'eleven_flash_v2_5'})
        result.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(502, 'Voice playback is unavailable. Please try again or read the question.') from None
    return Response(result.content, media_type='audio/mpeg', headers={'Cache-Control': 'no-store'})
