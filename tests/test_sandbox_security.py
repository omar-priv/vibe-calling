import unittest

from adapters.sandbox import SandboxAdapter, SandboxSecurityError


class SandboxSecurityTests(unittest.TestCase):
    """The placeholder sandbox must stay disabled until OS isolation is real."""

    def setUp(self):
        self.adapter = SandboxAdapter()

    def test_sandbox_adapter_is_reported_but_unavailable(self):
        status = self.adapter.status()
        self.assertFalse(self.adapter.is_available())
        self.assertFalse(status["available"])
        self.assertFalse(status["enforced"]["os_filesystem_isolation"])
        self.assertFalse(status["enforced"]["network_isolation"])
        self.assertFalse(status["enforced"]["restricted_process_token"])

    def test_sandbox_initialization_refuses_unsafe_fallback(self):
        with self.assertRaises(SandboxSecurityError):
            self.adapter.initialize()

    def test_sandbox_command_refuses_to_run_as_regular_user(self):
        result = self.adapter.sandbox_command({"command": "cmd /c echo hello"})
        self.assertFalse(result.ok)
        self.assertIn("not available", result.error.lower())

    def test_sandbox_workspace_registration_is_disabled(self):
        with self.assertRaises(SandboxSecurityError):
            self.adapter.register_workspace("test", ".")


if __name__ == "__main__":
    unittest.main()
