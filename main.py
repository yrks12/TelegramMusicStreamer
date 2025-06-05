"""
Telegram YouTube Music Bot
A personal bot for searching, playing, and managing YouTube music.
"""

import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaAudio
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ChatAction
import telegram

from utils.ytdl_wrapper import search_youtube, download_audio_stream, extract_playlist_videos, get_video_info
from utils.playlist_manager import PlaylistManager
from utils.storage import StorageManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Session:
    """Manages user playback session state."""
    
    def __init__(self):
        self.queue: list[Dict] = []
        self.current_index: Optional[int] = None
        self.message_id: Optional[int] = None
        self.chat_id: Optional[int] = None
        self.is_paused: bool = False
        self.current_download_task: Optional[asyncio.Task] = None
        self.downloading_message_id: Optional[int] = None

    def add_track(self, track_info: Dict) -> None:
        """Add a track to the queue."""
        self.queue.append(track_info)
        if self.current_index is None:
            self.current_index = 0

    def get_current_track(self) -> Optional[Dict]:
        """Get the current track info."""
        if self.current_index is None or not self.queue:
            return None
        return self.queue[self.current_index]

    def next_track(self) -> bool:
        """Move to next track. Returns True if successful."""
        if not self.queue or self.current_index is None:
            return False
        if self.current_index < len(self.queue) - 1:
            self.current_index += 1
            return True
        return False

    def prev_track(self) -> bool:
        """Move to previous track. Returns True if successful."""
        if not self.queue or self.current_index is None:
            return False
        if self.current_index > 0:
            self.current_index -= 1
            return True
        return False

    def clear(self) -> None:
        """Clear the session state."""
        self.queue.clear()
        self.current_index = None
        self.message_id = None
        self.chat_id = None
        self.is_paused = False
        self.downloading_message_id = None
        if self.current_download_task:
            self.current_download_task.cancel()
            self.current_download_task = None

# Initialize utility managers and sessions
playlist_manager = PlaylistManager()
storage_manager = StorageManager()
user_sessions: Dict[int, Session] = {}

def get_session(user_id: int) -> Session:
    """Get or create a session for the user."""
    if user_id not in user_sessions:
        user_sessions[user_id] = Session()
    return user_sessions[user_id]

def build_playback_keyboard(session: Session) -> InlineKeyboardMarkup:
    """Build the playback control keyboard."""
    buttons = []
    row = []
    
    # Previous button
    row.append(InlineKeyboardButton("⏮️ Prev", callback_data="prev"))
    
    # Play/Pause button
    if session.is_paused:
        row.append(InlineKeyboardButton("▶️ Resume", callback_data="resume"))
    else:
        row.append(InlineKeyboardButton("⏸️ Pause", callback_data="pause"))
    
    # Next button
    row.append(InlineKeyboardButton("⏭️ Next", callback_data="next"))
    
    # Stop button
    row.append(InlineKeyboardButton("⏹️ Stop", callback_data="stop"))
    
    buttons.append(row)
    return InlineKeyboardMarkup(buttons)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "🎵 Welcome to the Music Player Bot!\n\n"
        "🎧 How to use the player:\n"
        "1. Use /search to find music\n"
        "2. Select a track to start playing\n"
        "3. Control playback with the buttons below the 'Now Playing' message:\n"
        "   ⏮️ Previous track\n"
        "   ⏸️ Pause / ▶️ Resume\n"
        "   ⏭️ Next track\n"
        "   ⏹️ Stop playback\n\n"
        "📋 Other commands:\n"
        "• /play <URL> - Play a video or playlist\n"
        "• /queue - View your current queue\n"
        "• /next - Skip to next track\n"
        "• /history - View your play history\n\n"
        "💡 Tip: The 'Now Playing' message stays in place and updates as you control playback!"
    )


async def playback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle playback control callbacks (prev, pause, resume, next, stop)."""
    query = update.callback_query
    try:
        await query.answer()
    except telegram.error.BadRequest as e:
        if "Query is too old" in str(e):
            # Ignore old query errors
            pass
        else:
            raise
    
    user_id = query.from_user.id
    session = get_session(user_id)
    action = query.data
    
    if action == "prev":
        if session.prev_track():
            await start_next(context, user_id)
    elif action == "pause":
        session.is_paused = True
        try:
            await query.edit_message_reply_markup(reply_markup=build_playback_keyboard(session))
        except telegram.error.BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    elif action == "resume":
        session.is_paused = False
        try:
            await query.edit_message_reply_markup(reply_markup=build_playback_keyboard(session))
        except telegram.error.BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
        await start_next(context, user_id)
    elif action == "next":
        if session.next_track():
            await start_next(context, user_id)
        else:
            try:
                await query.edit_message_text(
                    text="❌ Queue is empty. Use /search to add more tracks.",
                    reply_markup=build_playback_keyboard(session)
                )
            except telegram.error.BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise
    elif action == "stop":
        if session.message_id and session.chat_id:
            try:
                await context.bot.delete_message(
                    chat_id=session.chat_id,
                    message_id=session.message_id
                )
            except telegram.error.BadRequest as e:
                if "Message to delete not found" not in str(e):
                    logger.error(f"Error deleting message: {e}")
        if session.downloading_message_id and session.chat_id:
            try:
                await context.bot.delete_message(
                    chat_id=session.chat_id,
                    message_id=session.downloading_message_id
                )
            except telegram.error.BadRequest as e:
                if "Message to delete not found" not in str(e):
                    logger.error(f"Error deleting downloading message: {e}")
        session.clear()
        user_sessions.pop(user_id, None)

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command - search YouTube and return results with inline keyboard."""
    if not context.args:
        await update.message.reply_text("Usage: /search <keywords>")
        return
    
    query = " ".join(context.args)
    
    # Send typing action
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    try:
        # Search YouTube in executor to avoid blocking
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, search_youtube, query, 5)
        
        if not results:
            await update.message.reply_text("No results found.")
            return
        
        # Build inline keyboard with search results
        keyboard = []
        for result in results:
            # Format duration as MM:SS
            duration = int(result.get('duration', 0) or 0)
            minutes, seconds = divmod(duration, 60)
            duration_str = f"({minutes:02d}:{seconds:02d})"
            
            # Format title with uploader
            title = result['title']
            uploader = result.get('uploader', 'Unknown Artist')
            
            # Truncate title and uploader if needed
            max_title_len = 30
            max_uploader_len = 20
            
            if len(title) > max_title_len:
                title = title[:max_title_len-3] + "..."
            if len(uploader) > max_uploader_len:
                uploader = uploader[:max_uploader_len-3] + "..."
            
            button_text = f"{title} {duration_str} - {uploader}"
            callback_data = f"play::{result['webpage_url']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select a track to play or queue:", reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text(f"❌ Search failed: {str(e)}")


def build_now_playing_keyboard(user_id):
    queue = playlist_manager.list_queue(user_id)
    buttons = []
    if queue:
        buttons.append(InlineKeyboardButton("⏭️ Next", callback_data="queue_next"))
    buttons.append(InlineKeyboardButton("📜 View Queue", callback_data="queue_view"))
    buttons.append(InlineKeyboardButton("➕ Add to Playlist", callback_data="add_to_playlist"))
    return InlineKeyboardMarkup([buttons])


async def predownload_next(user_id):
    queue = playlist_manager.list_queue(user_id)
    if queue:
        next_track = queue[0]
        url = next_track.get('url')
        from utils.ytdl_wrapper import download_audio_stream
        loop = asyncio.get_event_loop()
        # Only download if not already downloaded
        await loop.run_in_executor(None, download_audio_stream, url, user_id)


async def start_next(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Start playing the next track in the queue."""
    session = get_session(user_id)
    logger.info(f"[start_next] user_id={user_id} current_index={session.current_index} queue_len={len(session.queue)} is_paused={session.is_paused}")
    if not session.queue or session.current_index is None:
        logger.info(f"[start_next] No queue or current_index is None for user_id={user_id}")
        return

    track = session.get_current_track()
    if not track:
        logger.info(f"[start_next] No current track for user_id={user_id}")
        return

    try:
        # Format duration as MM:SS
        duration = track.get('duration', 0)
        minutes, seconds = divmod(duration, 60)
        duration_str = f"{minutes:02d}:{seconds:02d}"

        # Update the "Now Playing" message
        message_text = (
            f"🎶 Now Playing:\n"
            f"{track['title']}\n"
            f"🧑‍🎤 Author: {track.get('uploader', 'Unknown Artist')}\n"
            f"⏱️ Duration: {duration_str}"
        )

        # Send "Downloading..." message
        if session.chat_id:
            try:
                downloading_message = await context.bot.send_message(
                    chat_id=session.chat_id,
                    text=f"⏬ Downloading {track['title']}... please wait"
                )
                session.downloading_message_id = downloading_message.message_id
            except Exception as e:
                logger.error(f"Error sending downloading message: {e}")

        if session.message_id and session.chat_id:
            try:
                # If we have a thumbnail, send it first
                if track.get('thumbnail'):
                    try:
                        await context.bot.send_photo(
                            chat_id=session.chat_id,
                            photo=track['thumbnail'],
                            caption=message_text,
                            reply_markup=build_playback_keyboard(session)
                        )
                        # Delete the old message if it exists
                        try:
                            await context.bot.delete_message(
                                chat_id=session.chat_id,
                                message_id=session.message_id
                            )
                        except telegram.error.BadRequest as e:
                            if "Message to delete not found" not in str(e):
                                logger.error(f"Error deleting old message: {e}")
                    except Exception as e:
                        logger.error(f"Error sending thumbnail: {e}")
                        # Fallback to text-only message if thumbnail fails
                        await context.bot.edit_message_text(
                            chat_id=session.chat_id,
                            message_id=session.message_id,
                            text=message_text,
                            reply_markup=build_playback_keyboard(session)
                        )
                else:
                    # No thumbnail, just update text
                    await context.bot.edit_message_text(
                        chat_id=session.chat_id,
                        message_id=session.message_id,
                        text=message_text,
                        reply_markup=build_playback_keyboard(session)
                    )
            except telegram.error.BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating message: {e}")
                    # Session might have expired
                    session.clear()
                    user_sessions.pop(user_id, None)
                    return
            except Exception as e:
                logger.error(f"Error updating message: {e}")
                # Session might have expired
                session.clear()
                user_sessions.pop(user_id, None)
                return
        else:
            # Create new "Now Playing" message if it doesn't exist
            if track.get('thumbnail'):
                try:
                    message = await context.bot.send_photo(
                        chat_id=session.chat_id,
                        photo=track['thumbnail'],
                        caption=message_text,
                        reply_markup=build_playback_keyboard(session)
                    )
                except Exception as e:
                    logger.error(f"Error sending thumbnail: {e}")
                    # Fallback to text-only message if thumbnail fails
                    message = await context.bot.send_message(
                        chat_id=session.chat_id,
                        text=message_text,
                        reply_markup=build_playback_keyboard(session)
                    )
            else:
                message = await context.bot.send_message(
                    chat_id=session.chat_id,
                    text=message_text,
                    reply_markup=build_playback_keyboard(session)
                )
            session.message_id = message.message_id
            session.chat_id = message.chat_id

        # Download and send the audio file
        if not session.is_paused:
            try:
                # Send immediate "uploading" status
                await context.bot.send_chat_action(
                    chat_id=session.chat_id,
                    action=ChatAction.UPLOAD_VOICE
                )
                
                # Download audio
                result = await download_audio_stream(track['url'], user_id)
                filepath = result['filepath']
                
                # Update track info with metadata if not already present
                if 'uploader' not in track:
                    track['uploader'] = result['uploader']
                if 'thumbnail' not in track:
                    track['thumbnail'] = result['thumbnail']
                
                # Delete the "Downloading..." message if it exists
                if session.downloading_message_id and session.chat_id:
                    try:
                        await context.bot.delete_message(
                            chat_id=session.chat_id,
                            message_id=session.downloading_message_id
                        )
                    except telegram.error.BadRequest as e:
                        if "Message to delete not found" not in str(e):
                            logger.error(f"Error deleting downloading message: {e}")
                    session.downloading_message_id = None
                
                # Download thumbnail if available
                thumbnail_path = None
                if track.get('thumbnail'):
                    try:
                        import requests
                        from io import BytesIO
                        from PIL import Image
                        
                        # Create thumbnail directory if it doesn't exist
                        thumb_dir = os.path.join("downloads", str(user_id), "thumbnails")
                        os.makedirs(thumb_dir, exist_ok=True)
                        
                        # Download and resize thumbnail
                        response = requests.get(track['thumbnail'])
                        if response.status_code == 200:
                            img = Image.open(BytesIO(response.content))
                            # Resize to a reasonable size (320x180)
                            img.thumbnail((320, 180))
                            thumbnail_path = os.path.join(thumb_dir, f"{track['id']}.jpg")
                            img.save(thumbnail_path, "JPEG")
                    except Exception as e:
                        logger.error(f"Error downloading thumbnail: {e}")
                        thumbnail_path = None
                
                # Send audio with thumbnail and caption
                try:
                    if thumbnail_path and os.path.exists(thumbnail_path):
                        with open(thumbnail_path, 'rb') as thumb_file, open(filepath, 'rb') as audio_file:
                            await context.bot.send_audio(
                                chat_id=session.chat_id,
                                audio=audio_file,
                                title=track['title'],
                                duration=track.get('duration', 0),
                                performer=track.get('uploader', 'Unknown Artist'),
                                caption=message_text,
                                thumb=thumb_file
                            )
                    else:
                        # Fallback to audio without thumbnail
                        with open(filepath, 'rb') as audio_file:
                            await context.bot.send_audio(
                                chat_id=session.chat_id,
                                audio=audio_file,
                                title=track['title'],
                                duration=track.get('duration', 0),
                                performer=track.get('uploader', 'Unknown Artist'),
                                caption=message_text
                            )
                finally:
                    # Clean up thumbnail file
                    if thumbnail_path and os.path.exists(thumbnail_path):
                        try:
                            os.remove(thumbnail_path)
                        except Exception as e:
                            logger.error(f"Error removing thumbnail file: {e}")
                
                # Record in history
                storage_manager.record_play(user_id, {
                    'title': track['title'],
                    'url': track['url'],
                    'duration': track.get('duration', 0),
                    'uploader': track.get('uploader', 'Unknown Artist')
                })
                
                # Clean up the downloaded file
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                # Check if there's a next track
                logger.info(f"[start_next] Finished sending audio for index={session.current_index} queue_len={len(session.queue)}")
                if session.current_index + 1 < len(session.queue):
                    logger.info(f"[start_next] Auto-advancing to next track for user_id={user_id}")
                    session.current_index += 1
                    await asyncio.sleep(1)
                    await start_next(context, user_id)
                else:
                    logger.info(f"[start_next] Queue finished for user_id={user_id}")
                    if session.message_id and session.chat_id:
                        try:
                            # Try to send a new message instead of editing
                            await context.bot.send_message(
                                chat_id=session.chat_id,
                                text="▶️ Queue finished. Use /search or /play to add more.",
                                reply_markup=build_playback_keyboard(session)
                            )
                            # Delete the old message
                            try:
                                await context.bot.delete_message(
                                    chat_id=session.chat_id,
                                    message_id=session.message_id
                                )
                            except telegram.error.BadRequest as e:
                                if "Message to delete not found" not in str(e):
                                    logger.error(f"Error deleting old message: {e}")
                        except Exception as e:
                            logger.error(f"Error sending queue finished message: {e}")
            except Exception as e:
                logger.error(f"Error downloading/sending audio: {e}")
                error_text = f"❌ Could not play {track['title']}: {str(e)}"
                if session.message_id and session.chat_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=session.chat_id,
                            message_id=session.message_id,
                            text=error_text,
                            reply_markup=build_playback_keyboard(session)
                        )
                    except telegram.error.BadRequest as e:
                        if "Message is not modified" not in str(e):
                            logger.error(f"Error updating error message: {e}")
                    except Exception as e:
                        logger.error(f"Error updating error message: {e}")
    except Exception as e:
        logger.error(f"Error in start_next: {e}")
        error_text = f"❌ Session error: {str(e)}"
        if session.message_id and session.chat_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=session.chat_id,
                    message_id=session.message_id,
                    text=error_text,
                    reply_markup=build_playback_keyboard(session)
                )
            except telegram.error.BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating error message: {e}")
            except Exception as e:
                logger.error(f"Error updating error message: {e}")

async def play_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks to play or queue a selected track."""
    query = update.callback_query
    await query.answer()
    data = query.data  # format: "play::<url>"
    _, url = data.split("::", 1)
    user_id = query.from_user.id

    session = get_session(user_id)
    # Set chat_id for session if not set
    if not session.chat_id:
        session.chat_id = query.message.chat_id

    # Delete the search results inline keyboard message
    try:
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
    except Exception:
        pass
    # Delete the user's /search message if available
    try:
        if query.message.reply_to_message:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.reply_to_message.message_id)
    except Exception:
        pass

    # Get video info to store metadata
    try:
        info = await asyncio.get_event_loop().run_in_executor(None, get_video_info, url)
        track_info = {
            "title": info.get('title', 'Unknown'),
            "url": url,
            "duration": info.get('duration', 0),
            "uploader": info.get('uploader', 'Unknown Artist'),
            "thumbnail": info.get('thumbnail', '')
        }
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        track_info = {
            "title": "Unknown",
            "url": url,
            "duration": 0,
            "uploader": "Unknown Artist",
            "thumbnail": ""
        }

    # If queue is empty, add and start playback
    if not session.queue:
        session.queue = [track_info]
        session.current_index = 0
        session.is_paused = False
        logger.info(f"[play_callback] Starting new queue for user_id={user_id}")
        await start_next(context, user_id)
    else:
        # Otherwise, append to queue
        session.queue.append(track_info)
        logger.info(f"[play_callback] Appended to queue for user_id={user_id} queue_len={len(session.queue)}")
        # Optionally, send a quick confirmation and delete it immediately
        try:
            added_msg = await context.bot.send_message(chat_id=query.message.chat_id, text=f"✅ Added to queue: {track_info['title']}")
            await asyncio.sleep(1)
            await context.bot.delete_message(chat_id=added_msg.chat_id, message_id=added_msg.message_id)
        except Exception:
            pass

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /play: play single video or enqueue entire playlist."""
    if not context.args:
        await update.message.reply_text("Usage: /play <YouTube URL or ID>")
        return

    url = context.args[0]
    user_id = update.message.from_user.id
    session = get_session(user_id)
    session.chat_id = update.message.chat_id

    # Detect playlist URL
    if "playlist?list=" in url or "&list=" in url:
        try:
            videos = await asyncio.get_event_loop().run_in_executor(
                None, lambda: extract_playlist_videos(url)
            )
            session.queue = videos
            session.current_index = 0
            session.is_paused = False
            logger.info(f"[play_command] Enqueued playlist for user_id={user_id} queue_len={len(videos)}")
            # Delete the user's /play command message
            try:
                await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            except Exception:
                pass
            # Optionally, send a quick playlist enqueued notification and delete it
            try:
                enq_msg = await context.bot.send_message(chat_id=update.message.chat_id, text=f"🚀 Playlist enqueued: {len(videos)} tracks.")
                await asyncio.sleep(1)
                await context.bot.delete_message(chat_id=enq_msg.chat_id, message_id=enq_msg.message_id)
            except Exception:
                pass
            await start_next(context, user_id)
        except Exception as e:
            await update.message.reply_text(f"❌ Error extracting playlist: {e}")
        return

    # Otherwise, play single video
    session.queue = [{"title": "Unknown", "url": url, "duration": None}]
    session.current_index = 0
    session.is_paused = False
    logger.info(f"[play_command] Playing single video for user_id={user_id}")
    # Delete the user's /play command message
    try:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    except Exception:
        pass
    await start_next(context, user_id)

async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /next or /queue: play the next track in the user's queue."""
    user_id = update.message.from_user.id
    next_track = playlist_manager.dequeue(user_id)

    if not next_track:
        await update.message.reply_text("Your queue is empty. Use /search to add something.")
        return

    url = next_track["url"]
    title = next_track.get("title", "Unknown Title")
    await update.message.chat.send_action(action=ChatAction.UPLOAD_VOICE)

    try:
        audio_path = await download_audio_stream(url, user_id)
        with open(audio_path, "rb") as audio_file:
            await update.message.reply_audio(audio=audio_file, title=title)

        storage_manager.record_play(user_id, next_track)
        os.remove(audio_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error playing next track: {e}")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history command - show recent play history."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    history = storage_manager.get_history(user_id)
    
    if not history:
        await update.message.reply_text("📜 No recent plays yet. Use /search or /play to start listening.")
        return
    
    # Build history message
    message = "📜 Your Recent Plays:\n\n"
    for entry in history:
        # Format timestamp
        timestamp = datetime.fromisoformat(entry['timestamp'])
        time_str = timestamp.strftime("%H:%M %Y-%m-%d")
        
        # Format duration
        duration = int(entry.get('duration', 0) or 0)
        minutes, seconds = divmod(duration, 60)
        duration_str = f"({minutes:02d}:{seconds:02d})"
        
        message += f"▶️ [{time_str}] {entry['title']} {duration_str}\n"
    
    # Add current session info if active
    if session.queue and session.current_index is not None:
        current = session.get_current_track()
        if current:
            message += f"\n🎵 Now Playing: {current['title']}"
    
    await update.message.reply_text(message)


async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized messages."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    
    # Check if user has an active session
    if session.message_id and session.chat_id:
        try:
            # Try to update the existing message
            await context.bot.edit_message_text(
                chat_id=session.chat_id,
                message_id=session.message_id,
                text="❓ Available commands:\n"
                     "• /search <keywords> - Find music\n"
                     "• /play <URL> - Play video/playlist\n"
                     "• /queue - View queue\n"
                     "• /history - View history\n\n"
                     "💡 Tap ▶️ to resume or ⏭️ to play next track",
                reply_markup=build_playback_keyboard(session)
            )
        except Exception as e:
            logger.error(f"Error updating message: {e}")
            # If message update fails, send new message
            await update.message.reply_text(
                "❓ Available commands:\n"
                "• /search <keywords> - Find music\n"
                "• /play <URL> - Play video/playlist\n"
                "• /queue - View queue\n"
                "• /history - View history"
            )
    else:
        # No active session, send basic help
        await update.message.reply_text(
            "❓ Available commands:\n"
            "• /search <keywords> - Find music\n"
            "• /play <URL> - Play video/playlist\n"
            "• /queue - View queue\n"
            "• /history - View history"
        )


def cleanup_old_downloads():
    """Clean up downloads older than 1 hour."""
    downloads_dir = "downloads"
    if not os.path.exists(downloads_dir):
        return
    
    current_time = datetime.now()
    for user_dir in os.listdir(downloads_dir):
        user_path = os.path.join(downloads_dir, user_dir)
        if not os.path.isdir(user_path):
            continue
        
        for file in os.listdir(user_path):
            file_path = os.path.join(user_path, file)
            if not os.path.isfile(file_path):
                continue
            
            file_time = datetime.fromtimestamp(os.path.getctime(file_path))
            if (current_time - file_time).total_seconds() > 3600:  # 1 hour
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.error(f"Error removing old file {file_path}: {e}")


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /queue command - show current queue."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    
    if not session.queue:
        await update.message.reply_text("📋 Queue is empty. Use /search to add tracks.")
        return
    
    # Build queue message
    message = "📋 Current Queue:\n\n"
    for i, track in enumerate(session.queue):
        # Format duration as MM:SS
        duration = int(track.get('duration', 0) or 0)
        minutes, seconds = divmod(duration, 60)
        duration_str = f"({minutes:02d}:{seconds:02d})"
        
        # Add "Now Playing" indicator
        if i == session.current_index:
            message += f"▶️ {track['title']} {duration_str}\n"
        else:
            message += f"{i + 1}. {track['title']} {duration_str}\n"
    
    # Add queue position info
    if session.current_index is not None:
        message += f"\n🎵 Now playing track {session.current_index + 1} of {len(session.queue)}"
    
    await update.message.reply_text(message)


async def queue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    queue = playlist_manager.list_queue(user_id)
    if data == "queue_next":
        # Play next track in queue
        if not queue:
            await query.answer("Queue is empty.")
            return
        next_track = playlist_manager.dequeue(user_id)
        if not next_track:
            await query.answer("Queue is empty.")
            return
        url = next_track.get('url')
        from utils.ytdl_wrapper import get_video_info
        loop = asyncio.get_event_loop()
        track_info = await loop.run_in_executor(None, get_video_info, url)
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_VOICE)
        filepath = await loop.run_in_executor(None, download_audio_stream, url, user_id)
        with open(filepath, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=audio_file,
                title=track_info.get('title', 'Unknown'),
                duration=track_info.get('duration'),
                reply_markup=build_now_playing_keyboard(user_id)
            )
        storage_manager.record_play(user_id, {
            'title': track_info.get('title', 'Unknown'),
            'url': url,
            'duration': track_info.get('duration', 0)
        })
        if os.path.exists(filepath):
            os.remove(filepath)
        # Pre-download next song in queue
        asyncio.create_task(predownload_next(user_id))
        await query.answer("Playing next track.")
    elif data == "queue_view":
        # Show the queue
        await queue_command(query, context)
        await query.answer()
    elif data.startswith("queue_play::"):
        idx = int(data.split("::")[1])
        if idx < 0 or idx >= len(queue):
            await query.answer("Invalid track.")
            return
        track = queue[idx]
        url = track.get('url')
        from utils.ytdl_wrapper import get_video_info
        loop = asyncio.get_event_loop()
        track_info = await loop.run_in_executor(None, get_video_info, url)
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_VOICE)
        filepath = await loop.run_in_executor(None, download_audio_stream, url, user_id)
        with open(filepath, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=audio_file,
                title=track_info.get('title', 'Unknown'),
                duration=track_info.get('duration'),
                reply_markup=build_now_playing_keyboard(user_id)
            )
        storage_manager.record_play(user_id, {
            'title': track_info.get('title', 'Unknown'),
            'url': url,
            'duration': track_info.get('duration', 0)
        })
        if os.path.exists(filepath):
            os.remove(filepath)
        # Pre-download next song in queue
        asyncio.create_task(predownload_next(user_id))
        await query.answer(f"Playing: {track_info.get('title', 'Unknown')}")
    else:
        await query.answer("Unknown action.")


# --- Playlist Management Commands ---

async def add_to_playlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /addtoplaylist <playlist_name>")
        return
    playlist_name = context.args[0]
    history = storage_manager.get_history(user_id, limit=1)
    if not history:
        await update.message.reply_text("No recently played song to add.")
        return
    track = history[0]
    playlist_manager.add_to_named_playlist(user_id, playlist_name, track)
    await update.message.reply_text(f"Added to playlist '{playlist_name}': {track['title']}")

async def my_playlists_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    playlists = playlist_manager.list_named_playlists(user_id)
    if not playlists:
        await update.message.reply_text("You have no playlists yet. Use /addtoplaylist <name> to create one.")
        return
    keyboard = [[InlineKeyboardButton(name, callback_data=f"show_playlist::{name}")] for name in playlists]
    await update.message.reply_text("Your playlists:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_playlist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    playlist_name = query.data.split("::", 1)[1]
    tracks = playlist_manager.get_named_playlist(user_id, playlist_name)
    if not tracks:
        await query.answer("Playlist is empty.")
        return
    lines = []
    keyboard = []
    for idx, track in enumerate(tracks, 1):
        title = track.get('title', 'Unknown')
        duration = int(track.get('duration', 0) or 0)
        mins, secs = divmod(duration, 60)
        button_text = f"{title[:40]} ({mins:02d}:{secs:02d})"
        callback_data = f"playlist_play::{playlist_name}::{idx-1}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        lines.append(f"{idx}. {title} ({mins:02d}:{secs:02d})")
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(f"Playlist: {playlist_name}", reply_markup=reply_markup)
    await query.answer()

async def playlist_play_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    _, playlist_name, idx = query.data.split("::")
    idx = int(idx)
    tracks = playlist_manager.get_named_playlist(user_id, playlist_name)
    if idx < 0 or idx >= len(tracks):
        await query.answer("Invalid track.")
        return
    track = tracks[idx]
    url = track.get('url')
    from utils.ytdl_wrapper import get_video_info, download_audio_stream
    loop = asyncio.get_event_loop()
    track_info = await loop.run_in_executor(None, get_video_info, url)
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_VOICE)
    filepath = await loop.run_in_executor(None, download_audio_stream, url, user_id)
    with open(filepath, 'rb') as audio_file:
        await context.bot.send_audio(
            chat_id=query.message.chat_id,
            audio=audio_file,
            title=track_info.get('title', 'Unknown'),
            duration=track_info.get('duration'),
            reply_markup=build_now_playing_keyboard(user_id)
        )
    storage_manager.record_play(user_id, {
        'title': track_info.get('title', 'Unknown'),
        'url': url,
        'duration': track_info.get('duration', 0)
    })
    if os.path.exists(filepath):
        os.remove(filepath)
    asyncio.create_task(predownload_next(user_id))
    await query.answer(f"Playing: {track_info.get('title', 'Unknown')}")

async def remove_from_playlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /removefrom <playlist_name> <index>")
        return
    playlist_name = context.args[0]
    try:
        idx = int(context.args[1]) - 1
    except ValueError:
        await update.message.reply_text("Index must be a number.")
        return
    success = playlist_manager.remove_from_named_playlist(user_id, playlist_name, idx)
    if success:
        await update.message.reply_text(f"Removed track {idx+1} from playlist '{playlist_name}'.")
    else:
        await update.message.reply_text("Failed to remove track. Check playlist name and index.")

# Add inline 'Add to Playlist' button to now-playing messages
async def add_to_playlist_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    # Get last played song from history
    history = storage_manager.get_history(user_id, limit=1)
    if not history:
        await query.answer("No recently played song to add.")
        return
    track = history[0]
    # Ask user for playlist name
    await query.message.reply_text("Reply with /addtoplaylist <playlist_name> to add this song to a playlist.")
    await query.answer("Use /addtoplaylist <playlist_name>.")

def main():
    """Start the bot."""
    # Clean up old downloads on startup
    cleanup_old_downloads()
    
    # Create the Application
    application = ApplicationBuilder().token(os.getenv('TELEGRAM_TOKEN')).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("next", next_command))
    application.add_handler(CommandHandler("queue", queue_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("addtoplaylist", add_to_playlist_command))
    application.add_handler(CommandHandler("myplaylists", my_playlists_command))
    application.add_handler(CommandHandler("removefrom", remove_from_playlist_command))
    
    # Register callback handlers
    application.add_handler(CallbackQueryHandler(play_callback, pattern="^play::"))
    application.add_handler(CallbackQueryHandler(playback_callback, pattern="^prev$|^pause$|^resume$|^next$|^stop$"))
    
    # Register fallback handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))
    
    # Start the bot
    application.run_polling()


if __name__ == '__main__':
    main()
