import asyncio
import dataclasses
import unittest

from brain.app import Brain
from brain.config import load_settings
from brain.crawl import first_crawl, process_queue
from brain.fetch import FetchResult, parse_sitemap
from brain.llm import MockLLM
from brain.parser import parse_article
from brain.qa import ask
from brain.sync import make_plan, run_sync
from brain.tasks import list_tasks, resolve_task

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


def page(title, body, img=None):
    im = f'<img src="{img}" alt="shot">' if img else ""
    return f"<html><body><nav>MENU LINKS</nav><article><h1>{title}</h1><p>{body}</p>{im}</article></body></html>".encode()


class FakeSite:
    def __init__(self, pages, lastmod="1"):
        self.pages = dict(pages)
        self.lastmod = {u: lastmod for u in pages}
        self.fail: set[str] = set()
        self.hits: list[str] = []

    def sitemap(self):
        items = "".join(f"<url><loc>{u}</loc><lastmod>{self.lastmod[u]}</lastmod></url>" for u in self.pages)
        return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'.encode()

    async def get(self, url):
        self.hits.append(url)
        if url.endswith("sitemap.xml"):
            return FetchResult(url, 200, self.sitemap(), "application/xml")
        if url.endswith(".png"):
            return FetchResult(url, 200, PNG, "image/png")
        if url in self.fail:
            raise RuntimeError("boom")
        if url in self.pages:
            return FetchResult(url, 200, self.pages[url], "text/html")
        return FetchResult(url, 404)


def make(site, **over):
    s = dataclasses.replace(load_settings(), sitemap_url="https://h.test/sitemap.xml", batch_pause_s=0,
                            batch_size=2, min_delay_s=0, max_attempts=2, **over)
    return Brain.create(s, llm=MockLLM(), fetcher=site, db_path=":memory:")


BASE = {
    "https://h.test/a": page("Change pricing", "Open Admin then Membership Plans and edit the Monthly Price field. " * 3, "https://h.test/i/one.png"),
    "https://h.test/b": page("Refund policy", "Refunds are available within fourteen days for annual plans only. " * 3),
    "https://h.test/c": page("Custom domain", "Point your CNAME record to the platform host name to connect a domain. " * 3, "https://h.test/i/one.png"),
}
run = asyncio.run


class T(unittest.TestCase):
    def test_parser_drops_nav_and_finds_images(self):
        a = parse_article(BASE["https://h.test/a"].decode(), "https://h.test/a")
        self.assertEqual(a.title, "Change pricing")
        self.assertNotIn("MENU", a.text)
        self.assertEqual(a.images, [("https://h.test/i/one.png", "shot")])

    def test_sitemap_index(self):
        pages, kids = parse_sitemap(b'<sitemapindex xmlns="x"><sitemap><loc>https://h/s2.xml</loc></sitemap></sitemapindex>')
        self.assertEqual((pages, kids), ([], ["https://h/s2.xml"]))

    def test_first_crawl_indexes_and_image_caption_is_cached(self):
        site = FakeSite(BASE); b = make(site)
        rep = run(first_crawl(b))
        self.assertEqual(rep.indexed, 3)
        vision = b.db.query("SELECT count(*) c FROM usage WHERE purpose='vision'")[0]["c"]
        self.assertEqual(vision, 1)  # same image on two pages -> captioned once
        self.assertGreater(b.index.stats()["chunks"], 3)

    def test_crawl_resumes_after_stop(self):
        site = FakeSite(BASE); b = make(site)
        run(first_crawl(b, limit=1))
        self.assertEqual(b.index.stats()["pages_active"], 1)
        before = len([h for h in site.hits if h in BASE])
        run(first_crawl(b))  # "restart": queue is already in the DB
        self.assertEqual(b.index.stats()["pages_active"], 3)
        self.assertEqual(len([h for h in site.hits if h in BASE]) - before, 2)  # did not refetch page 1

    def test_failing_page_is_isolated_and_retried(self):
        site = FakeSite(BASE); site.fail.add("https://h.test/b"); b = make(site)
        rep = run(first_crawl(b))
        self.assertEqual((rep.indexed, rep.failed), (2, 1))
        site.fail.clear()
        rep2 = run(process_queue(b, retry_failed=True))
        self.assertEqual(rep2.indexed, 1)

    def test_sync_added_updated_removed(self):
        site = FakeSite(BASE); b = make(site); run(first_crawl(b))
        site.pages["https://h.test/a"] = page("Change pricing", "NEW text about Stripe payouts and invoices. " * 5)
        site.lastmod["https://h.test/a"] = "2"
        del site.pages["https://h.test/b"]; del site.lastmod["https://h.test/b"]
        site.pages["https://h.test/d"] = page("Invoices", "Download invoices from the billing tab of your account. " * 3)
        site.lastmod["https://h.test/d"] = "1"
        out = run(run_sync(b))
        self.assertEqual((out["added"], out["updated"], out["removed"]), (1, 1, 1))
        self.assertEqual(b.index.search("refund annual plans"), [])        # removed article is gone
        self.assertTrue(b.index.search("stripe payouts"))                    # updated content searchable
        self.assertFalse(b.index.search("membership plans edit"))            # old content is gone
        out2 = run(run_sync(b))                                              # nothing changed -> nothing refetched
        self.assertEqual((out2["added"], out2["updated"], out2["removed"], out2["indexed"]), (0, 0, 0, 0))

    def test_removal_guard_on_broken_sitemap(self):
        site = FakeSite(BASE); b = make(site); run(first_crawl(b))
        plan = make_plan(b, [("https://h.test/a", "1")])  # sitemap suddenly lists 1 of 3
        self.assertTrue(plan.removal_blocked); self.assertEqual(plan.removed, [])

    def test_answer_with_sources_and_unknown_creates_task_then_expert_teaches(self):
        site = FakeSite(BASE); b = make(site); run(first_crawl(b))
        a = run(ask(b, "How do I change the monthly price of a plan?"))
        self.assertTrue(a.answered); self.assertEqual(a.sources[0].url, "https://h.test/a")
        u = run(ask(b, "How do I export members to Salesforce?"))
        self.assertFalse(u.answered); self.assertIsNotNone(u.task_id)
        self.assertEqual(len(list_tasks(b)), 1)
        run(ask(b, "How do I export members to Salesforce?"))
        self.assertEqual(len(list_tasks(b)), 1)  # deduplicated
        resolve_task(b, u.task_id, "Use the Zapier integration under Admin > Integrations.", "jane")
        again = run(ask(b, "How do I export members to Salesforce?"))
        self.assertTrue(again.answered); self.assertEqual(again.sources[0].kind, "expert")

    def test_answer_found_only_in_screenshot_caption(self):
        site = FakeSite(BASE)
        llm = MockLLM(lambda s, u, img: "Screenshot showing the Hexagon Toggle switched ON" if img else MockLLM._default(s, u, img))
        s = dataclasses.replace(load_settings(), sitemap_url="https://h.test/sitemap.xml", batch_pause_s=0, min_delay_s=0)
        b = Brain.create(s, llm=llm, fetcher=site, db_path=":memory:"); run(first_crawl(b))
        hits = b.index.search("hexagon toggle")
        self.assertTrue(hits and hits[0].kind == "image" and hits[0].image_url)

    def test_model_citing_nonexistent_source_is_refused(self):
        site = FakeSite(BASE)
        llm = MockLLM(lambda s, u, img: "cap" if img else '{"answer":"made up","sources":[9],"confident":true}')
        s = dataclasses.replace(load_settings(), sitemap_url="https://h.test/sitemap.xml", batch_pause_s=0, min_delay_s=0)
        b = Brain.create(s, llm=llm, fetcher=site, db_path=":memory:"); run(first_crawl(b))
        self.assertFalse(run(ask(b, "How do I change the monthly price of a plan?")).answered)


if __name__ == "__main__":
    unittest.main()
