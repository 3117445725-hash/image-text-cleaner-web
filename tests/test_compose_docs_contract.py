"""Keep Docker Compose documentation aligned with actual deployment defaults."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ComposeDocsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.deployment = (ROOT / "README_部署说明.md").read_text(encoding="utf-8")
        cls.main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    def test_default_host_and_container_ports_agree(self):
        match = re.search(r'\$\{WEB_PORT:-(\d+)\}:(\d+)', self.compose)
        self.assertIsNotNone(match, "Compose host port mapping changed; update this test")
        self.assertEqual(match.group(1), match.group(2))

    def test_readmes_match_actual_host_port(self):
        port = re.search(r'\$\{WEB_PORT:-(\d+)\}', self.compose).group(1)
        self.assertIn(f"http://localhost:{port}", self.readme)
        self.assertIn(f"http://localhost:{port}", self.deployment)
        self.assertIn(f"http://服务器IP:{port}", self.deployment)

    def test_no_obsolete_example_password_or_port(self):
        for doc in (self.readme, self.deployment):
            self.assertNotIn("change-this-password", doc)
            self.assertNotIn("http://localhost:8000", doc)
            self.assertNotIn("http://服务器IP:8000", doc)

    def test_default_app_password_is_empty(self):
        self.assertRegex(self.compose, r'APP_PASSWORD:\s*\$\{APP_PASSWORD:-\}')
        self.assertIn("if APP_PASSWORD and value != APP_PASSWORD:", self.main)

    def test_docs_warn_about_missing_password(self):
        self.assertIn("不启用应用层密码校验", self.readme)
        self.assertIn("无应用层密码保护", self.deployment)
        self.assertIn("APP_PASSWORD", self.readme)
        self.assertIn("APP_PASSWORD", self.deployment)

    def test_public_deployment_requires_security_guidance(self):
        self.assertIn("HTTPS", self.readme)
        self.assertIn("HTTPS", self.deployment)
        self.assertIn("WEB_PORT", self.readme)
        self.assertIn("WEB_PORT", self.deployment)


if __name__ == "__main__":
    unittest.main()
