from src.greet import greet
from src.mathutil import add

def test_greet():
    assert "Hello" in greet("x")

def test_add():
    assert add(1, 2) == 3
