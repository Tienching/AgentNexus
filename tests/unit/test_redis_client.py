# -*- coding: utf-8 -*-
"""Tests for Redis client connection handling and operations"""

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


class TestRedisClientSortedSetOperations:
    """Test sorted set operations: zadd, zrem, zrange, zrevrange"""

    def setup_method(self):
        """Reset singleton state before each test"""
        RedisClient._instance = None
        RedisClient._pool = None
        RedisClient._connection_logged = False

    def test_zadd_adds_members_with_scores(self):
        """zadd() adds members to sorted set with scores"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.zadd.return_value = 2
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zadd("myzset", {"member1": 1.0, "member2": 2.0})
                
                assert result == 2
                mock_redis.zadd.assert_called_once_with("aona:myzset", {"member1": 1.0, "member2": 2.0})

    def test_zadd_returns_zero_for_empty_mapping(self):
        """zadd() returns 0 when mapping is empty"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zadd("myzset", {})
                
                assert result == 0
                mock_redis.zadd.assert_not_called()

    def test_zrem_removes_members(self):
        """zrem() removes members from sorted set"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.zrem.return_value = 2
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zrem("myzset", "member1", "member2")
                
                assert result == 2
                mock_redis.zrem.assert_called_once_with("aona:myzset", "member1", "member2")

    def test_zrem_returns_zero_for_empty_values(self):
        """zrem() returns 0 when no values provided"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zrem("myzset")
                
                assert result == 0
                mock_redis.zrem.assert_not_called()

    def test_zrange_returns_members_in_score_order(self):
        """zrange() returns members sorted by score"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.zrange.return_value = ["member1", "member2", "member3"]
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zrange("myzset", 0, -1)
                
                assert result == ["member1", "member2", "member3"]
                mock_redis.zrange.assert_called_once_with("aona:myzset", 0, -1, withscores=False)

    def test_zrange_with_scores(self):
        """zrange() returns tuples when withscores=True"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.zrange.return_value = [("member1", 1.0), ("member2", 2.0)]
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zrange("myzset", 0, -1, withscores=True)
                
                assert result == [("member1", 1.0), ("member2", 2.0)]
                mock_redis.zrange.assert_called_once_with("aona:myzset", 0, -1, withscores=True)

    def test_zrevrange_returns_members_in_reverse_score_order(self):
        """zrevrange() returns members sorted by score in descending order"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.zrevrange.return_value = ["member3", "member2", "member1"]
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zrevrange("myzset", 0, -1)
                
                assert result == ["member3", "member2", "member1"]
                mock_redis.zrevrange.assert_called_once_with("aona:myzset", 0, -1, withscores=False)

    def test_zrevrange_with_scores(self):
        """zrevrange() returns tuples when withscores=True"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.zrevrange.return_value = [("member3", 3.0), ("member2", 2.0), ("member1", 1.0)]
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.zrevrange("myzset", 0, -1, withscores=True)
                
                assert result == [("member3", 3.0), ("member2", 2.0), ("member1", 1.0)]
                mock_redis.zrevrange.assert_called_once_with("aona:myzset", 0, -1, withscores=True)


class TestRedisClientSetOperations:
    """Test set operations: sadd, srem, smembers, sismember"""

    def setup_method(self):
        """Reset singleton state before each test"""
        RedisClient._instance = None
        RedisClient._pool = None
        RedisClient._connection_logged = False

    def test_sadd_adds_members_to_set(self):
        """sadd() adds members to set"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.sadd.return_value = 2
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.sadd("myset", "member1", "member2")
                
                assert result == 2
                mock_redis.sadd.assert_called_once_with("aona:myset", "member1", "member2")

    def test_sadd_returns_zero_for_empty_values(self):
        """sadd() returns 0 when no values provided"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.sadd("myset")
                
                assert result == 0
                mock_redis.sadd.assert_not_called()

    def test_srem_removes_members_from_set(self):
        """srem() removes members from set"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.srem.return_value = 1
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.srem("myset", "member1")
                
                assert result == 1
                mock_redis.srem.assert_called_once_with("aona:myset", "member1")

    def test_srem_returns_zero_for_empty_values(self):
        """srem() returns 0 when no values provided"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.srem("myset")
                
                assert result == 0
                mock_redis.srem.assert_not_called()

    def test_smembers_returns_all_members(self):
        """smembers() returns all set members"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.smembers.return_value = {"member1", "member2"}
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.smembers("myset")
                
                assert result == {"member1", "member2"}
                mock_redis.smembers.assert_called_once_with("aona:myset")

    def test_sismember_returns_true_when_member_exists(self):
        """sismember() returns True when value is member of set"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.sismember.return_value = True
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.sismember("myset", "member1")
                
                assert result is True
                mock_redis.sismember.assert_called_once_with("aona:myset", "member1")

    def test_sismember_returns_false_when_member_not_exists(self):
        """sismember() returns False when value is not member of set"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.sismember.return_value = False
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.sismember("myset", "nonexistent")
                
                assert result is False


class TestRedisClientScanIter:
    """Test scan_iter operation for key pattern matching"""

    def setup_method(self):
        """Reset singleton state before each test"""
        RedisClient._instance = None
        RedisClient._pool = None
        RedisClient._connection_logged = False

    def test_scan_iter_yields_matching_keys_with_prefix_stripped(self):
        """scan_iter() yields keys matching pattern with prefix stripped"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.scan_iter.return_value = iter([
                "aona:session:abc:msg:1",
                "aona:session:abc:msg:2",
                "aona:session:abc:msg:3",
            ])
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = list(client.scan_iter("session:abc:msg:*"))
                
                assert result == [
                    "session:abc:msg:1",
                    "session:abc:msg:2",
                    "session:abc:msg:3",
                ]
                mock_redis.scan_iter.assert_called_once_with(match="aona:session:abc:msg:*", count=100)

    def test_scan_iter_uses_custom_count(self):
        """scan_iter() passes count parameter to underlying client"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.scan_iter.return_value = iter([])
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                list(client.scan_iter("mykey:*", count=50))
                
                mock_redis.scan_iter.assert_called_once_with(match="aona:mykey:*", count=50)

    def test_scan_iter_returns_empty_for_no_matches(self):
        """scan_iter() returns empty list when no keys match"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.scan_iter.return_value = iter([])
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = list(client.scan_iter("nonexistent:*"))
                
                assert result == []


class TestRedisClientListOperations:
    """Test list operations: lset, ltrim"""

    def setup_method(self):
        """Reset singleton state before each test"""
        RedisClient._instance = None
        RedisClient._pool = None
        RedisClient._connection_logged = False

    def test_lset_updates_value_at_index(self):
        """lset() updates value at specific index in list"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.lset.return_value = True
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.lset("mylist", 0, "new_value")
                
                assert result is True
                mock_redis.lset.assert_called_once_with("aona:mylist", 0, "new_value")

    def test_lset_returns_false_for_invalid_index(self):
        """lset() raises exception when index out of range"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.lset.side_effect = redis.ResponseError("index out of range")
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                with pytest.raises(redis.ResponseError):
                    client.lset("mylist", 100, "value")

    def test_ltrim_keeps_specified_range(self):
        """ltrim() keeps only elements in specified range"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.ltrim.return_value = True
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.ltrim("mylist", 0, 99)
                
                assert result is True
                mock_redis.ltrim.assert_called_once_with("aona:mylist", 0, 99)

    def test_ltrim_with_negative_indices(self):
        """ltrim() works with negative indices to keep last N elements"""
        with patch.dict("os.environ", {"REDIS_HOST": "localhost"}):
            client = RedisClient()
            mock_redis = MagicMock()
            mock_redis.ltrim.return_value = True
            
            with patch.object(RedisClient, "client", new_callable=lambda: property(lambda self: mock_redis)):
                result = client.ltrim("mylist", -100, -1)
                
                assert result is True
                mock_redis.ltrim.assert_called_once_with("aona:mylist", -100, -1)
