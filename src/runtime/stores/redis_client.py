# -*- coding: utf-8 -*-
"""Redis client management module

Provides Redis connection pool management and basic operations.
"""

import logging
import os
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

import redis
from redis import Redis, ConnectionPool

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis client wrapper with connection pool management"""
    
    _instance: Optional["RedisClient"] = None
    _pool: Optional[ConnectionPool] = None
    _connection_logged: bool = False
    
    def __new__(cls) -> "RedisClient":
        """Singleton pattern for Redis client"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize Redis client with connection pool"""
        if self._initialized:
            return
        
        self._connected = False
        
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        db = int(os.environ.get("REDIS_DB", "0"))
        password = os.environ.get("REDIS_PASSWORD") or None
        socket_timeout = float(os.environ.get("REDIS_SOCKET_TIMEOUT", "5"))
        socket_connect_timeout = float(os.environ.get("REDIS_CONNECTION_TIMEOUT", "5"))
        self._prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")

        try:
            self._pool = ConnectionPool(
                host=host,
                port=port,
                db=db,
                password=password,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
                decode_responses=True,
                max_connections=50,
            )
            logger.info(f"Redis client initialized: {host}:{port}/{db}")
        except redis.ConnectionError:
            self._pool = None
            if not self._connection_logged:
                logger.error(f"Redis connection failed: {host}:{port}/{db}")
                self.__class__._connection_logged = True

        self._initialized = True
    
    @property
    def client(self) -> Redis:
        """Get Redis client instance"""
        return Redis(connection_pool=self._pool)
    
    def _key(self, key: str) -> str:
        """Add prefix to key"""
        return f"{self._prefix}{key}"
    
    # ============ Basic Operations ============
    
    def is_available(self) -> bool:
        """Check if Redis connection is available
        
        Returns:
            bool: True if pool exists and connection is ready
        """
        return self._pool is not None
    
    def ping(self) -> bool:
        """Check Redis connection and cache result
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if self._pool is None:
            return False
        
        try:
            result = self.client.ping()
            self._connected = result
            return result
        except redis.ConnectionError as e:
            self._connected = False
            if not self._connection_logged:
                logger.error(f"Redis connection error: {e}")
                self.__class__._connection_logged = True
            return False
    
    def get(self, key: str) -> Optional[str]:
        """Get string value"""
        return self.client.get(self._key(key))
    
    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set string value with optional expiration"""
        return self.client.set(self._key(key), value, ex=ex)
    
    def delete(self, *keys: str) -> int:
        """Delete keys"""
        if not keys:
            return 0
        return self.client.delete(*[self._key(k) for k in keys])
    
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        return self.client.exists(self._key(key)) > 0
    
    # ============ Hash Operations ============
    
    def hset(self, name: str, mapping: Dict[str, str]) -> int:
        """Set hash fields"""
        if not mapping:
            return 0
        return self.client.hset(self._key(name), mapping=mapping)
    
    def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field value"""
        return self.client.hget(self._key(name), key)
    
    def hgetall(self, name: str) -> Dict[str, str]:
        """Get all hash fields"""
        return self.client.hgetall(self._key(name))
    
    def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields"""
        if not keys:
            return 0
        return self.client.hdel(self._key(name), *keys)
    
    def hexists(self, name: str, key: str) -> bool:
        """Check if hash field exists"""
        return self.client.hexists(self._key(name), key)
    
    # ============ List Operations ============
    
    def lpush(self, name: str, *values: str) -> int:
        """Push values to list head"""
        if not values:
            return 0
        return self.client.lpush(self._key(name), *values)
    
    def rpush(self, name: str, *values: str) -> int:
        """Push values to list tail"""
        if not values:
            return 0
        return self.client.rpush(self._key(name), *values)
    
    def lpop(self, name: str) -> Optional[str]:
        """Pop from list head"""
        return self.client.lpop(self._key(name))
    
    def rpop(self, name: str) -> Optional[str]:
        """Pop from list tail"""
        return self.client.rpop(self._key(name))
    
    def lrange(self, name: str, start: int, end: int) -> List[str]:
        """Get list range"""
        return self.client.lrange(self._key(name), start, end)
    
    def llen(self, name: str) -> int:
        """Get list length"""
        return self.client.llen(self._key(name))
    
    def lrem(self, name: str, count: int, value: str) -> int:
        """Remove elements from list"""
        return self.client.lrem(self._key(name), count, value)
    
    def lset(self, name: str, index: int, value: str) -> bool:
        """Set value at index in list"""
        return self.client.lset(self._key(name), index, value)
    
    def ltrim(self, name: str, start: int, end: int) -> bool:
        """Trim list to specified range"""
        return self.client.ltrim(self._key(name), start, end)
    
    # ============ Set Operations ============
    
    def sadd(self, name: str, *values: str) -> int:
        """Add members to set"""
        if not values:
            return 0
        return self.client.sadd(self._key(name), *values)
    
    def srem(self, name: str, *values: str) -> int:
        """Remove members from set"""
        if not values:
            return 0
        return self.client.srem(self._key(name), *values)
    
    def smembers(self, name: str) -> set:
        """Get all set members"""
        return self.client.smembers(self._key(name))
    
    def sismember(self, name: str, value: str) -> bool:
        """Check if value is member of set"""
        return self.client.sismember(self._key(name), value)
    
    def scard(self, name: str) -> int:
        """Get set cardinality"""
        return self.client.scard(self._key(name))
    
    # ============ Sorted Set Operations ============
    
    def zadd(self, name: str, mapping: Dict[str, float]) -> int:
        """Add members to sorted set with scores"""
        if not mapping:
            return 0
        return self.client.zadd(self._key(name), mapping)
    
    def zrem(self, name: str, *values: str) -> int:
        """Remove members from sorted set"""
        if not values:
            return 0
        return self.client.zrem(self._key(name), *values)
    
    def zrange(self, name: str, start: int, end: int, withscores: bool = False) -> List:
        """Get sorted set range by index"""
        return self.client.zrange(self._key(name), start, end, withscores=withscores)
    
    def zrevrange(self, name: str, start: int, end: int, withscores: bool = False) -> List:
        """Get sorted set range by index in reverse order (highest to lowest score)"""
        return self.client.zrevrange(self._key(name), start, end, withscores=withscores)
    
    def zrangebyscore(self, name: str, min_score: float, max_score: float, 
                      start: Optional[int] = None, num: Optional[int] = None,
                      withscores: bool = False) -> List:
        """Get sorted set range by score"""
        return self.client.zrangebyscore(
            self._key(name), min_score, max_score,
            start=start, num=num, withscores=withscores
        )
    
    def zcard(self, name: str) -> int:
        """Get sorted set cardinality"""
        return self.client.zcard(self._key(name))
    
    def zscore(self, name: str, value: str) -> Optional[float]:
        """Get score of member in sorted set"""
        return self.client.zscore(self._key(name), value)
    
    # ============ Transaction Operations ============
    
    @contextmanager
    def pipeline(self, transaction: bool = True):
        """Get pipeline for batch operations"""
        pipe = self.client.pipeline(transaction=transaction)
        try:
            yield _PipelineWrapper(pipe, self._prefix)
            pipe.execute()
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            raise
    
    def execute_script(self, script: str, keys: List[str], args: List[str]) -> Any:
        """Execute Lua script"""
        prefixed_keys = [self._key(k) for k in keys]
        return self.client.eval(script, len(prefixed_keys), *prefixed_keys, *args)
    
    # ============ Key Pattern Operations ============
    
    def keys(self, pattern: str) -> List[str]:
        """Get keys matching pattern"""
        full_pattern = self._key(pattern)
        keys = self.client.keys(full_pattern)
        # Remove prefix from returned keys
        prefix_len = len(self._prefix)
        return [k[prefix_len:] for k in keys]
    
    def scan_iter(self, match: str, count: int = 100):
        """Iterate over keys matching pattern"""
        full_pattern = self._key(match)
        prefix_len = len(self._prefix)
        for key in self.client.scan_iter(match=full_pattern, count=count):
            yield key[prefix_len:]
    
    # ============ Lifecycle ============
    
    def close(self):
        """Close connection pool"""
        if self._pool:
            self._pool.disconnect()
            logger.info("Redis connection pool closed")
    
    def __del__(self):
        """Cleanup on destruction"""
        self.close()


class _PipelineWrapper:
    """Wrapper for Redis pipeline with key prefix support"""
    
    def __init__(self, pipe, prefix: str):
        self._pipe = pipe
        self._prefix = prefix
    
    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"
    
    def hset(self, name: str, mapping: Dict[str, str]):
        return self._pipe.hset(self._key(name), mapping=mapping)
    
    def delete(self, *keys: str):
        return self._pipe.delete(*[self._key(k) for k in keys])
    
    def sadd(self, name: str, *values: str):
        return self._pipe.sadd(self._key(name), *values)
    
    def srem(self, name: str, *values: str):
        return self._pipe.srem(self._key(name), *values)
    
    def lpush(self, name: str, *values: str):
        return self._pipe.lpush(self._key(name), *values)
    
    def rpush(self, name: str, *values: str):
        return self._pipe.rpush(self._key(name), *values)
    
    def lrem(self, name: str, count: int, value: str):
        return self._pipe.lrem(self._key(name), count, value)
    
    def zadd(self, name: str, mapping: Dict[str, float]):
        return self._pipe.zadd(self._key(name), mapping)
    
    def zrem(self, name: str, *values: str):
        return self._pipe.zrem(self._key(name), *values)


# Global Redis client instance
def get_redis_client() -> RedisClient:
    """Get global Redis client instance"""
    return RedisClient()
