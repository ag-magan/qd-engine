import json
import logging
import re
from typing import Optional

import anthropic

from src.shared.config import ANTHROPIC_API_KEY, CLAUDE_MODELS
from src.shared.database import Database

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Wrapper around Anthropic SDK with model-aware methods.

    Three call types:
    - analyze():          Standard analysis (Sonnet default, optional extended thinking)
    - quick_decision():   Fast yes/no (Haiku, no thinking)
    - strategic_review(): Deep strategic analysis (Opus with adaptive thinking)
    """

    def __init__(self, account_id: str = None):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.account_id = account_id
        self.db = Database()

    def _parse_json(self, text: str) -> Optional[dict]:
        """Extract JSON from response text, handling markdown code blocks."""
        patterns = [
            r"```json\s*(.*?)\s*```",
            r"```\s*(.*?)\s*```",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.error(f"Failed to parse JSON from response: {text[:200]}...")
            return None

    def _extract_text(self, response) -> str:
        """Extract text from response, handling thinking blocks."""
        result_text = ""
        for block in response.content:
            if block.type == "thinking":
                pass  # Thinking blocks logged but not returned
            elif block.type == "text":
                result_text += block.text
        return result_text

    def _log(self, model_id: str, analysis_type: str, prompt_summary: str,
             response_text: str, tokens_used: int):
        """Log API call to database."""
        self.db.log_analysis({
            "account_id": self.account_id,
            "analysis_type": analysis_type,
            "prompt_summary": prompt_summary[:500],
            "response_summary": response_text[:500],
            "full_response": {"text": response_text},
            "tokens_used": tokens_used,
            "model": model_id,
        })

    def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "sonnet",
        analysis_type: str = "general",
        expect_json: bool = True,
        max_tokens: int = 4096,
        thinking: bool = False,
        thinking_budget: int = 4096,
    ) -> Optional[dict]:
        """Standard analysis. Defaults to Sonnet without thinking.

        Set thinking=True to enable extended thinking (budget_tokens) on Sonnet/Haiku.
        """
        model_id = CLAUDE_MODELS[model]
        try:
            params = {
                "model": model_id,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if thinking and model != "opus":
                params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
                # API requires max_tokens > budget_tokens
                if params["max_tokens"] <= thinking_budget:
                    params["max_tokens"] = thinking_budget + max_tokens

            message = self.client.messages.create(**params)

            response_text = self._extract_text(message)
            tokens_used = message.usage.input_tokens + message.usage.output_tokens
            self._log(model_id, analysis_type, user_prompt, response_text, tokens_used)

            if expect_json:
                parsed = self._parse_json(response_text)
                if parsed is None:
                    logger.error("Failed to parse JSON from Claude response")
                return parsed
            else:
                return {"text": response_text, "tokens_used": tokens_used}

        except Exception as e:
            logger.error(f"Claude API call failed ({model_id}): {e}")
            return None

    def quick_decision(self, context: str, model: str = "haiku") -> Optional[dict]:
        """Fast yes/no trade decision. Haiku, no thinking. Returns parsed JSON."""
        system = (
            "You are a trading decision assistant. Respond with ONLY a JSON object: "
            '{"decision": "yes" or "no", "confidence": 0-100, "reason": "brief reason"}'
        )
        return self.analyze(
            system_prompt=system,
            user_prompt=context,
            model=model,
            analysis_type="quick_decision",
            max_tokens=256,
        )

    def strategic_review(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "opus",
        effort: str = "high",
        analysis_type: str = "strategic_review",
        expect_json: bool = True,
        max_tokens: int = 32000,
    ) -> Optional[dict]:
        """Deep strategic analysis. Opus 4.6 with adaptive thinking.

        Effort levels: 'low', 'medium', 'high' (default), 'max'
        """
        import time

        model_id = CLAUDE_MODELS[model]
        max_retries = 3

        for attempt in range(max_retries):
            try:
                params = {
                    "model": model_id,
                    "max_tokens": max_tokens,
                    "thinking": {"type": "adaptive"},
                    "output_config": {"effort": effort},
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                }

                # Use streaming for Opus to avoid timeout on long-running requests
                with self.client.messages.stream(**params) as stream:
                    message = stream.get_final_message()

                response_text = self._extract_text(message)
                tokens_used = message.usage.input_tokens + message.usage.output_tokens
                self._log(model_id, analysis_type, user_prompt, response_text, tokens_used)

                if expect_json:
                    parsed = self._parse_json(response_text)
                    if parsed is None:
                        logger.error("Failed to parse JSON from strategic review response")
                    return parsed
                else:
                    return {"text": response_text, "tokens_used": tokens_used}

            except anthropic.APIStatusError as e:
                if "overloaded" in str(e).lower() and attempt < max_retries - 1:
                    wait = 30 * (attempt + 1)
                    logger.warning(f"Opus overloaded, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue
                logger.error(f"Strategic review API call failed ({model_id}): {e}")
                return None
            except Exception as e:
                logger.error(f"Strategic review API call failed ({model_id}): {e}")
                return None
