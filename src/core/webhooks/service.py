# -*- coding: utf-8 -*-
"""Webhook delivery system with retry, circuit breaker, and HMAC-SHA256 verification.

Provides reliable webhook delivery with:
- Automatic retry with exponential backoff
- Circuit breaker pattern for failing endpoints
- HMAC-SHA256 signature verification for security
- Event type filtering

Usage:
    from src.core.webhooks.service import WebhookService, get_webhook_service

    service = get_webhook_service()
    service.register("task.created", "https://example.com/webhook")
    service.trigger("task.created", {"task_id": 123})
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import logging

import requests

from src.runtime.stores.db import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit breaker states
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"         # Failing, reject immediately
    HALF_OPEN = "half_open"  # Testing if service recovered


# ---------------------------------------------------------------------------
# Webhook models
# ---------------------------------------------------------------------------

@dataclass
class Webhook:
    """A registered webhook endpoint."""
    id: Optional[int] = None
    url: str = ""
    events: List[str] = field(default_factory=list)  # Event types to receive
    secret: str = ""  # For HMAC signature
    active: bool = True
    created_at: float = field(default_factory=time.time)


@dataclass
class WebhookDelivery:
    """A webhook delivery attempt."""
    id: Optional[int] = None
    webhook_id: int = 0
    event: str = ""
    payload: str = ""  # JSON string
    status: str = "pending"  # pending, delivered, failed
    attempts: int = 0
    last_attempt: Optional[float] = None
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker for webhook endpoints.

    Prevents hammering a failing endpoint by temporarily stopping requests.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if (
                self._last_failure_time
                and time.time() - self._last_failure_time > self._recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self._half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
        elif (
            self._state == CircuitState.CLOSED
            and self._failure_count >= self._failure_threshold
        ):
            self._state = CircuitState.OPEN

    def can_execute(self) -> bool:
        """Check if a call can be executed."""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self._half_open_max_calls
        return False  # OPEN state


# ---------------------------------------------------------------------------
# Webhook service
# ---------------------------------------------------------------------------

class WebhookService:
    """Service for managing webhooks and delivering events.

    Features:
    - Register/unregister webhooks
    - HMAC-SHA256 signature generation and verification
    - Automatic retry with exponential backoff
    - Circuit breaker for failing endpoints
    - Event type filtering
    """

    MAX_RETRIES = 3
    BASE_BACKOFF = 1.0  # seconds
    MAX_BACKOFF = 60.0  # seconds
    TIMEOUT = 10.0  # seconds per request

    def __init__(self):
        self._db = get_db()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._webhook_cache: Optional[List[Webhook]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # Refresh cache every 60 seconds

    def _get_circuit(self, url: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a URL."""
        if url not in self._circuit_breakers:
            self._circuit_breakers[url] = CircuitBreaker()
        return self._circuit_breakers[url]

    def _ensure_table(self) -> None:
        """Create the webhooks tables if they don't exist."""
        sql1 = """
            CREATE TABLE IF NOT EXISTS webhooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                events TEXT NOT NULL,
                secret TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            )
        """
        self._db.execute(sql1)
        
        sql2 = """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                webhook_id INTEGER NOT NULL,
                event TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt REAL,
                response_status INTEGER,
                response_body TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (webhook_id) REFERENCES webhooks(id)
            )
        """
        self._db.execute(sql2)
        
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_webhook_events ON webhooks (events)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_webhook ON webhook_deliveries (webhook_id)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_status ON webhook_deliveries (status)")

    def _load_webhooks(self) -> List[Webhook]:
        """Load webhooks from database with caching."""
        now = time.time()
        if self._webhook_cache and (now - self._cache_time) < self._cache_ttl:
            return self._webhook_cache

        self._ensure_table()
        rows = self._db.execute_fetchall(
            "SELECT * FROM webhooks WHERE active = 1"
        )
        webhooks = []
        for row in rows:
            events = json.loads(row["events"]) if row["events"] else []
            webhooks.append(
                Webhook(
                    id=row["id"],
                    url=row["url"],
                    events=events,
                    secret=row["secret"] or "",
                    active=bool(row["active"]),
                    created_at=row["created_at"],
                )
            )
        self._webhook_cache = webhooks
        self._cache_time = now
        return webhooks

    def register(
        self,
        url: str,
        events: List[str],
        secret: str = "",
    ) -> Webhook:
        """Register a new webhook endpoint.

        Args:
            url: The webhook URL to call
            events: List of event types to subscribe to
            secret: Secret for HMAC signature verification

        Returns:
            The created Webhook
        """
        self._ensure_table()
        now = time.time()

        # Check if URL already exists
        existing = self._db.execute_fetchone(
            "SELECT id FROM webhooks WHERE url = ?", (url,)
        )
        if existing:
            # Update existing
            self._db.execute(
                "UPDATE webhooks SET events = ?, secret = ?, active = 1 WHERE url = ?",
                (json.dumps(events), secret, url),
            )
            webhook_id = existing["id"]
        else:
            cursor = self._db.execute(
                "INSERT INTO webhooks (url, events, secret, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (url, json.dumps(events), secret, now),
            )
            webhook_id = cursor.lastrowid

        # Invalidate cache
        self._webhook_cache = None

        return Webhook(
            id=webhook_id,
            url=url,
            events=events,
            secret=secret,
            active=True,
            created_at=now,
        )

    def unregister(self, url: str) -> bool:
        """Unregister a webhook endpoint.

        Args:
            url: The webhook URL to remove

        Returns:
            True if removed, False if not found
        """
        self._ensure_table()
        result = self._db.execute(
            "UPDATE webhooks SET active = 0 WHERE url = ?",
            (url,),
        )
        self._webhook_cache = None
        return result.rowcount > 0

    def _generate_signature(self, payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for payload."""
        if not secret:
            return ""
        return hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _deliver_with_retry(
        self,
        webhook: Webhook,
        event: str,
        payload: Dict[str, Any],
    ) -> WebhookDelivery:
        """Deliver a webhook event with retry and circuit breaker.

        Args:
            webhook: The webhook to deliver to
            event: Event type
            payload: Event payload

        Returns:
            WebhookDelivery with delivery status
        """
        self._ensure_table()
        payload_json = json.dumps(payload)
        signature = self._generate_signature(payload_json, webhook.secret)

        # Create delivery record
        delivery = WebhookDelivery(
            webhook_id=webhook.id,
            event=event,
            payload=payload_json,
        )

        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO webhook_deliveries (webhook_id, event, payload, status, attempts, created_at) VALUES (?, ?, ?, 'pending', 0, ?)",
                (webhook.id, event, payload_json, time.time()),
            )
            delivery.id = cursor.lastrowid

        circuit = self._get_circuit(webhook.url)
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            if not circuit.can_execute():
                last_error = "Circuit breaker open"
                break

            delivery.attempts = attempt + 1
            delivery.last_attempt = time.time()

            try:
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "Nexus-Webhook/1.0",
                    "X-Webhook-Event": event,
                    "X-Webhook-Delivery-ID": str(delivery.id),
                }
                if signature:
                    headers["X-Webhook-Signature"] = f"sha256={signature}"

                response = requests.post(
                    webhook.url,
                    data=payload_json,
                    headers=headers,
                    timeout=self.TIMEOUT,
                )

                if response.status_code >= 200 and response.status_code < 300:
                    delivery.status = "delivered"
                    delivery.response_status = response.status_code
                    delivery.response_body = response.text[:1000]  # Truncate
                    circuit.record_success()
                    break
                else:
                    last_error = f"HTTP {response.status_code}"
                    circuit.record_failure()

            except requests.exceptions.Timeout:
                last_error = "Request timeout"
                circuit.record_failure()
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                circuit.record_failure()
            except Exception as e:
                last_error = str(e)
                circuit.record_failure()

            # Exponential backoff
            if attempt < self.MAX_RETRIES - 1:
                backoff = min(
                    self.BASE_BACKOFF * (2**attempt),
                    self.MAX_BACKOFF,
                )
                time.sleep(backoff)

        if delivery.status == "pending":
            delivery.status = "failed"
            delivery.error = last_error

        # Update delivery record
        self._db.execute(
            "UPDATE webhook_deliveries SET status = ?, attempts = ?, last_attempt = ?, response_status = ?, response_body = ?, error = ? WHERE id = ?",
            (
                delivery.status,
                delivery.attempts,
                delivery.last_attempt,
                delivery.response_status,
                delivery.response_body,
                delivery.error,
                delivery.id,
            ),
        )

        return delivery

    def trigger(
        self,
        event: str,
        payload: Dict[str, Any],
        async_delivery: bool = True,
    ) -> List[WebhookDelivery]:
        """Trigger a webhook event to all matching subscribers.

        Args:
            event: Event type (e.g., "task.created")
            payload: Event payload data
            async_delivery: If True, deliver in background (default)

        Returns:
            List of WebhookDelivery results
        """
        webhooks = self._load_webhooks()
        matching = [w for w in webhooks if event in w.events or "*" in w.events]

        deliveries = []
        for webhook in matching:
            delivery = self._deliver_with_retry(webhook, event, payload)
            deliveries.append(delivery)

        return deliveries

    def verify_signature(
        self,
        payload: str,
        signature: str,
        secret: str,
    ) -> bool:
        """Verify an incoming webhook signature.

        Args:
            payload: Raw request body
            signature: X-Webhook-Signature header value
            secret: Webhook secret

        Returns:
            True if signature is valid
        """
        if not signature or not secret:
            return False

        expected = self._generate_signature(payload, secret)
        expected_header = f"sha256={expected}"

        return hmac.compare_digest(signature, expected_header)

    def get_deliveries(
        self,
        webhook_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[WebhookDelivery]:
        """Get webhook delivery history.

        Args:
            webhook_id: Filter by webhook ID
            status: Filter by status (pending, delivered, failed)
            limit: Maximum number of records

        Returns:
            List of WebhookDelivery records
        """
        self._ensure_table()
        sql = "SELECT * FROM webhook_deliveries WHERE 1=1"
        params: List[Any] = []

        if webhook_id is not None:
            sql += " AND webhook_id = ?"
            params.append(webhook_id)

        if status:
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._db.execute_fetchall(sql, tuple(params))
        deliveries = []
        for row in rows:
            deliveries.append(
                WebhookDelivery(
                    id=row["id"],
                    webhook_id=row["webhook_id"],
                    event=row["event"],
                    payload=row["payload"],
                    status=row["status"],
                    attempts=row["attempts"],
                    last_attempt=row["last_attempt"],
                    response_status=row["response_status"],
                    response_body=row["response_body"],
                    error=row["error"],
                    created_at=row["created_at"],
                )
            )
        return deliveries


# Global service instance
_webhook_service: Optional[WebhookService] = None


def get_webhook_service() -> WebhookService:
    """Get the global WebhookService instance."""
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = WebhookService()
    return _webhook_service
