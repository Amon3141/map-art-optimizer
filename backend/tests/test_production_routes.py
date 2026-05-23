"""本番 /api/optimize リクエストボディのバリデーション。"""

import pytest
from pydantic import ValidationError

from app.routes import OptimizeBody, StrokePointBody
from app.optimization.app_defaults import (
    DEFAULT_FETCH_RADIUS_M,
    DEFAULT_SPEED_PRESET,
    FETCH_RADIUS_MAX_M,
    FETCH_RADIUS_MIN_M,
)


def _minimal_body(**kwargs) -> dict:
    base = {
        "stroke_components": [[StrokePointBody(x=0.0, y=0.0), StrokePointBody(x=1.0, y=0.0)]],
        "center_lon": 139.7671,
        "center_lat": 35.6812,
    }
    base.update(kwargs)
    return base


def test_fetch_radius_default():
    body = OptimizeBody(**_minimal_body())
    assert body.fetch_radius_m == DEFAULT_FETCH_RADIUS_M


def test_speed_preset_default():
    body = OptimizeBody(**_minimal_body())
    assert body.speed_preset == DEFAULT_SPEED_PRESET


def test_fetch_radius_at_bounds():
    OptimizeBody(**_minimal_body(fetch_radius_m=FETCH_RADIUS_MIN_M))
    OptimizeBody(**_minimal_body(fetch_radius_m=FETCH_RADIUS_MAX_M))


def test_fetch_radius_below_min_rejected():
    with pytest.raises(ValidationError):
        OptimizeBody(**_minimal_body(fetch_radius_m=FETCH_RADIUS_MIN_M - 1))


def test_fetch_radius_above_max_rejected():
    with pytest.raises(ValidationError):
        OptimizeBody(**_minimal_body(fetch_radius_m=FETCH_RADIUS_MAX_M + 1))
