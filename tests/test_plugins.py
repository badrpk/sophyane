import inspect
import unittest

from sophyane.plugin_loader import PluginLoader


class PluginTests(unittest.TestCase):
    def test_plugins_discover(self):
        loader = PluginLoader()
        providers = loader.discover()

        self.assertIn("gemini", providers)
        self.assertIn("openai", providers)
        self.assertIn("ollama", providers)

    def test_all_plugins_support_timeout(self):
        loader = PluginLoader()

        for provider_class in loader.discover().values():
            signature = inspect.signature(
                provider_class.__init__
            )

            self.assertIn(
                "timeout",
                signature.parameters,
                msg=provider_class.__name__,
            )

    def test_provider_creation_accepts_timeout(self):
        loader = PluginLoader()

        provider = loader.create(
            "gemini",
            api_key="test",
            model="test-model",
            timeout=30,
            temperature=0.2,
            max_tokens=500,
        )

        self.assertEqual(provider.timeout, 30)


if __name__ == "__main__":
    unittest.main()
