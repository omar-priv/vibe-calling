import unittest

from worker.worker import _redact


class WorkerRedactionTests(unittest.TestCase):
    def test_redacts_secret_fields_recursively(self):
        value = {
            "api_key": "top-secret",
            "Authorization": "Bearer token-value",
            "nested": [{"client-secret": "client-value", "message": "safe"}],
        }
        result = _redact(value)
        self.assertEqual(result["api_key"], "***REDACTED***")
        self.assertEqual(result["Authorization"], "***REDACTED***")
        self.assertEqual(result["nested"][0]["client-secret"], "***REDACTED***")
        self.assertEqual(result["nested"][0]["message"], "safe")
        self.assertNotIn("top-secret", repr(result))
        self.assertNotIn("token-value", repr(result))

    def test_redacts_secret_values_embedded_in_error_text(self):
        result = _redact("request failed: Bearer abc123 api_key=xyz789 password:secret")
        self.assertNotIn("abc123", result)
        self.assertNotIn("xyz789", result)
        self.assertNotIn("secret", result)
        self.assertIn("Bearer ***REDACTED***", result)


if __name__ == "__main__":
    unittest.main()
