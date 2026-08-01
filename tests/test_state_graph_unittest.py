import unittest
from sophyane.state_graph import END, MemorySaver, StateGraph


class StateGraphTests(unittest.TestCase):
    def test_linear_chain(self):
        g = StateGraph()
        g.add_node("a", lambda s: {"v": s.get("v", 0) + 1})
        g.add_node("b", lambda s: {"v": s["v"] + 1})
        g.add_node("c", lambda s: {"v": s["v"] + 1, "done": True})
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", END)
        app = g.compile()
        out = app.invoke({"v": 0})
        self.assertEqual(out["v"], 3)
        self.assertTrue(out["done"])

    def test_conditional(self):
        g = StateGraph()
        g.add_node("classify", lambda s: {"label": "hi" if s.get("n", 0) > 0 else "lo"})
        g.add_node("hi", lambda s: {"path": "hi"})
        g.add_node("lo", lambda s: {"path": "lo"})
        g.set_entry_point("classify")
        g.add_conditional_edges(
            "classify",
            lambda s: s.get("label", "lo"),
            {"hi": "hi", "lo": "lo"},
        )
        g.add_edge("hi", END)
        g.add_edge("lo", END)
        app = g.compile()
        self.assertEqual(app.invoke({"n": 1})["path"], "hi")
        self.assertEqual(app.invoke({"n": 0})["path"], "lo")

    def test_checkpoint_resume(self):
        mem = MemorySaver()
        g = StateGraph()
        g.add_node("inc", lambda s: {"n": s.get("n", 0) + 1})
        g.set_entry_point("inc")
        g.add_edge("inc", END)
        app = g.compile(checkpointer=mem)
        app.invoke({"n": 0}, config={"thread_id": "t1"})
        out = app.invoke({}, config={"thread_id": "t1"})
        self.assertEqual(out["n"], 2)

    def test_list_reducer(self):
        g = StateGraph()
        g.add_node("a", lambda s: {"logs": ["a"]})
        g.add_node("b", lambda s: {"logs": ["b"]})
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        out = g.compile().invoke({"logs": []})
        self.assertEqual(out["logs"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
