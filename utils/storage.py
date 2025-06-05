"""
Listening history storage and management.
Handles recording and retrieving user play history with JSON persistence.
"""

import json
import os
from datetime import datetime
from typing import Dict, List

# TODO: Add unit tests


class StorageManager:
    """Manages user listening history with JSON persistence."""
    
    def __init__(self):
        """Initialize storage manager and ensure data directory exists."""
        self.data_dir = "data"
        self.history_file = os.path.join(self.data_dir, "history.json")
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load or create history file
        if not os.path.exists(self.history_file):
            with open(self.history_file, 'w') as f:
                json.dump({}, f, indent=2)
        
        # Load history into memory
        self._load_history()
    
    def _load_history(self) -> None:
        """Load history from JSON file into memory."""
        try:
            with open(self.history_file, 'r') as f:
                self.history = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            self.history = {}
    
    def _save_history(self) -> None:
        """Save history from memory to JSON file."""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            raise Exception(f"Failed to save history: {str(e)}")
    
    def record_play(self, user_id: int, track_info: Dict) -> None:
        """
        Record a track play in the user's history.
        
        Args:
            user_id: User ID
            track_info: Dictionary with track information (title, url, duration)
        """
        user_key = str(user_id)
        
        # Create history entry
        history_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'title': track_info.get('title', 'Unknown'),
            'url': track_info.get('url', ''),
            'duration': track_info.get('duration', 0)
        }
        
        # Initialize user history if it doesn't exist
        if user_key not in self.history:
            self.history[user_key] = []
        
        # Add new entry to the beginning of the list (most recent first)
        self.history[user_key].insert(0, history_entry)
        
        # Keep only the last 100 entries
        if len(self.history[user_key]) > 100:
            self.history[user_key] = self.history[user_key][:100]
        
        self._save_history()
    
    def get_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """
        Get the user's listening history.
        
        Args:
            user_id: User ID
            limit: Maximum number of entries to return
            
        Returns:
            List of history entries (most recent first)
        """
        user_key = str(user_id)
        user_history = self.history.get(user_key, [])
        
        # Return the most recent entries up to the limit
        return user_history[:limit]
