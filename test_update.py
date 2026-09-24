#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Unit tests for update.py: tag selection and Alpine candidate filtering."""
import io
import json
import unittest
import urllib.error
from datetime import date
from unittest import mock

import update


def _ls_remote(*lines):
    m = mock.Mock()
    m.stdout = "".join(f"{sha}\t{ref}\n" for sha, ref in lines)
    return m


class NewestTagTests(unittest.TestCase):
    def test_peeled_annotated_tag_wins(self):
        out = _ls_remote(
            ("aaa111", "refs/tags/v3.1.0"),
            ("bbb222", "refs/tags/v3.1.0^{}"),
            ("ccc333", "refs/tags/v3.1.1"),
        )
        with mock.patch.object(update.subprocess, "run", return_value=out):
            self.assertEqual(update.newest_tag("amneziawg-go", "v3.0.0"), ("v3.1.1", "ccc333"))

    def test_same_major_only_and_newest_patch(self):
        out = _ls_remote(
            ("aaa", "refs/tags/v2.9.9"),
            ("bbb", "refs/tags/v3.0.1"),
            ("ccc", "refs/tags/v3.1.0"),
            ("ddd", "refs/tags/v3.0.10"),
            ("eee", "refs/tags/v4.0.0"),
        )
        with mock.patch.object(update.subprocess, "run", return_value=out):
            tag, sha = update.newest_tag("amneziawg-go", "v3.0.0")
        self.assertEqual((tag, sha), ("v3.1.0", "ccc"))

    def test_numeric_not_lexicographic(self):
        out = _ls_remote(
            ("aaa", "refs/tags/v3.1.9"),
            ("bbb", "refs/tags/v3.1.10"),
        )
        with mock.patch.object(update.subprocess, "run", return_value=out):
            self.assertEqual(update.newest_tag("amneziawg-tools", "v3.1.0")[0], "v3.1.10")

    def test_no_candidate_exits(self):
        out = _ls_remote(("aaa", "refs/tags/v9.0.0"))
        with mock.patch.object(update.subprocess, "run", return_value=out):
            with self.assertRaises(SystemExit):
                update.newest_tag("amneziawg-go", "v3.0.0")

    def test_dash_suffix_tag(self):
        out = _ls_remote(
            ("aaa", "refs/tags/v3.1.20260828-1"),
            ("bbb", "refs/tags/v3.1.20260828"),
        )
        with mock.patch.object(update.subprocess, "run", return_value=out):
            self.assertEqual(update.newest_tag("amneziawg-go", "v3.1.1")[0], "v3.1.20260828-1")


class AlpineCandidatesTests(unittest.TestCase):
    def _feed(self, branches):
        payload = json.dumps({"release_branches": branches})
        fake_date = mock.Mock(wraps=date)
        fake_date.today.return_value = date(2026, 9, 24)
        with mock.patch.object(update, "get", return_value=payload), \
             mock.patch.object(update, "date", fake_date):
            return update.alpine_candidates()

    def test_filters_branches_newest_first(self):
        got = self._feed([
            {"rel_branch": "v3.20", "branch_date": "2024-05-01", "eol_date": "2026-04-01"},
            {"rel_branch": "v3.22", "branch_date": "2024-11-01", "eol_date": "2026-11-01"},
            {"rel_branch": "v3.23", "branch_date": "2025-05-01", "eol_date": "2027-05-01"},
            {"rel_branch": "v3.24", "branch_date": "2025-11-01", "eol_date": "2027-11-01"},
            {"rel_branch": "main", "branch_date": "2020-01-01", "eol_date": "2099-01-01"},
            {"rel_branch": "v3.21.0", "branch_date": "2025-01-01", "eol_date": "2027-01-01"},
        ])
        # 3.20 EOL before the mocked today (2026-09-24); non vX.Y and patch branches dropped; newest first.
        self.assertEqual(got, ["3.24", "3.23", "3.22"])

    def test_missing_eol_date_is_not_supported(self):
        got = self._feed([{"rel_branch": "v3.24", "branch_date": "2025-11-01"}])
        self.assertEqual(got, [])

    def test_missing_branch_date_is_excluded(self):
        # The "9" sentinel fails `<= today` lexicographically, so a release without branch_date is dropped.
        got = self._feed([
            {"rel_branch": "v3.24", "eol_date": "2027-11-01"},
            {"rel_branch": "v3.23", "branch_date": "2025-05-01", "eol_date": "2027-05-01"},
        ])
        self.assertEqual(got, ["3.23"])


class RetryTests(unittest.TestCase):
    def test_retries_transient_http_then_succeeds(self):
        calls = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise urllib.error.HTTPError(req.full_url, 503, "busy", None, io.BytesIO(b""))
            m = mock.Mock()
            m.read.return_value = b"ok"
            m.__enter__ = lambda s: s
            m.__exit__ = lambda *a: False
            return m

        with mock.patch.object(update.urllib.request, "urlopen", side_effect=fake_urlopen), \
             mock.patch.object(update.time, "sleep"):
            self.assertEqual(update.get("https://example.com"), "ok")
        self.assertEqual(len(calls), 3)

    def test_404_is_not_retried(self):
        calls = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 404, "nf", None, io.BytesIO(b""))

        with mock.patch.object(update.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(urllib.error.HTTPError):
                update.get("https://example.com/missing")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
