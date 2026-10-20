import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

class TestLeadDesk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        os.environ["LEADDESK_DATA_DIR"]=cls.temp.name
        import server
        cls.s=server
        cls.s.initialize()
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        with self.s.db() as db:
            db.execute("DELETE FROM leads")
            db.execute("UPDATE kv SET value='0' WHERE name='enabled'")
            db.commit()

    def lead(self):
        return {
            "username":"@candidate_writer",
            "project":"Telegram bot",
            "service":"development",
            "message":"hello, I saw your public job listing and can build this Telegram bot.",
            "source_url":"https://t.me/public_jobs/1337",
            "posted_on":date.today().isoformat()
        }

    def test_source_must_be_public_post_not_profile(self):
        a=self.lead()
        self.assertIsNone(self.s.valid(a))
        a["source_url"]="https://t.me/random_username"
        self.assertIsNotNone(self.s.valid(a))
        a["source_url"]="javascript:alert(1)"
        self.assertIsNotNone(self.s.valid(a))
        a["source_url"]="https://t.me/public_jobs/1337"
        a["posted_on"]=(date.today()-timedelta(days=60)).isoformat()
        self.assertIsNotNone(self.s.valid(a))

    def test_import_does_not_approve_or_run(self):
        self.s.add_rows([self.lead(),self.lead()])
        with self.s.db() as c:
            rows=c.execute("SELECT * FROM leads").fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["status"],"review")
        self.assertFalse(self.s.enabled())
        self.assertEqual(self.s.counts()[:2],(0,0))

    def test_no_credentials_means_no_delivery(self):
        with patch.dict(os.environ,{"TG_API_ID":"","TG_API_HASH":"","TG_STRING_SESSION":""}):
            self.assertFalse(self.s.configured())

    def test_admin_requires_secret_and_origin(self):
        from aiohttp import web
        class Req:
            path="/";method="GET";headers={};host="app.example.com"
        with patch.dict(os.environ,{"ADMIN_PASSWORD":""}):
            with self.assertRaises(web.HTTPServiceUnavailable):self.s.authorize(Req())
        with patch.dict(os.environ,{"ADMIN_PASSWORD":"longunique_admin_password"}):
            with self.assertRaises(web.HTTPUnauthorized):self.s.authorize(Req())
            from aiohttp import BasicAuth
            Req.headers={"Authorization":BasicAuth("admin","longunique_admin_password").encode()}
            self.assertTrue(self.s.authorize(Req()))
            Req.method="POST"
            with self.assertRaises(web.HTTPForbidden):self.s.authorize(Req())
            Req.headers["Origin"]="https://app.example.com"
            self.assertTrue(self.s.authorize(Req()))

if __name__=="__main__":unittest.main()
