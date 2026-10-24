import unittest
from agent import demo, dispatch, inspect_logs, run_agent


class AgentTests(unittest.TestCase):
    def test_mixed_and_recovery(self):
        result = inspect_logs('Interface Ethernet1 changed state to down\nBGP neighbor 192.0.2.2 Established')
        self.assertEqual(result['categories'], ['bgp', 'interface'])
        self.assertEqual(result['events'][1]['line'], 2)

    def test_unknown_not_healthy(self):
        self.assertIn('does not establish healthy', demo('inventory complete')['report'])

    def test_tool_allowlist(self):
        self.assertIn('error', dispatch('execute_shell', {'command': 'anything'}, ''))
        self.assertIn('error', dispatch('inspect_logs', {'path': '../secret'}, ''))
        self.assertIn('error', dispatch('get_runbook', {'category': []}, ''))

    def test_loop_with_tools(self):
        answers = iter([
            {'tool_calls': [{'function': {'name': 'inspect_logs', 'arguments': {}}},
                            {'function': {'name': 'get_runbook', 'arguments': {'category': 'bgp'}}}]},
            {'content': 'Observed BGP down [L1]. Cause unconfirmed; inspect peer state.'}])
        result = run_agent('BGP neighbor down', chat=lambda *args: next(answers))
        self.assertEqual(len(result['trace']), 2)

    def test_invalid_citation_retried(self):
        answers = iter([
            {'tool_calls': [{'function': {'name': 'inspect_logs', 'arguments': {}}},
                            {'function': {'name': 'get_runbook', 'arguments': {'category': 'bgp'}}}]},
            {'content': 'BGP down [L99]'}, {'content': 'BGP down [L1]'}])
        result = run_agent('BGP down', chat=lambda *args: next(answers))
        self.assertEqual(result['report'], 'BGP down [L1]')

    def test_bounded_loop(self):
        with self.assertRaises(RuntimeError):
            run_agent('hello', chat=lambda *args: {'content': 'unsupported'}, max_steps=2)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            run_agent('')


if __name__ == '__main__':
    unittest.main()
