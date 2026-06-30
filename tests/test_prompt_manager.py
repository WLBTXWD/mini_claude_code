import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.agent import AgentLoop
from core.prompt_manager import PromptContext, PromptManager


class PromptManagerTests(unittest.TestCase):
    def make_session(self, root: str):
        return SimpleNamespace(
            cwd=root,
            project_root=root,
            model="test-model",
            session_id="test-session",
            max_turns=5,
            auto_compact_enabled=False,
        )

    def test_from_session_builds_system_prompt_with_environment(self):
        with tempfile.TemporaryDirectory() as root:
            manager = PromptManager.from_session(self.make_session(root))

        self.assertIn("Mini Claude Code", manager.system_prompt)
        self.assertIn("Working directory", manager.system_prompt)
        self.assertIn("test-model", manager.system_prompt)
        self.assertIn("platform", manager.system_context)

    def test_prepend_user_context_includes_claude_md_and_date(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "CLAUDE.md").write_text("# Project rules\nUse tests.", encoding="utf-8")
            manager = PromptManager.from_session(self.make_session(root))
            messages = [{"role": "user", "content": "hello"}]
            built = manager.prepend_user_context(messages)

        self.assertEqual(len(built), 2)
        self.assertEqual(built[0]["role"], "user")
        self.assertIn("<system-reminder>", built[0]["content"])
        self.assertIn("Project rules", built[0]["content"])
        self.assertIn("Today's date", built[0]["content"])
        self.assertEqual(messages, [{"role": "user", "content": "hello"}])

    def test_without_project_context_still_includes_current_date(self):
        with tempfile.TemporaryDirectory() as root:
            manager = PromptManager.from_session(self.make_session(root))
            built = manager.prepend_user_context([])

        self.assertEqual(len(built), 1)
        self.assertIn("currentDate", manager.user_context)
        self.assertIn("Today's date", built[0]["content"])

    def test_memory_index_is_included_in_system_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            memory_dir = Path(root, ".mini_claude_code", "memory")
            memory_dir.mkdir(parents=True)
            Path(memory_dir, "MEMORY.md").write_text("- Remember project facts", encoding="utf-8")
            manager = PromptManager.from_session(self.make_session(root))

        self.assertIn("# Memory", manager.system_prompt)
        self.assertIn("Remember project facts", manager.system_prompt)


class FakeLLM:
    def __init__(self, summary: str = "compact summary"):
        self.calls = []
        self.compact_calls = []
        self.summary = summary

    async def chat_completion(self, **kwargs):
        self.compact_calls.append(kwargs)
        return {
            "content": self.summary,
            "tool_calls": [],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    async def chat_completion_stream(self, **kwargs):
        self.calls.append(kwargs)
        yield {
            "type": "final",
            "content": "done",
            "thinking": "",
            "tool_calls": [],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "model": "test-model",
        }


class AgentPromptIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_uses_cached_prompt_manager_for_model_call(self):
        fake_llm = FakeLLM()
        manager = PromptManager(PromptContext(
            system_prompt="STATIC SYSTEM PROMPT",
            user_context={"currentDate": "Today's date is 2026-06-30."},
            system_context={"git_status": "(clean)"},
        ))
        agent = AgentLoop(fake_llm, prompt_manager=manager)

        events = [event async for event in agent.run("hello")]

        self.assertTrue(any(getattr(event, "reason", None) == "completed" for event in events))
        self.assertEqual(len(fake_llm.calls), 1)
        call = fake_llm.calls[0]
        self.assertEqual(call["system_prompt"], "STATIC SYSTEM PROMPT")
        self.assertEqual(call["messages"][0]["role"], "user")
        self.assertIn("<system-reminder>", call["messages"][0]["content"])
        self.assertEqual(call["messages"][1], {"role": "user", "content": "hello"})

    async def test_agent_compacts_with_llm_before_model_call_when_over_threshold(self):
        fake_llm = FakeLLM(summary="Summary for continuing work")
        manager = PromptManager(PromptContext(
            system_prompt="STATIC SYSTEM PROMPT",
            user_context={},
            system_context={},
        ))
        agent = AgentLoop(fake_llm, prompt_manager=manager)
        agent.compactor.auto_compact_threshold = 100
        agent.compactor.auto_compact_buffer = 0
        agent.compactor.preserve_last_n = 2
        agent.read_file_state["/tmp/example.py"] = {
            "timestamp": 1,
            "content": "1\tprint('restored')\n",
        }
        initial_messages = [
            {"role": "user", "content": "old context " + ("x" * 500)},
            {"role": "assistant", "content": "old answer " + ("y" * 500)},
            {"role": "tool", "tool_call_id": "old_tool", "content": "z" * 500},
        ]

        events = [event async for event in agent.run("continue", initial_messages)]

        self.assertTrue(any(event.get("type") == "compact" for event in events if isinstance(event, dict)))
        self.assertEqual(len(fake_llm.compact_calls), 1)
        model_messages = fake_llm.calls[0]["messages"]
        self.assertIn("<compact-summary>", model_messages[0]["content"])
        self.assertIn("Summary for continuing work", model_messages[0]["content"])
        self.assertIn("Recent file context", model_messages[1]["content"])
        self.assertEqual(model_messages[-1], {"role": "user", "content": "continue"})

    async def test_agent_does_not_full_compact_when_under_threshold(self):
        fake_llm = FakeLLM()
        manager = PromptManager(PromptContext(
            system_prompt="STATIC SYSTEM PROMPT",
            user_context={},
            system_context={},
        ))
        agent = AgentLoop(fake_llm, prompt_manager=manager)
        agent.compactor.auto_compact_threshold = 100000
        agent.compactor.auto_compact_buffer = 0

        events = [event async for event in agent.run("small")]

        self.assertTrue(any(getattr(event, "reason", None) == "completed" for event in events))
        self.assertEqual(fake_llm.compact_calls, [])
        self.assertEqual(fake_llm.calls[0]["messages"], [{"role": "user", "content": "small"}])


if __name__ == "__main__":
    unittest.main()
