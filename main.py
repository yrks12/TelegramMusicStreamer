"""
Telegram YouTube Music Bot
A personal bot for searching, playing, and managing YouTube music.
"""

import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaAudio
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ChatAction

from utils.ytdl_wrapper import search_youtube, download_audio_stream, extract_playlist_videos
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

# Initialize utility managers
playlist_manager = PlaylistManager()
storage_manager = StorageManager()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - send welcome message with available commands."""
    welcome_text = """
🎵 **YouTube Music Bot** 🎵

Welcome! I'm your personal YouTube music assistant. Here are the available commands:

🔍 `/search <keywords>` - Search for music on YouTube
▶️ `/play <YouTube URL or ID>` - Play a specific track or playlist
⏭️ `/next` or `/queue` - Play next track from your queue
📜 `/history` - View your recent listening history

Just send me a command to get started! 🎶
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')


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
            
            # Truncate title to 40 characters
            title = result['title'][:40] + "..." if len(result['title']) > 40 else result['title']
            button_text = f"{title} {duration_str}"
            
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
    # For previous, you could keep a history stack, but for now, just show Next and View Queue
    buttons.append(InlineKeyboardButton("📜 View Queue", callback_data="queue_view"))
    return InlineKeyboardMarkup([buttons])


async def play_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback query for play buttons."""
    query = update.callback_query
    await query.answer()
    url = query.data.split("::", 1)[1]
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # Get video info for queue
    from utils.ytdl_wrapper import get_video_info
    loop = asyncio.get_event_loop()
    track_info = await loop.run_in_executor(None, get_video_info, url)
    # Always enqueue before playing
    playlist_manager.enqueue(user_id, {
        'id': track_info.get('id'),
        'title': track_info.get('title'),
        'url': url,
        'duration': track_info.get('duration')
    })

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
    filepath = await loop.run_in_executor(None, download_audio_stream, url, user_id)
    with open(filepath, 'rb') as audio_file:
        await context.bot.send_audio(
            chat_id=chat_id,
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


async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /play command - play single video or enqueue playlist."""
    if not context.args:
        await update.message.reply_text("Usage: /play <YouTube URL or ID>")
        return
    url = context.args[0]
    user_id = update.effective_user.id
    if 'playlist?list=' in url or '&list=' in url:
        await update.message.reply_text("Enqueuing playlist, please wait...")
        loop = asyncio.get_event_loop()
        videos = await loop.run_in_executor(None, extract_playlist_videos, url)
        for video in videos:
            playlist_manager.enqueue(user_id, video)
        await update.message.reply_text(f"Enqueued {len(videos)} tracks from the playlist.")
        return
    # Single video: enqueue and play
    from utils.ytdl_wrapper import get_video_info
    loop = asyncio.get_event_loop()
    track_info = await loop.run_in_executor(None, get_video_info, url)
    playlist_manager.enqueue(user_id, {
        'id': track_info.get('id'),
        'title': track_info.get('title'),
        'url': url,
        'duration': track_info.get('duration')
    })
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)
    filepath = await loop.run_in_executor(None, download_audio_stream, url, user_id)
    with open(filepath, 'rb') as audio_file:
        await update.message.reply_audio(
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


async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /next and /queue commands - play next track from queue."""
    user_id = update.effective_user.id
    
    # Get next track from queue
    next_track = playlist_manager.dequeue(user_id)
    
    if next_track is None:
        await update.message.reply_text("Your queue is empty. Use /search to add something.")
        return
    
    try:
        # Send upload audio action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)
        
        # Download and send next track
        url = next_track.get('url') or f"https://youtube.com/watch?v={next_track['id']}"
        loop = asyncio.get_event_loop()
        filepath = await loop.run_in_executor(None, download_audio_stream, url, user_id)
        
        # Send audio file
        with open(filepath, 'rb') as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                title=next_track.get('title', 'Unknown'),
                duration=next_track.get('duration')
            )
            
            # Record in history
            storage_manager.record_play(user_id, {
                'title': next_track.get('title', 'Unknown'),
                'url': url,
                'duration': next_track.get('duration', 0)
            })
        
        # Clean up temporary file
        if os.path.exists(filepath):
            os.remove(filepath)
            
    except Exception as e:
        logger.error(f"Next command error: {e}")
        await update.message.reply_text(f"❌ Failed to play next track: {str(e)}")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history command - show recent listening history."""
    user_id = update.effective_user.id
    
    history = storage_manager.get_history(user_id, limit=10)
    
    if not history:
        await update.message.reply_text("No history yet. Use /play or /search to start listening.")
        return
    
    # Build history list
    history_text = "🎵 **Recent Listening History** 🎵\n\n"
    
    for i, entry in enumerate(history, 1):
        # Format timestamp (truncate to YYYY-MM-DDTHH:MM)
        timestamp = entry['timestamp'][:16]  # Keep only YYYY-MM-DDTHH:MM
        title = entry['title']
        url = entry['url']
        
        history_text += f"{i}. [{timestamp}] {title}\n{url}\n\n"
    
    await update.message.reply_text(history_text, parse_mode='Markdown')


async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized messages."""
    await update.message.reply_text("Use /search or /play to interact with the bot.")


def cleanup_old_downloads():
    """Clean up old download files on startup (optional but recommended)."""
    # TODO: Implement cleanup of files older than 1 hour
    downloads_dir = "downloads"
    if os.path.exists(downloads_dir):
        logger.info("Download folder exists - consider implementing cleanup logic")


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if hasattr(update, 'effective_user') and update.effective_user:
        user_id = update.effective_user.id
    else:
        user_id = update.from_user.id
    queue = playlist_manager.list_queue(user_id)
    if not queue:
        await update.message.reply_text("Your queue is empty. Use /search or /play to add songs.")
        return
    lines = []
    keyboard = []
    for idx, track in enumerate(queue, 1):
        title = track.get('title', 'Unknown')
        duration = int(track.get('duration', 0) or 0)
        mins, secs = divmod(duration, 60)
        button_text = f"{title[:40]} ({mins:02d}:{secs:02d})"
        callback_data = f"queue_play::{idx-1}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        lines.append(f"{idx}. {title} ({mins:02d}:{secs:02d})")
    reply_markup = InlineKeyboardMarkup(keyboard)
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text("Your queue:", reply_markup=reply_markup)
    else:
        await update.edit_message_text("Your queue:", reply_markup=reply_markup)


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
        await query.answer(f"Playing: {track_info.get('title', 'Unknown')}")
    else:
        await query.answer("Unknown action.")


def main():
    """Initialize and run the bot."""
    # Get bot token from environment
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable is required")
    
    # Create downloads directory if it doesn't exist
    os.makedirs("downloads", exist_ok=True)
    
    # Optional: Clean up old files on startup
    cleanup_old_downloads()
    
    # Build application
    app = ApplicationBuilder().token(token).build()
    
    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("play", play_command))
    app.add_handler(CommandHandler("next", next_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("history", history_command))
    
    # Register callback handler for play buttons
    app.add_handler(CallbackQueryHandler(play_callback, pattern="^play::"))
    app.add_handler(CallbackQueryHandler(queue_callback, pattern=r"^queue_"))
    
    # Register fallback handler for unrecognized messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))
    
    # Start polling
    print("Bot is polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
