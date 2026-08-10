"""Greeting helper for the tiny CLI fixture."""

def greet(name: str) -> str:
    return f"Hello, {name}!"


def shout(name: str) -> str:
    return greet(name).upper()
