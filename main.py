from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import requests
import os

app = FastAPI()

# A simple API key protection so others don't abuse your server
API_KEY = os.getenv("API_KEY", "my_secret_key")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def get_api_key(auth_header: str = Security(api_key_header)):
    if API_KEY:
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
        token = auth_header.split(" ")[1]
        if token != API_KEY:
            raise HTTPException(status_code=403, detail="Could not validate API key")
    return auth_header

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class TranscriptRequest(BaseModel):
    videoId: str

@app.post("/transcript")
def get_transcript(req: TranscriptRequest, api_key: str = Depends(get_api_key)):
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'quiet': True,
        'extractor_args': {'youtube': {'client': ['android', 'ios']}}
    }
    
    url = f"https://www.youtube.com/watch?v={req.videoId}"
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # We don't need to actually download the video, just get the info
            info = ydl.extract_info(url, download=False)
            
            subs = info.get('subtitles', {})
            auto_subs = info.get('automatic_captions', {})
            
            en_subs = subs.get('en') or subs.get('en-US') or subs.get('en-GB') or auto_subs.get('en')
            if not en_subs:
                raise HTTPException(status_code=404, detail="No transcript (disabled or missing)")
                
            # yt-dlp returns a list of formats. We want json3 for exact timestamps.
            json3_track = next((s for s in en_subs if s['ext'] == 'json3'), None)
            if not json3_track:
                raise HTTPException(status_code=404, detail="No json3 transcript format found")
            
            res = requests.get(json3_track['url'])
            if not res.ok:
                raise HTTPException(status_code=502, detail="Failed to fetch transcript from YouTube")
                
            data = res.json()
            
            segments = []
            for event in data.get('events', []):
                if 'segs' in event:
                    text = "".join([seg.get('utf8', '') for seg in event['segs']]).strip()
                    if text and text != '\n':
                        segments.append({
                            'text': text,
                            'start': event.get('tStartMs', 0) / 1000.0,
                            'duration': event.get('dDurationMs', 0) / 1000.0
                        })
            
            if not segments:
                raise HTTPException(status_code=404, detail="No transcript content")
                
            return {"segments": segments}
            
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).lower()
        if 'unavailable' in msg:
            raise HTTPException(status_code=404, detail="Video unavailable")
        if 'age restricted' in msg:
            raise HTTPException(status_code=403, detail="Age restricted")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "ok"}
