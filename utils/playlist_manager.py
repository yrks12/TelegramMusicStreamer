"""
Queue management for user playlists.
Handles enqueueing, dequeueing, and persistence of user queues.
"""

import json
import os
from typing import Dict, List, Optional

# TODO: Add unit tests


class PlaylistManager:
    """Manages user queues with JSON persistence."""
    
    def __init__(self):
        """Initialize playlist manager and ensure data directory exists."""
        self.data_dir = "data"
        self.playlists_file = os.path.join(self.data_dir, "playlists.json")
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load or create playlists file
        if not os.path.exists(self.playlists_file):
            with open(self.playlists_file, 'w') as f:
                json.dump({}, f, indent=2)
        
        # Load playlists into memory
        self._load_playlists()
    
    def _load_playlists(self) -> None:
        """Load playlists from JSON file into memory."""
        try:
            with open(self.playlists_file, 'r') as f:
                self.playlists = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            self.playlists = {}
    
    def _save_playlists(self) -> None:
        """Save playlists from memory to JSON file."""
        try:
            with open(self.playlists_file, 'w') as f:
                json.dump(self.playlists, f, indent=2)
        except Exception as e:
            raise Exception(f"Failed to save playlists: {str(e)}")
    
    def enqueue(self, user_id: int, track_info: Dict) -> None:
        """
        Add a track to the user's queue.
        
        Args:
            user_id: User ID
            track_info: Dictionary with track information (id, title, url, duration)
        """
        user_key = str(user_id)
        
        if user_key not in self.playlists:
            self.playlists[user_key] = []
        
        self.playlists[user_key].append(track_info)
        self._save_playlists()
    
    def dequeue(self, user_id: int) -> Optional[Dict]:
        """
        Remove and return the first track from the user's queue.
        
        Args:
            user_id: User ID
            
        Returns:
            Track dictionary or None if queue is empty
        """
        user_key = str(user_id)
        
        if user_key not in self.playlists or not self.playlists[user_key]:
            return None
        
        track = self.playlists[user_key].pop(0)
        self._save_playlists()
        return track
    
    def peek(self, user_id: int) -> Optional[Dict]:
        """
        Return the first track from the user's queue without removing it.
        
        Args:
            user_id: User ID
            
        Returns:
            Track dictionary or None if queue is empty
        """
        user_key = str(user_id)
        
        if user_key not in self.playlists or not self.playlists[user_key]:
            return None
        
        return self.playlists[user_key][0]
    
    def clear(self, user_id: int) -> None:
        """
        Clear all tracks from the user's queue.
        
        Args:
            user_id: User ID
        """
        user_key = str(user_id)
        
        if user_key in self.playlists:
            self.playlists[user_key] = []
            self._save_playlists()
    
    def list_queue(self, user_id: int) -> List[Dict]:
        """
        Get the entire queue for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of track dictionaries
        """
        user_key = str(user_id)
        return self.playlists.get(user_key, [])
