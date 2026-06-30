import unittest

from core.compact import ContextCompactor, OLD_TOOL_RESULT_CLEARED


class ContextCompactorTests(unittest.IsolatedAsyncioTestCase):
    def test_estimate_tokens_includes_tool_results_and_tool_calls(self):
        compactor = ContextCompactor()
        messages = [
            {"role": "user", "content": "hello" * 30},
            {
                "role": "assistant",
                "content": "using a tool",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "Read",
                        "arguments": '{"file_path":"big.py"}',
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "result" * 100,
            },
        ]

        self.assertGreater(compactor.estimate_tokens(messages), 200)

    def test_microcompact_clears_old_large_tool_results_and_keeps_recent(self):
        compactor = ContextCompactor(
            keep_recent_tool_results=5,
            tool_result_clear_threshold_chars=10,
        )
        messages = [
            {"role": "tool", "tool_call_id": f"tool_{i}", "content": "x" * 50}
            for i in range(7)
        ]

        compacted, cleared = compactor.microcompact_tool_results(messages)

        self.assertEqual(cleared, 2)
        self.assertEqual(compacted[0]["content"], OLD_TOOL_RESULT_CLEARED)
        self.assertEqual(compacted[1]["content"], OLD_TOOL_RESULT_CLEARED)
        self.assertEqual(compacted[2]["content"], "x" * 50)
        self.assertEqual(messages[0]["content"], "x" * 50)

    def test_microcompact_does_not_modify_non_tool_messages(self):
        compactor = ContextCompactor(tool_result_clear_threshold_chars=10)
        messages = [
            {"role": "user", "content": "x" * 100},
            {"role": "assistant", "content": "y" * 100},
        ]

        compacted, cleared = compactor.microcompact_tool_results(messages)

        self.assertEqual(cleared, 0)
        self.assertEqual(compacted, messages)

    async def test_compact_summary_success_returns_summary_files_and_recent_messages(self):
        compactor = ContextCompactor(preserve_last_n=2)
        messages = [
            {"role": "user", "content": f"old {i}"}
            for i in range(4)
        ] + [
            {"role": "assistant", "content": "recent assistant"},
            {"role": "user", "content": "recent user"},
        ]
        read_file_state = {
            "/tmp/app.py": {
                "timestamp": 10,
                "content": "1\tprint('hello')\n",
            }
        }

        async def fake_llm(_messages):
            return {"content": "Detailed compact summary"}

        result = await compactor.compact_with_llm_to_messages(
            messages,
            fake_llm,
            read_file_state,
        )

        self.assertIsNotNone(result)
        compacted, info = result
        self.assertIn("<compact-summary>", compacted[0]["content"])
        self.assertIn("Detailed compact summary", compacted[0]["content"])
        self.assertIn("Recent file context", compacted[1]["content"])
        self.assertEqual(compacted[-2:], messages[-2:])
        self.assertEqual(info.restored_file_count, 1)
        self.assertEqual(compactor.consecutive_failures, 0)

    async def test_compact_summary_failure_preserves_failure_count(self):
        compactor = ContextCompactor(preserve_last_n=1)
        messages = [
            {"role": "user", "content": "old"},
            {"role": "user", "content": "recent"},
        ]

        async def failing_llm(_messages):
            raise RuntimeError("boom")

        result = await compactor.compact_with_llm_to_messages(messages, failing_llm)

        self.assertIsNone(result)
        self.assertEqual(compactor.consecutive_failures, 1)

    def test_consecutive_failures_trip_auto_compact_circuit_breaker(self):
        compactor = ContextCompactor(auto_compact_threshold=100, auto_compact_buffer=0)
        compactor.consecutive_failures = compactor.max_consecutive_failures
        messages = [{"role": "user", "content": "x" * 1000}]

        self.assertFalse(compactor.should_auto_compact(messages))


if __name__ == "__main__":
    unittest.main()
