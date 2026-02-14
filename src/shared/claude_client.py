import json
import logging
import re
from typing import Optional

import anthropic

from src.shared.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.shared.database import Database

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Wrapper around Anthropic SDK with JSON parsing and logging."""

    def __init__(self, account_id: str = None, model: str = None):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = model or CLAUDE_MODEL
        self.account_id = account_id
        self.db = Database()

    def _parse_json(self, text: str) -> Optional[dict]:
        """Extract JSON from response text, handling markdown code blocks."""
        # Try to extract from code blocks first
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

        # Try parsing the whole text as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in text
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.error(f"Failed to parse JSON from response: {text[:200]}...")
            return None

    def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        analysis_type: str = "general",
        expect_json: bool = True,
        max_tokens: int = 4096,
    ) -> Optional[dict]:
        """Send a prompt to Claude and parse the JSON response."""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            response_text = message.content[0].text
            tokens_used = message.usage.input_tokens + message.usage.output_tokens

            # Log to database
            self.db.log_analysis({
                "account_id": self.account_id,
                "analysis_type": analysis_type,
                "prompt_summary": user_prompt[:500],
                "response_summary": response_text[:500],
                "full_response": {"text": response_text},
                "tokens_used": tokens_used,
                "model": self.model,
            })

            if expect_json:
                parsed = self._parse_json(response_text)
                if parsed is None:
                    logger.error("Failed to parse JSON from Claude response")
                return parsed
            else:
                return {"text": response_text, "tokens_used": tokens_used}

        except Exception as e:
            logger.error(f"Claude API call failed: {e}")
            return None

    def quick_decision(self, context: str) -> Optional[dict]:
        """Quick yes/no trade decision with minimal tokens."""
        system = (
            "You are a trading decision assistant. Respond with ONLY a JSON object: "
            '{"decision": "yes" or "no", "confidence": 0-100, "reason": "brief reason"}'
        )
        return self.analyze(
            system_prompt=system,
            user_prompt=context,
            analysis_type="quick_decision",
            max_tokens=256,
        )
