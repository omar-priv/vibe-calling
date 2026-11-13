import unittest
from unittest.mock import Mock

from adapters.computer import ComputerAdapter


class ComputerDispatchTests(unittest.TestCase):
    def test_initialize_tool_calls_adapter_initialize(self):
        adapter = ComputerAdapter()
        adapter.initialize = Mock()
        result = adapter.execute(None, "computer_initialize", {"screenshot_dir": "C:/screens"})
        self.assertTrue(result.ok, result.error)
        adapter.initialize.assert_called_once_with(screenshot_dir="C:/screens")

    def test_shutdown_tool_calls_adapter_shutdown(self):
        adapter = ComputerAdapter()
        adapter.shutdown = Mock()
        result = adapter.execute(None, "computer_shutdown", {})
        self.assertTrue(result.ok, result.error)
        adapter.shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
