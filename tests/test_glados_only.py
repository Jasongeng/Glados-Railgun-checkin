"""Offline regression tests using synthetic cookies and mocked HTTP/push calls."""

import json
import os
import unittest
from unittest.mock import patch

import requests

import checkin


class GladosOnlyTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"GLADOS_COOKIES": "synthetic-cookie"}, clear=True).start()
        patch.object(checkin, "logger").start()
        self.push = patch.object(checkin, "PushDeer").start()
        self.checkin_code = 0
        self.http = patch.object(
            requests.sessions.Session, "request", side_effect=self.fake_request
        ).start()

    def fake_request(self, method, url, **kwargs):
        self.assertTrue(url.startswith("https://glados.cloud/api/user/"), url)
        endpoint = url.rsplit("/", 1)[-1]
        payloads = {
            "status": {"code": 0, "data": {"leftDays": "42.5"}},
            "checkin": {"code": self.checkin_code, "points": 10, "message": "synthetic result"},
            "points": {"code": 0, "points": 600},
            "exchange": {"code": 0, "message": "synthetic exchange"},
        }
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payloads[endpoint]).encode()
        return response

    def run_checker(self):
        checker = checkin.Checker(checkin.Config())
        checker.checkin_all()
        return checker

    def test_only_glados_is_configured(self):
        self.assertEqual(checkin.Config().DOMAINS, ["glados.cloud"])

    def test_single_cookie_uses_glados_for_all_requests(self):
        checker = self.run_checker()
        self.assertEqual(len(checker.results), 1)
        self.assertEqual(checker.results[0].domain, "glados.cloud")
        self.assertEqual(checker.results[0].days, "42 天")
        self.assertEqual(checker.results[0].points_total, "600 积分")
        self.assertEqual(checker.results[0].exchange, "兑换成功: plan500")
        calls = self.http.call_args_list
        self.assertEqual(
            [(call.args[0], call.args[1]) for call in calls],
            [(method, "https://glados.cloud/api/user/" + endpoint) for method, endpoint in [
                ("GET", "status"), ("POST", "checkin"),
                ("GET", "points"), ("POST", "exchange"),
            ]],
        )
        for call in calls:
            self.assertEqual(call.kwargs["headers"]["cookie"], "synthetic-cookie")
            self.assertEqual(call.kwargs["headers"]["origin"], "https://glados.cloud")
        self.assertEqual(calls[1].kwargs["data"], {"token": "glados.cloud"})
        self.assertEqual(checker.format_results()[0], "GLaDOS 签到, 成功1, 失败0, 重复0")

    def test_multiple_cookies_each_run_once(self):
        os.environ["GLADOS_COOKIES"] = " cookie-one & & cookie-two "
        checker = self.run_checker()
        self.assertEqual([result.cookie_index for result in checker.results], [1, 2])
        self.assertEqual(self.http.call_count, 8)
        cookies = [call.kwargs["headers"]["cookie"] for call in self.http.call_args_list]
        self.assertEqual(cookies, ["cookie-one"] * 4 + ["cookie-two"] * 4)
        self.assertEqual(checker.format_results()[0], "GLaDOS 签到, 成功2, 失败0, 重复0")

    def test_repeat_checkin_is_preserved(self):
        self.checkin_code = 1
        checker = self.run_checker()
        self.assertEqual(checker.format_results()[0], "GLaDOS 签到, 成功0, 失败0, 重复1")
        self.assertEqual(self.http.call_count, 4)

    def test_failed_checkin_is_preserved(self):
        self.checkin_code = -2
        checker = self.run_checker()
        self.assertEqual(checker.format_results()[0], "GLaDOS 签到, 成功0, 失败1, 重复0")
        self.assertEqual(self.http.call_count, 4)

    def test_custom_exchange_plan_and_verbose_are_preserved(self):
        os.environ.update(GLADOS_EXCHANGE_PLAN="plan200", GLADOS_VERBOSE="true")
        checker = self.run_checker()
        self.assertTrue(checker.config.verbose)
        self.assertEqual(self.http.call_args_list[-1].kwargs["data"], {"planType": "plan200"})

    def test_main_sends_glados_only_summary(self):
        os.environ["PUSHDEER_SENDKEY"] = "synthetic-push-key"
        checkin.main()
        self.assertEqual(self.http.call_count, 4)
        self.push.assert_called_once_with(pushkey="synthetic-push-key")
        send = self.push.return_value.send_text
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "GLaDOS 签到, 成功1, 失败0, 重复0")

    def test_missing_cookies_and_push_key_do_not_send_requests(self):
        os.environ.clear()
        checkin.main()
        self.http.assert_not_called()
        self.push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
