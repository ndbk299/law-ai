import io
import os
import unittest
from pathlib import Path
from http import HTTPStatus
from unittest.mock import Mock, patch

from backend import ai_engine as ai_engine_module
from backend import server as server_module


class MedicalLLMGeneratorTests(unittest.TestCase):
    def create_generator(self, **environment):
        config_path = Path("/nonexistent/law-gpt-ai-config.json")
        with patch.dict(os.environ, environment, clear=True), patch.object(
            ai_engine_module, "CONFIG_PATH", config_path
        ):
            return ai_engine_module.MedicalLLMGenerator()

    def test_openai_uses_chat_completions_api(self):
        generator = self.create_generator(
            AI_PROVIDER="openai",
            OPENAI_API_KEY="test-key",
            OPENAI_MODEL="test-model",
        )
        response = {"choices": [{"message": {"content": "Câu trả lời"}}]}
        with patch.object(generator, "_post_json", return_value=response) as post_json:
            answer = generator._call_provider([
                {"role": "system", "content": "system"},
                {"role": "user", "content": "question"},
            ])

        self.assertEqual(answer, "Câu trả lời")
        args, _ = post_json.call_args
        self.assertEqual(args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(args[1]["model"], "test-model")
        self.assertEqual(args[2]["Authorization"], "Bearer test-key")

    def test_gemini_and_ollama_extract_responses(self):
        cases = [
            (
                {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"},
                {"candidates": [{"content": {"parts": [{"text": "Gemini"}]}}]},
                "Gemini",
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            ),
            (
                {"AI_PROVIDER": "ollama", "OLLAMA_MODEL": "llama3.2"},
                {"message": {"content": "Ollama"}},
                "Ollama",
                "http://localhost:11434/api/chat",
            ),
        ]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
        ]
        for environment, response, expected, expected_url in cases:
            with self.subTest(provider=environment["AI_PROVIDER"]):
                generator = self.create_generator(**environment)
                with patch.object(generator, "_post_json", return_value=response) as post_json:
                    self.assertEqual(generator._call_provider(messages), expected)
                self.assertTrue(post_json.call_args.args[0].startswith(expected_url))
                if environment["AI_PROVIDER"] == "gemini":
                    self.assertEqual(
                        post_json.call_args.args[2]["x-goog-api-key"],
                        "test-key",
                    )

    def test_provider_failure_does_not_fall_back_to_local_response(self):
        generator = self.create_generator(AI_PROVIDER="openai", OPENAI_API_KEY="test-key")
        error = ai_engine_module.LLMProviderError("OpenAI API trả về HTTP 429.")
        with patch.object(generator, "_post_json", side_effect=error):
            with self.assertRaisesRegex(ai_engine_module.LLMProviderError, "HTTP 429"):
                generator.generate(
                    "Câu hỏi",
                    {"symptoms": [], "demographics": [], "conditions": []},
                    [],
                )

    def test_explicit_cloud_provider_requires_api_key(self):
        with self.assertRaisesRegex(ai_engine_module.LLMProviderError, "Thiếu API key"):
            self.create_generator(AI_PROVIDER="gemini")

    def test_local_processor_remains_available_without_provider_configuration(self):
        generator = self.create_generator()
        answer, _ = generator.generate(
            "xin chào",
            {"intent": "GREETING", "symptoms": [], "demographics": [], "conditions": []},
            [],
        )
        self.assertIn("Xin chào", answer)

    def test_chat_endpoint_returns_bad_gateway_for_provider_errors(self):
        handler = object.__new__(server_module.LawGPTRequestHandler)
        body = b'{"message":"test"}'
        handler.path = "/api/chat"
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler._send_json = Mock()

        with patch.object(
            server_module.ai_engine,
            "process",
            side_effect=ai_engine_module.LLMProviderError("OpenAI API trả về HTTP 429."),
        ):
            handler.do_POST()

        handler._send_json.assert_called_once_with(
            HTTPStatus.BAD_GATEWAY,
            {"error": "OpenAI API trả về HTTP 429."},
        )


if __name__ == "__main__":
    unittest.main()
