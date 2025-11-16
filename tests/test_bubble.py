"""Basic tests for the pybubble package."""

from pybubble import bubble_message


def test_bubble_message_default():
    assert bubble_message() == "Hello from pybubble!"


def test_bubble_message_custom_name():
    assert bubble_message("Codex") == "Hello from Codex!"
