import logging
import redis

logger = logging.getLogger("agentops.memory.redis")

class EpisodicMemoryCache:
    """
    Episodic memory adapter wrapping standard Redis caching systems.
    Responsible for short-term working state, task logs, and context window sliding buffers.
    """
    def __init__(self, connection_url: str):
        self.connection_url = connection_url
        self._client = None
        logger.info(f"Redis adapter initialized referencing URL: {connection_url}")

    def connect(self):
        """
        Establishes lazy connection to local or cloud Redis instance.
        """
        try:
            self._client = redis.from_url(self.connection_url, decode_responses=True)
            # Send ping to confirm connection
            self._client.ping()
            logger.info("Connected successfully to Redis server instance.")
        except redis.RedisError as e:
            logger.error(f"Failed to connect to Redis cache socket: {e}")
            raise

    def store_episode(self, session_id: str, episode_key: str, data: str, ttl_seconds: int = 3600):
        """
        Caches a specific episodic block under the active session layout.
        """
        if not self._client:
            self.connect()
        
        composite_key = f"agentops:session:{session_id}:episode:{episode_key}"
        try:
            self._client.set(composite_key, data, ex=ttl_seconds)
            logger.debug(f"Cached session episodic key: {composite_key} (TTL: {ttl_seconds}s)")
        except redis.RedisError as e:
            logger.error(f"Failed to cache episodic token {composite_key}: {e}")

    def retrieve_episode(self, session_id: str, episode_key: str) -> str:
        """
        Recalls cache information for the active micro-agent.
        """
        if not self._client:
            self.connect()
            
        composite_key = f"agentops:session:{session_id}:episode:{episode_key}"
        try:
            return self._client.get(composite_key)
        except redis.RedisError as e:
            logger.error(f"Failed to recall episodic token {composite_key}: {e}")
            return None
            
    def clear_session(self, session_id: str):
        """
        Evicts all cached keys associated with the target session.
        """
        if not self._client:
            self.connect()
            
        pattern = f"agentops:session:{session_id}:*"
        try:
            keys = self._client.keys(pattern)
            if keys:
                self._client.delete(*keys)
                logger.info(f"Successfully evicted {len(keys)} episodic keys for session {session_id}.")
        except redis.RedisError as e:
            logger.error(f"Failed to purge cached keys for pattern {pattern}: {e}")
