# -*- coding: utf-8 -*-
"""Tests for Redis client connection handling"""

import pytest
from unittest.mock import patch, MagicMock
import redis

from src.runtime.stores.redis_client import RedisClient, get_redis_client


class TestRedisClientConnectionHandling:
    """Test Redis connection error handling and log-once behavior"""

    def setup_method(self):
        """Reset singleton state before each test"""
        RedisClient._instance = None
        RedisClient._pool = None
        RedisClient._connection_logged = False

    def test_is_available_returns_true_when_pool_exists(self):
        """is_available() returns True when connection pool is created"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            assert client.is_available() is True

    def test_is_available_returns_false_on_connection_error(self):
        """is_available() returns False when ConnectionPool raises ConnectionError"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            with patch("src.runtime.stores.redis_client.ConnectionPool") as mock_pool:
                mock_pool.side_effect = redis.ConnectionError("Connection refused")
                client = RedisClient()
                assert client.is_available() is False
                assert client._pool is None

    def test_ping_returns_false_when_pool_is_none(self):
        """ping() returns False immediately when pool was not created"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            with patch("src.runtime.stores.redis_client.ConnectionPool") as mock_pool:
                mock_pool.side_effect = redis.ConnectionError("Connection refused")
                client = RedisClient()
                result = client.ping()
                assert result is False

    def test_ping_caches_result_in_connected_attribute(self):
        """ping() caches connection status in _connected attribute"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.ping.return_value = True
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.ping()
                assert result is True
                assert client._connected is True

    def test_ping_caches_false_on_connection_error(self):
        """ping() caches False in _connected when connection fails"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.ping.side_effect = redis.ConnectionError("Timeout")
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.ping()
                assert result is False
                assert client._connected is False

    def test_connection_error_logged_once_only(self, caplog):
        """Connection error is logged only once across all instances"""
        import logging
        caplog.set_level(logging.ERROR)
        
        # First instance - should log
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            with patch("src.runtime.stores.redis_client.ConnectionPool") as mock_pool:
                mock_pool.side_effect = redis.ConnectionError("Connection refused")
                client1 = RedisClient()
                _ = client1.ping()
        
        # Reset instance but not class attribute
        RedisClient._instance = None
        
        # Second instance - should NOT log again
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            with patch("src.runtime.stores.redis_client.ConnectionPool") as mock_pool:
                mock_pool.side_effect = redis.ConnectionError("Connection refused")
                client2 = RedisClient()
                _ = client2.ping()
        
        # Count how many times the error was logged
        # __init__ logs "Redis connection failed" when pool creation fails
        # ping() returns early when pool is None, so no duplicate log
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_logs) == 1
        assert "Redis connection failed" in error_logs[0].message

    def test_get_redis_client_returns_singleton(self):
        """get_redis_client() returns the same instance"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client1 = get_redis_client()
            client2 = get_redis_client()
            assert client1 is client2
