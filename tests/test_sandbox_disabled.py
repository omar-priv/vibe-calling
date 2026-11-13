import unittest

from adapters.sandbox import SandboxAdapter, SandboxSecurityError


class SandboxDisabledTests(unittest.TestCase):
    def setUp(self):
        self.adapter = SandboxAdapter()

    def test_sandbox_is_not_advertised_as_available(self):
        self.assertFalse(self.adapter.is_available())
        status = self.adapter.status()
        self.assertFalse(status["available"])
        self.assertFalse(status["enforced"]["os_filesystem_isolation"])
        self.assertFalse(status["enforced"]["network_isolation"])
        self.assertFalse(status["enforced"]["restricted_process_token"])

    def test_initialize_refuses_to_run_host_commands_as_sandboxed(self):
        with self.assertRaises(SandboxSecurityError):
            self.adapter.initialize()

    def test_command_execution_is_refused(self):
        result = self.adapter.sandbox_command({"command": "python -c print(1)"})
        self.assertFalse(result.ok)
        self.assertIn("not available", result.error.lower())


if __name__ == "__main__":
    unittest.main()
