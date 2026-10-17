import asyncio
import unittest
from pathlib import Path

from scope import pipeline as PL
from scope.brain_client import FakeBrain, KbReply
from scope.chunking import windows
from scope.config import load
from scope.llm import LLMResult, MockLLM
from scope.models import Project

FIX = Path(__file__).resolve().parent.parent / "fixtures"
run = asyncio.run
BRAIN = lambda: FakeBrain({"newsletter": KbReply(True, "Enable Email Capture.", ["https://h/ec"]),  # noqa: E731
                           "spanish": KbReply(True, "Admin > Languages.", ["https://h/lang"])})


def project():
    p = Project("t", "Bakery")
    for f in FIX.glob("*.txt"):
        p.transcripts[f.stem] = f.read_text()
    return p


def pipe(llm=None, brain=None):
    return PL.Pipeline(llm or MockLLM(), brain or BRAIN(), load())


class T(unittest.TestCase):
    def test_windows_overlap_and_cover_everything(self):
        t = "\n".join(f"Anna: line {i} " + "word " * 20 for i in range(100))
        ws = windows(t, max_words=300, overlap_words=60)
        self.assertGreater(len(ws), 3)
        self.assertTrue(all(len(w.split()) <= 340 for w in ws))
        joined = "\n".join(ws)
        self.assertTrue(all(f"line {i} " in joined for i in range(100)))
        self.assertTrue(set(ws[0].splitlines()[-1:]) & set(ws[1].splitlines()))   # overlap exists

    def test_initial_scope_uses_brain_for_existing_settings_and_totals_come_from_code(self):
        b = BRAIN(); p = project(); sow = run(pipe(brain=b).build_initial(p, ["meeting-1", "meeting-2"]))
        by = {r.text: r for r in sow.requirements}
        self.assertEqual(by["We also want a newsletter signup form on the homepage"].solution, "existing_setting")
        self.assertTrue(by["We also want a newsletter signup form on the homepage"].kb_sources)
        self.assertTrue(any("newsletter" in q.lower() for q in b.asked))
        lo, hi = sow.total_hours()
        self.assertIn(f"{lo:g}-{hi:g}", sow.proposal_md)
        self.assertTrue(any(t.kind == "overhead" for t in sow.tasks))
        self.assertEqual(sum(1 for r in sow.requirements if r.text.startswith("Customers should pick")), 1)  # deduped across meetings
        self.assertTrue(any("search" in q for q in sow.questions))                                          # vague -> question

    def test_nothing_reaches_client_before_human_approval(self):
        sow = run(pipe().build_initial(project(), ["meeting-1"]))
        with self.assertRaises(PermissionError):
            PL.client_view(sow)
        PL.approve(sow, "senior")
        self.assertIn("Proposal", PL.client_view(sow))
        with self.assertRaises(ValueError):
            PL.approve(sow, "again")

    def test_followup_needs_an_approved_baseline(self):
        p = project(); pp = pipe(); run(pp.build_initial(p, ["meeting-1"]))
        with self.assertRaises(PermissionError):
            run(pp.build_followup(p, ["meeting-3-followup"]))

    def test_followup_diff_unchanged_modified_removed_and_out_of_scope(self):
        p = project(); pp = pipe()
        v1 = run(pp.build_initial(p, ["meeting-1", "meeting-2"])); PL.approve(v1, "senior")
        v2 = run(pp.build_followup(p, ["meeting-3-followup"]))
        d = v2.diff
        self.assertEqual([m["id"] for m in d["modified"]], ["R3"])
        self.assertEqual([m["id"] for m in d["removed"]], ["R4"])
        self.assertEqual(len(d["new_out_of_scope"]), 1)
        self.assertIn("loyalty", d["new_out_of_scope"][0]["text"])
        self.assertGreater(d["totals"]["change_order_hours"], 0)
        self.assertNotIn("R4", [r.id for r in v2.requirements])
        # agreed items keep their agreed numbers (update, not restart)
        h = lambda sow, rid: sum(t.hours for t in sow.tasks if t.requirement_id == rid)  # noqa: E731
        self.assertEqual(h(v1, "R5"), h(v2, "R5"))
        self.assertEqual(v2.baseline_version, 1)
        self.assertIn("outside agreed scope", v2.proposal_md.lower())

    def test_garbage_model_output_never_crashes_and_is_flagged(self):
        class Junk:
            async def complete(self, **kw): return LLMResult("lol no json")
        sow = run(pipe(llm=Junk()).build_initial(project(), ["meeting-1"]))
        self.assertEqual(sow.requirements, [])
        self.assertTrue(any("could not be read" in i for i in sow.review_issues))

    def test_estimator_failure_falls_back_to_flagged_defaults(self):
        class NoEstimates(MockLLM):
            async def complete(self, *, system, user, model, max_tokens=2000):
                if system.startswith("ESTIMATE"):
                    return LLMResult('{"tasks": "oops"}')
                return await super().complete(system=system, user=user, model=model, max_tokens=max_tokens)
        sow = run(pipe(llm=NoEstimates()).build_initial(project(), ["meeting-1"]))
        self.assertTrue(any("default" in i.lower() for i in sow.review_issues))
        self.assertTrue(any("DEFAULT ESTIMATE" in a for t in sow.tasks for a in t.assumptions))

    def test_brain_down_is_quoted_as_custom_and_flagged(self):
        class Down:
            async def ask(self, q): return KbReply(False, unavailable=True)
        sow = run(pipe(brain=Down()).build_initial(project(), ["meeting-1"]))
        self.assertTrue(all(r.solution == "custom" for r in sow.requirements))
        self.assertTrue(any("unavailable" in i for i in sow.review_issues))

    def test_long_transcript_requirements_in_late_windows_are_found(self):
        filler = "\n".join("Dev: " + "just talking about the weather and lunch " * 6 for _ in range(300))
        p = Project("L", "Long"); p.transcripts["long"] = "Maria: We need a refund button.\n" + filler + "\nMaria: We must have an admin report page.\n"
        s = load().__class__(**{**load().__dict__, "window_words": 400, "overlap_words": 50})
        sow = run(PL.Pipeline(MockLLM(), BRAIN(), s).build_initial(p, ["long"]))
        texts = " ".join(r.text for r in sow.requirements)
        self.assertIn("refund button", texts); self.assertIn("admin report", texts)

    def test_store_roundtrip(self):
        import tempfile, os
        p = project(); run(pipe().build_initial(p, ["meeting-1"]))
        path = os.path.join(tempfile.mkdtemp(), "p.json")
        st = PL.ProjectStore(path); st.projects[p.id] = p; st.save()
        back = PL.ProjectStore(path).projects[p.id]
        self.assertEqual(back.versions[0].total_hours(), p.versions[0].total_hours())


if __name__ == "__main__":
    unittest.main()
