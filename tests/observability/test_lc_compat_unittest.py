import unittest
from sophyane.lc_compat.prompt_templates import PromptTemplate
from sophyane.lc_compat.output_parsers import JsonOutputParser
from sophyane.lc_compat.tools import tool
from sophyane.lc_compat.memory import BufferMemory
from sophyane.observability.datasets import Dataset, Example, run_experiment, exact_match
from sophyane.observability.accounting import record_usage, summarize
from sophyane.graph_runtime import StateGraph
from sophyane.lc_compat.graph_viz import to_mermaid
from sophyane.lc_compat.durable_graph import DurableExecutor

class LCCompatTests(unittest.TestCase):
    def test_prompt(self):
        p = PromptTemplate("Hello {name}")
        self.assertEqual(p.format(name="Ada"), "Hello Ada")

    def test_json_parser(self):
        self.assertEqual(JsonOutputParser().parse('x {"a":1} y'), {"a": 1})

    def test_tool(self):
        @tool(description="add")
        def add(x: int, y: int) -> int:
            return x + y
        self.assertEqual(add.invoke(x=2, y=3), 5)

    def test_memory(self):
        m = BufferMemory()
        m.add("user", "hi")
        self.assertIn("hi", m.as_text())

    def test_dataset_experiment(self):
        ds = Dataset("demo", examples=[Example(inputs={"x": 1}, outputs={"y": 2})])
        ds.save()
        exp = run_experiment(ds, predict=lambda inp: {"y": 2}, evaluators=[exact_match])
        self.assertEqual(exp.mean_score, 1.0)

    def test_accounting(self):
        record_usage("local", "test", 10, 5)
        s = summarize()
        self.assertGreaterEqual(s["calls"], 1)

    def test_mermaid_and_durable(self):
        g = StateGraph()
        g.add_node("a", lambda s: {**s, "v": 1})
        g.add_edge(g.START, "a")
        g.add_edge("a", g.END)
        text = to_mermaid(g)
        self.assertIn("START", text)
        ex = DurableExecutor(g)
        ts = ex.invoke({})
        self.assertEqual(ts.status, "done")

if __name__ == "__main__":
    unittest.main()
