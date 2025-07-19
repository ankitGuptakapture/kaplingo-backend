import asyncio
import time
from typing import Dict, Optional, Set
from dataclasses import dataclass
from enum import Enum
from loguru import logger

class RoomStatus(Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    CLOSED = "closed"

class UserLanguage(Enum):
    ENGLISH = "en"
    HINDI = "hi"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"
    CHINESE = "zh"
    JAPANESE = "ja"
    ARABIC = "ar"
    AUTO_DETECT = "auto"

@dataclass
class User:
    user_id: str
    connection_id: str
    preferred_language: UserLanguage
    room_id: Optional[str] = None
    joined_at: float = None
    is_speaking: bool = False
    
    def __post_init__(self):
        if self.joined_at is None:
            self.joined_at = time.time()

@dataclass
class TranslationRoom:
    room_id: str
    created_at: float
    status: RoomStatus = RoomStatus.WAITING
    users: Dict[str, User] = None
    max_users: int = 2
    
    def __post_init__(self):
        if self.users is None:
            self.users = {}
    
    @property
    def is_full(self) -> bool:
        return len(self.users) >= self.max_users
    
    @property
    def is_ready(self) -> bool:
        return len(self.users) == self.max_users
    
    def get_partner(self, user_id: str) -> Optional[User]:
        """Get the translation partner for a given user"""
        for uid, user in self.users.items():
            if uid != user_id:
                return user
        return None
    
    def get_language_pair(self) -> tuple:
        """Get the language pair for this room"""
        languages = [user.preferred_language for user in self.users.values()]
        return tuple(languages) if len(languages) == 2 else (None, None)

class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, TranslationRoom] = {}
        self.users: Dict[str, User] = {}
        self.user_to_room: Dict[str, str] = {}
        self.waiting_queue: Dict[UserLanguage, Set[str]] = {}
        self._room_counter = 0
    
    def _generate_room_id(self) -> str:
        """Generate a unique room ID"""
        self._room_counter += 1
        return f"room_{int(time.time())}_{self._room_counter}"
    
    async def add_user(self, user_id: str, connection_id: str, preferred_language: UserLanguage) -> Optional[str]:
        """Add a user and try to match them with another user"""
        user = User(
            user_id=user_id,
            connection_id=connection_id,
            preferred_language=preferred_language
        )
        
        self.users[user_id] = user
        
        # Try to find a waiting partner
        partner_user_id = self._find_waiting_partner(user)
        
        if partner_user_id:
            # Create room with matched users
            room_id = self._generate_room_id()
            room = TranslationRoom(room_id=room_id, created_at=time.time())
            
            # Add both users to room
            partner = self.users[partner_user_id]
            room.users[user_id] = user
            room.users[partner_user_id] = partner
            room.status = RoomStatus.ACTIVE
            
            # Update user room assignments
            user.room_id = room_id
            partner.room_id = room_id
            self.user_to_room[user_id] = room_id
            self.user_to_room[partner_user_id] = room_id
            
            # Remove partner from waiting queue
            self._remove_from_waiting_queue(partner_user_id)
            
            self.rooms[room_id] = room
            
            logger.info(f"Created room {room_id} with users {user_id} ({user.preferred_language.value}) and {partner_user_id} ({partner.preferred_language.value})")
            return room_id
        else:
            # Add to waiting queue
            self._add_to_waiting_queue(user)
            logger.info(f"User {user_id} added to waiting queue for {preferred_language.value}")
            return None
    
    def _find_waiting_partner(self, user: User) -> Optional[str]:
        """Find a suitable waiting partner for the user"""
        user_lang = user.preferred_language
        
        # Look for users with different languages
        for lang, waiting_users in self.waiting_queue.items():
            if lang != user_lang and waiting_users:
                # Return the first waiting user with a different language
                return next(iter(waiting_users))
        
        # If no different language users, look for same language users
        # (they can practice with each other)
        if user_lang in self.waiting_queue and self.waiting_queue[user_lang]:
            waiting_users = self.waiting_queue[user_lang]
            if waiting_users:
                return next(iter(waiting_users))
        
        return None
    
    def _add_to_waiting_queue(self, user: User):
        """Add user to waiting queue"""
        if user.preferred_language not in self.waiting_queue:
            self.waiting_queue[user.preferred_language] = set()
        self.waiting_queue[user.preferred_language].add(user.user_id)
    
    def _remove_from_waiting_queue(self, user_id: str):
        """Remove user from waiting queue"""
        if user_id in self.users:
            user_lang = self.users[user_id].preferred_language
            if user_lang in self.waiting_queue:
                self.waiting_queue[user_lang].discard(user_id)
    
    async def remove_user(self, user_id: str) -> Optional[str]:
        """Remove user and handle room cleanup"""
        if user_id not in self.users:
            return None
            
        user = self.users[user_id]
        room_id = self.user_to_room.get(user_id)
        
        # Remove from waiting queue if present
        self._remove_from_waiting_queue(user_id)
        
        # Handle room cleanup
        if room_id and room_id in self.rooms:
            room = self.rooms[room_id]
            room.users.pop(user_id, None)
            
            # If room becomes empty, close it
            if not room.users:
                room.status = RoomStatus.CLOSED
                del self.rooms[room_id]
                logger.info(f"Closed empty room {room_id}")
            else:
                # Notify remaining user that partner left
                remaining_user_id = next(iter(room.users.keys()))
                logger.info(f"User {user_id} left room {room_id}, {remaining_user_id} remains")
        
        # Cleanup user data
        self.users.pop(user_id, None)
        self.user_to_room.pop(user_id, None)
        
        logger.info(f"Removed user {user_id}")
        return room_id
    
    def get_room(self, room_id: str) -> Optional[TranslationRoom]:
        """Get room by ID"""
        return self.rooms.get(room_id)
    
    def get_user_room(self, user_id: str) -> Optional[TranslationRoom]:
        """Get room for a specific user"""
        room_id = self.user_to_room.get(user_id)
        return self.rooms.get(room_id) if room_id else None
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return self.users.get(user_id)
    
    def get_translation_partner(self, user_id: str) -> Optional[User]:
        """Get the translation partner for a user"""
        room = self.get_user_room(user_id)
        return room.get_partner(user_id) if room else None
    
    def set_user_speaking_status(self, user_id: str, is_speaking: bool):
        """Update user's speaking status"""
        if user_id in self.users:
            self.users[user_id].is_speaking = is_speaking
    
    def get_waiting_stats(self) -> Dict:
        """Get statistics about waiting users"""
        stats = {}
        for lang, users in self.waiting_queue.items():
            stats[lang.value] = len(users)
        return stats
    
    def get_active_rooms_count(self) -> int:
        """Get number of active rooms"""
        return len([r for r in self.rooms.values() if r.status == RoomStatus.ACTIVE])

# Global room manager instance
room_manager = RoomManager()
