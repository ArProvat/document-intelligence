from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    created_at: datetime
    document_ids: List[str] = field(default_factory=list)


class InMemorySessionStore:
    def __init__(self):
        self._sessions: Dict[str, SessionRecord] = {}

    def create_session(self, user_id: str) -> SessionRecord:
        session = SessionRecord(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return self._sessions.get(session_id)

    def add_document(self, session_id: str, doc_id: str) -> None:
        session = self.get_session(session_id)
        if not session:
            raise ValueError("Session not found")
        session.document_ids.append(doc_id)