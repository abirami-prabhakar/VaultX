"""Reject unsafe runtime settings before opening private application state."""
from decimal import Decimal

import pytest

from app.config import Settings


@pytest.mark.parametrize('value', ['NaN', 'sNaN', 'Infinity', '-Infinity', '-1'])
def test_minimum_amount_rejects_nonfinite_and_negative_values(value):
    with pytest.raises(ValueError, match='MINIMUM_AMOUNT'):
        Settings(api_key='test-key', minimum_amount=Decimal(value))


def test_zero_minimum_disables_the_threshold_without_breaking_positive_amount_rules():
    assert Settings(api_key='test-key', minimum_amount=Decimal('0')).minimum_amount == 0


@pytest.mark.parametrize('values', [
    {'api_key': ''},
    {'gemma_timeout': float('inf')},
    {'request_timeout_seconds': 0},
    {'request_timeout_seconds': float('nan')},
    {'rate_limit_requests': 0},
    {'rate_limit_window_seconds': -1},
])
def test_credentials_and_request_limits_must_be_explicit_and_valid(values):
    with pytest.raises(ValueError):
        Settings(**({'api_key': 'test-key'} | values))
