import math
import pytest
import server

def test_slug():
    assert server._slug("My Design 01!") == "My-Design-01"
    assert server._slug("caixa_presente_12x12") == "caixa_presente_12x12"
    with pytest.raises(ValueError):
        server._slug("   ***///   ")

def test_num_and_pos():
    server._num(a=1, b=2.5, c=-3)
    with pytest.raises(ValueError, match="must be a finite number"):
        server._num(x=float("nan"))
    with pytest.raises(ValueError, match="must be a finite number"):
        server._num(x=True)

    server._pos(width=10, height=0.5)
    with pytest.raises(ValueError, match="must be > 0"):
        server._pos(width=0)
    with pytest.raises(ValueError, match="must be > 0"):
        server._pos(height=-5)

def test_fmt():
    assert server._fmt(10.0) == "10"
    assert server._fmt(10.5) == "10.5"
    assert server._fmt(0.1234) == "0.1234"
    assert server._fmt(0.00001) == "0"

def test_bbox_and_union():
    circle = {"kind": "circle", "cx": 50, "cy": 50, "r": 10}
    assert server._bbox(circle) == (40, 40, 60, 60)

    poly = {"kind": "poly", "points": [[0, 5], [20, 5], [20, 25], [0, 25]]}
    assert server._bbox(poly) == (0, 5, 20, 25)

    assert server._union_bbox([circle, poly]) == (0, 5, 60, 60)
    assert server._union_bbox([]) is None

def test_arc_and_n_segments():
    pts = server._arc(0, 0, 10, 10, 0, math.pi / 2)
    assert len(pts) >= 3
    # Primeiro ponto proximo a (10, 0)
    assert math.isclose(pts[0][0], 10.0, abs_tol=1e-4)
    assert math.isclose(pts[0][1], 0.0, abs_tol=1e-4)
    # Ultimo ponto proximo a (0, 10)
    assert math.isclose(pts[-1][0], 0.0, abs_tol=1e-4)
    assert math.isclose(pts[-1][1], 10.0, abs_tol=1e-4)

def test_rotate():
    pts = [(10, 0)]
    rotated = server._rotate(pts, 0, 0, 90)
    assert math.isclose(rotated[0][0], 0.0, abs_tol=1e-4)
    assert math.isclose(rotated[0][1], 10.0, abs_tol=1e-4)

def test_rounded_rect():
    # Sem arredondamento
    rect = server._rounded_rect(0, 0, 50, 30, 0)
    assert rect == [(0, 0), (50, 0), (50, 30), (0, 30)]

    # Com arredondamento
    r_rect = server._rounded_rect(0, 0, 50, 30, 5)
    assert len(r_rect) > 4
    xs = [p[0] for p in r_rect]
    ys = [p[1] for p in r_rect]
    assert min(xs) >= 0.0 and max(xs) <= 50.0
    assert min(ys) >= 0.0 and max(ys) <= 30.0

