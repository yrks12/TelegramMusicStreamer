# Telegram YouTube Music Bot

A personal Telegram bot that lets you search, play, queue, and review history of YouTube audio tracks. This bot is designed for single-user personal use and provides a convenient way to interact with YouTube content through Telegram.

## Project Overview

This bot acts as your personal YouTube music client, allowing you to search for tracks, play individual videos or entire playlists, manage a playback queue, and track your listening history. All operations are performed through simple Telegram commands, making it easy to discover and enjoy music on the go.

## Setup Instructions

### Prerequisites
- Python 3.8 or higher
- ffmpeg installed on your system
- A Telegram bot token from [@BotFather](https://t.me/botfather)

### Installation Steps

1. **Clone or open the Replit project**
   - Fork this project or create a new Replit Python project
   - Upload all the project files to your Replit environment

2. **Create a Python virtual environment** 
   - Replit handles this automatically, but you can verify by checking the Python version

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install ffmpeg**
   - In Replit, use the Packages tab to search for and install "ffmpeg"
   - Alternatively, run in the shell: `apt-get update && apt-get install -y ffmpeg`
   - Verify installation: `ffmpeg -version`

5. **Configure environment variables**
   - Create a `.env` file in the root directory with:
     ```
     TELEGRAM_TOKEN=your_bot_token_here
     ```
   - Or use Replit Secrets to set `TELEGRAM_TOKEN`

6. **Run the bot**
   ```bash
   python main.py
   ```

## File Structure

- **main.py**: Bot initialization, handler registration, and polling loop
- **utils/ytdl_wrapper.py**: YouTube searching and audio downloading functionality
- **utils/playlist_manager.py**: JSON-backed queue management for user playlists
- **utils/storage.py**: JSON-backed listening history storage and retrieval
- **data/history.json**: Stores per-user play history (created automatically)
- **data/playlists.json**: Stores per-user queues (created automatically)
- **downloads/**: Runtime folder for temporary MP3 files (auto-generated)
- **requirements.txt**: Pinned dependencies for the project
- **README.md**: This documentation file

## Usage Instructions

The bot supports the following commands:

### `/start`
Displays a welcome message with all available commands and their descriptions.

### `/search <keywords>`
Search YouTube for music matching your keywords. Returns up to 5 results with an inline keyboard where you can select tracks to play immediately.

**Example**: `/search bohemian rhapsody queen`

### `/play <YouTube URL or ID>`
Play a specific YouTube video or enqueue an entire playlist:
- For single videos: Downloads and sends the audio immediately
- For playlists: Adds all tracks to your personal queue for later playback

**Examples**: 
- `/play https://youtube.com/watch?v=fJ9rUzIMcZQ`
- `/play https://youtube.com/playlist?list=PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG`

### `/next` or `/queue`
Play the next track from your personal queue. If the queue is empty, you'll be prompted to add tracks using `/search`.

### `/history`
View your last 10 played tracks with timestamps and YouTube links. Perfect for rediscovering music you enjoyed recently.

**Note**: This bot is designed for personal use, so all queues and history are tied to your Telegram user ID. No authentication beyond Telegram's built-in user identification is required.

## Technical Details

- **Audio Quality**: All downloads are converted to MP3 at 192kbps for optimal quality/size balance
- **Storage**: User queues and history are stored in JSON files, with automatic cleanup of temporary audio files
- **Concurrency**: All YouTube operations use async/await patterns to prevent blocking the bot
- **Error Handling**: Comprehensive error handling with user-friendly error messages

## Future Improvements

**TODO Items for Enhancement:**
- Add unit tests for utility modules
- Consider caching MP3s to avoid redownloading the same track
- Implement cleanup of old files on startup
- Add queue management commands (view queue, clear queue, remove specific tracks)
- Support for audio quality selection
- Integration with music streaming APIs for enhanced metadata

## Dependencies

The project uses these pinned versions for stability:
- `python-telegram-bot==22.1`
- `yt-dlp==2025.5.22` 
- `python-dotenv>=0.21.0`

## Troubleshooting

**Common Issues:**
1. **"ffmpeg not found"**: Ensure ffmpeg is installed and accessible in your PATH
2. **"No such file or directory"**: Check that all project files are uploaded correctly
3. **Bot not responding**: Verify your `TELEGRAM_TOKEN` is set correctly
4. **Download failures**: Some videos may be restricted - try different content

For any issues, check the console output for detailed error messages.
