import http.server
import os
import shutil
import subprocess
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "fetch-page.py")

PAGE = """<!doctype html><html><head><title>红果月活 &amp; 河马</title><style>.x{}</style>
<script>var secret = "不应出现";</script></head><body>
<nav><a>首页</a><a>科技</a></nav>
<p>红果短剧 2026 年 5 月月活 3.56 亿，排名第一。</p><div>河马剧场约为其五分之一，数据来自第三方。</div>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/empty":
            body, code = b"<html><head><title>t</title></head><body><script>x()</script></body></html>", 200
        elif self.path == "/missing":
            body, code = b"not found", 404
        else:
            body, code = PAGE.encode("utf-8"), 200
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@unittest.skipUnless(shutil.which("curl"), "需要 curl")
class FetchPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)

    def test_text_and_title(self):
        r = self.run_(self.base + "/a")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("TITLE: 红果月活 & 河马", r.stdout)
        self.assertIn("3.56 亿", r.stdout)
        self.assertIn("五分之一", r.stdout)
        self.assertNotIn("不应出现", r.stdout)  # scripts stripped
        self.assertNotIn("首页", r.stdout)  # short navigation lines dropped

    def test_limit(self):
        r = self.run_(self.base + "/a", "10")
        self.assertLessEqual(len(r.stdout.split("TEXT: ", 1)[1].strip()), 10)

    def test_empty_and_http_error(self):
        self.assertEqual(self.run_(self.base + "/empty").returncode, 1)
        self.assertEqual(self.run_(self.base + "/missing").returncode, 1)

    def test_unreachable_and_bad_args(self):
        self.assertEqual(self.run_("http://127.0.0.1:1/x").returncode, 3)
        self.assertEqual(self.run_("ftp://x").returncode, 2)
        self.assertEqual(self.run_().returncode, 2)


if __name__ == "__main__":
    unittest.main()
