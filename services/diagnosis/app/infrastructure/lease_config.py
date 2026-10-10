"""Lease policy and lifecycle configuration for Diagnosis service.

In accordance with ADR-0008 (D6):
- lease_duration_seconds: default 60s
- heartbeat_seconds: default 20s
- processing_deadline_seconds: default 300s
- max_attempt_count: default 3
- recovery_wait_seconds_attempt_2: default 5s (wait after 1st lease expiration)
- recovery_wait_seconds_attempt_3: default 15s (wait after 2nd lease expiration)

Validation rules:
- heartbeat_seconds < lease_duration_seconds
- lease_duration_seconds > 0, heartbeat_seconds > 0, processing_deadline_seconds > 0
- processing_deadline_seconds >= lease_duration_seconds
- max_attempt_count >= 1
- recovery_wait_seconds >= 0
"""
from dataclasses import dataclass
import os
from typing import Optional


class LeaseConfigurationError(ValueError):
    """Raised when lease timing or policy configuration is invalid."""
    pass


@dataclass(frozen=True)
class LeasePolicy:
    lease_duration_seconds: int = 60
    heartbeat_seconds: int = 20
    processing_deadline_seconds: int = 300
    max_attempt_count: int = 3
    recovery_wait_seconds_attempt_2: int = 5
    recovery_wait_seconds_attempt_3: int = 15

    def __post_init__(self):
        if self.lease_duration_seconds <= 0:
            raise LeaseConfigurationError("lease_duration_seconds must be positive")
        if self.heartbeat_seconds <= 0:
            raise LeaseConfigurationError("heartbeat_seconds must be positive")
        if self.heartbeat_seconds >= self.lease_duration_seconds:
            raise LeaseConfigurationError("heartbeat_seconds must be strictly less than lease_duration_seconds")
        if self.processing_deadline_seconds < self.lease_duration_seconds:
            raise LeaseConfigurationError("processing_deadline_seconds cannot be less than lease_duration_seconds")
        if self.max_attempt_count < 1:
            raise LeaseConfigurationError("max_attempt_count must be at least 1")
        if self.recovery_wait_seconds_attempt_2 < 0 or self.recovery_wait_seconds_attempt_3 < 0:
            raise LeaseConfigurationError("recovery wait seconds cannot be negative")

    def get_recovery_wait_seconds(self, current_attempt: int) -> int:
        """Returns the minimum recovery wait time after the previous lease expired."""
        if current_attempt == 1:
            return self.recovery_wait_seconds_attempt_2
        return self.recovery_wait_seconds_attempt_3


def get_lease_policy_from_environment() -> LeasePolicy:
    """Load and validate lease policy from environment variables."""
    return LeasePolicy(
        lease_duration_seconds=int(os.environ.get("LEASE_DURATION_SECONDS", "60")),
        heartbeat_seconds=int(os.environ.get("LEASE_HEARTBEAT_SECONDS", "20")),
        processing_deadline_seconds=int(os.environ.get("PROCESSING_DEADLINE_SECONDS", "300")),
        max_attempt_count=int(os.environ.get("MAX_ATTEMPT_COUNT", "3")),
        recovery_wait_seconds_attempt_2=int(os.environ.get("RECOVERY_WAIT_SECONDS_ATTEMPT_2", "5")),
        recovery_wait_seconds_attempt_3=int(os.environ.get("RECOVERY_WAIT_SECONDS_ATTEMPT_3", "15")),
    )


_GLOBAL_POLICY: Optional[LeasePolicy] = None


def get_lease_policy() -> LeasePolicy:
    global _GLOBAL_POLICY
    if _GLOBAL_POLICY is None:
        _GLOBAL_POLICY = get_lease_policy_from_environment()
    return _GLOBAL_POLICY


def set_lease_policy(policy: LeasePolicy) -> None:
    global _GLOBAL_POLICY
    _GLOBAL_POLICY = policy

