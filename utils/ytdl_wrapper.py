"""
YouTube interactions using yt-dlp.
Handles searching, playlist extraction, and audio downloading.
"""

import os
import yt_dlp
from typing import List, Dict, Optional
import re
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
import asyncio

# TODO: Add unit tests


def search_youtube(query: str, max_results: int = 5) -> List[Dict]:
    """
    Search YouTube for videos matching the query.
    
    Args:
        query: Search keywords
        max_results: Maximum number of results to return
        
    Returns:
        List of dictionaries with video information
    """
    search_query = f"ytsearch{max_results}:{query}"
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(search_query, download=False)
            
            results = []
            for entry in search_results.get('entries', []):
                if entry:
                    results.append({
                        'id': entry.get('id', ''),
                        'title': entry.get('title', 'Unknown'),
                        'duration': entry.get('duration', 0),
                        'webpage_url': entry.get('webpage_url', f"https://youtube.com/watch?v={entry.get('id', '')}"),
                        'thumbnail': entry.get('thumbnail', '')
                    })
            
            return results
            
    except Exception as e:
        raise Exception(f"YouTube search failed: {str(e)}")


def extract_playlist_videos(playlist_url: str) -> List[Dict]:
    """
    Extract all videos from a YouTube playlist.
    
    Args:
        playlist_url: YouTube playlist URL
        
    Returns:
        List of dictionaries with video information
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            playlist_info = ydl.extract_info(playlist_url, download=False)
            
            videos = []
            for entry in playlist_info.get('entries', []):
                if entry:
                    videos.append({
                        'id': entry.get('id', ''),
                        'title': entry.get('title', 'Unknown'),
                        'url': entry.get('webpage_url', f"https://youtube.com/watch?v={entry.get('id', '')}"),
                        'duration': entry.get('duration', 0)
                    })
            
            return videos
            
    except Exception as e:
        raise Exception(f"Playlist extraction failed: {str(e)}")


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe filenames."""
    return re.sub(r'[^\w\-_\. ]', '_', name)


async def download_audio_stream(url: str, user_id: int) -> str:
    """
    Download audio from YouTube video and convert to MP3.
    If already downloaded, reuse the file.
    Args:
        url: YouTube video URL or ID
        user_id: User ID for organizing downloads
    Returns:
        Absolute path to the downloaded audio file
    """
    # Get video info for title
    info = await asyncio.get_event_loop().run_in_executor(None, get_video_info, url)
    title = info.get('title', 'Unknown')
    video_id = info.get('id', '')
    # Sanitize title for filename
    safe_title = sanitize_filename(title)
    download_dir = f"downloads/{user_id}"
    os.makedirs(download_dir, exist_ok=True)
    audio_path = os.path.join(download_dir, f"{safe_title}_{video_id}.m4a")
    # If file exists, return it
    if os.path.exists(audio_path):
        return os.path.abspath(audio_path)
    # Download to temp file first
    temp_audio_path = os.path.join(download_dir, f"{video_id}.m4a")
    ydl_opts = {
        'format': 'bestaudio/best',  # More flexible format selection
        'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'retries': 3,
        'fragment_retries': 3,
        'skip_unavailable_fragments': True,
        'keepvideo': False,
        'writethumbnail': False,
        'noplaylist': True,
        'extract_flat': False,
        'concurrent_fragments': 4,  # Parallel fragment downloads
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
            'preferredquality': '192',
        }],
    }
    try:
        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            # Rename to include title
            if os.path.exists(temp_audio_path):
                os.rename(temp_audio_path, audio_path)
            return os.path.abspath(audio_path)
            
        return await asyncio.get_event_loop().run_in_executor(None, _download)
    except Exception as e:
        raise Exception(f"Audio download failed: {str(e)}")


def get_video_info(url: str) -> Dict:
    """
    Get video information without downloading.
    
    Args:
        url: YouTube video URL or ID
        
    Returns:
        Dictionary with video information
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'id': info.get('id', ''),
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'webpage_url': info.get('webpage_url', url),
                'thumbnail': info.get('thumbnail', '')
            }
            
    except Exception as e:
        raise Exception(f"Failed to get video info: {str(e)}")
