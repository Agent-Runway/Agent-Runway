from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))


class AssertionLanguageEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        self.server = importlib.reload(importlib.import_module("server"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def bash_receipt(self, task_id: str):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_verified_slice(self, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Ran pytest and mapped the zero-exit receipt before attempting completion.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_rejects_additional_chinese_hedging_shapes(self) -> None:
        cases = [
            "应该就好了，我先停在这里，但这只是推测不是验证结论。",
            "大概行了，可以先算完成，但这里没有新增可核验结果。",
            "感觉没问题了，所以我准备结束这一轮，但这里没有新的日志证据。",
            "感觉应该没问题了，所以我准备结束这一轮，但这里没有新的日志证据。",
            "估计应该可以了，我不再继续检查，也没有引用新的验证输出。",
            "似乎可以了，当前总结没有绑定新的命令输出。",
            "似乎已经解决了，当前总结没有绑定新的命令输出。",
            "好像好了，我先把这一轮关掉，但没有列出新的核验结果。",
            "按说没问题，可以不用继续验证，但这不是可复现证据。",
            "理论上应该没问题，所以我不再跑检查，也没有新凭证。",
            "不出意外的话应该可以，因此我先停下，没有更多证据。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"cn-hedge-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_completion_gate_rejects_additional_english_hedging_shapes(self) -> None:
        cases = [
            "The result seems correct, so I am treating the task as complete.",
            "The patch appears fixed, so no deeper verification is needed.",
            "The implementation is likely correct based on inspection alone.",
            "The change is most likely fine and can be accepted now.",
            "Maybe done after the edit, so I am closing the task.",
            "Maybe it is done after the edit, so I am closing the task.",
            "Perhaps this is correct after the edit, so I am closing the task.",
            "This might be resolved without running another check.",
            "I feel this is fixed and no more evidence is needed.",
            "I'd say these changes are correct enough to complete.",
            "As far as I can tell the fix is complete.",
            "Presumably the update is good after the local edit.",
            "There is no reason why it should not work now.",
            "I feel like this is resolved, so I am closing the task.",
            "I see no reason why it would fail, so I am accepting it.",
            "There is no reason why it would fail, so I am accepting it.",
            "There is no reason why not to accept the patch now.",
            "No reason why not to accept the patch now.",
            "No reason not to accept the patch now.",
            "There's no reason why not to merge this change now.",
            "I see no reason not to approve this patch now.",
            "I see nothing wrong with accepting this patch now.",
            "There's nothing wrong with shipping this change now.",
            "Nothing wrong with accepting this patch now.",
            "The implementation should be good after the patch.",
            "The implementation should be okay after the patch.",
            "The previous run seemed to work, so I am completing now.",
            "I think these changes are correct and ready.",
        ]
        for index, summary in enumerate(cases):
            task_id = f"en-hedge-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary=summary,
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_turn_end_gate_rejects_archived_20260514_chinese_hedging_gaps(self) -> None:
        cases = [
            "按说应该可以，我先停下但没有新的可复现证据。",
            "按说应该是好了，我先停下但没有新的可复现证据。",
            "不出意外应该可以，所以我准备结束这一轮。",
            "不出意外应该没问题，因此我准备结束这一轮。",
            "应该不会出问题了，可以先算完成。",
            "应该不会出错了，可以先算完成。",
            "应该不会失败了，可以先算完成。",
            "应该不会有问题了，可以先算完成。",
            "应该不用再查了，我准备停在这里。",
            "应该不用继续了，我准备停在这里。",
            "应该不用再改了，我准备停在这里。",
            "应该不用再跑了，我准备停在这里。",
            "看着没问题，我准备结束这一轮。",
            "看着可以了，我准备结束这一轮。",
            "看着好了，我准备结束这一轮。",
            "看着行了，我准备结束这一轮。",
            "我觉得没问题了，所以不再补证据。",
            "我觉得可以了，所以不再补证据。",
            "我觉得好了，所以不再补证据。",
            "我觉得行了，所以不再补证据。",
            "我觉得差不多了，所以不再补证据。",
            "我觉得是这样了，所以不再补证据。",
            "感觉差不多，可以先结束。",
            "好像差不多，可以先结束。",
            "似乎差不多，可以先结束。",
            "理论上应该可以，我先停下。",
            "理论上没问题，我先停下。",
            "没有理由不接受，所以我准备结束这一轮。",
            "没什么理由不通过，可以先算完成。",
            "没有任何理由不合并，所以我准备停下。",
            "看不出有什么问题，所以我准备结束这一轮。",
            "看不出任何问题，可以先算完成。",
            "看不出有问题，可以先算完成。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"cn-archive-hedge-gap-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)
                work_summary = f"{summary} 这里仍然缺少新的验证输出。"

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=work_summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_turn_end_gate_rejects_hedging_with_invisible_characters(self) -> None:
        cases = [
            "The result seems c\u200borrect, so I am treating the task as complete.",
            "The patch should be g\x00ood after the edit, so I am closing the task.",
            "感觉没\u200d问题了，所以我准备结束这一轮，但这里没有新增可核验结果。",
            "应该已\x1f经解决了，我先停在这里，但这里没有新增可核验结果。",
            "应该不\u200d会失败了，可以先算完成，但这里没有新增可核验结果。",
            "应该不\x1f用再查了，我准备停在这里，但这里没有新增可核验结果。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"invisible-hedge-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_turn_end_gate_rejects_hedging_with_invisible_marks(self) -> None:
        cases = [
            "The result seems c\u034forrect, so I am treating the task as complete.",
            "The result seems c\ufe00orrect, so I am treating the task as complete.",
            "The patch should be g\ufe0food after the edit, so I am closing the task.",
        ]
        for index, summary in enumerate(cases):
            task_id = f"invisible-mark-hedge-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_turn_end_gate_rejects_nfkc_compatibility_assertion_bypass(self) -> None:
        cases = [
            "ｓｈｏｕｌｄ　ｗｏｒｋ, so I am stopping without more evidence.",
            "𝐈 𝐛𝐞𝐥𝐢𝐞𝐯𝐞 𝐭𝐡𝐢𝐬 𝐢𝐬 𝐟𝐢𝐱𝐞𝐝, so I am stopping.",
            "𝐢𝐭 𝐰𝐨𝐫𝐤𝐬, so I am stopping.",
        ]
        for index, summary in enumerate(cases):
            task_id = f"nfkc-hedge-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_turn_end_gate_rejects_multilingual_assertion_language(self) -> None:
        cases = [
            "Debería funcionar, así que voy a detenerme.",
            "Parece correcto, así que voy a cerrar la tarea.",
            "Devrait marcher, donc je m'arrête.",
            "Semble correct, donc je termine.",
            "Sollte funktionieren, deshalb höre ich auf.",
            "Scheint korrekt, deshalb schließe ich die Aufgabe.",
            "Deveria funcionar, então vou parar.",
            "Parece correto, então vou encerrar.",
            "動くはずなので、ここで止めます。追加の検証証跡はありません。",
            "たぶん大丈夫なので、完了にします。追加の検証証跡はありません。",
            "작동할 거예요, 그래서 멈추겠습니다.",
            "괜찮을 것 같아요, 그래서 완료하겠습니다.",
        ]
        for index, summary in enumerate(cases):
            task_id = f"i18n-assertion-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_turn_end_gate_allows_common_english_user_quote_markers(self) -> None:
        cases = [
            'The user told me "should pass now"; I reran pytest and mapped the zero-exit receipt instead of trusting the quote.',
            "The user told me 'should pass now'; I reran pytest and mapped the zero-exit receipt instead of trusting the quote.",
            'The user mentioned "should pass now"; I reran pytest and mapped the zero-exit receipt instead of trusting the quote.',
            'The user stated "should pass now"; I reran pytest and mapped the zero-exit receipt instead of trusting the quote.',
            'The user claimed "should pass now"; I reran pytest and mapped the zero-exit receipt instead of trusting the quote.',
            'Per the user, "should pass now" was the prior claim; I reran pytest and mapped the zero-exit receipt.',
        ]
        for index, summary in enumerate(cases):
            task_id = f"en-quote-marker-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                approved = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("APPROVED", approved)

    def test_turn_end_gate_rejects_english_quote_marker_when_trailing_assertion_is_adopted(
        self,
    ) -> None:
        cases = [
            'The user told me "should pass now". It should pass now, so I am stopping.',
            'The user stated "looks correct". It looks correct, so I am stopping.',
            'Per the user, "probably fixed" was the claim. It is probably fixed, so I am stopping.',
        ]
        for index, summary in enumerate(cases):
            task_id = f"en-quote-trailing-assertion-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_completion_gate_allows_common_chinese_user_quote_markers(self) -> None:
        cases = [
            "用户说“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "日志写“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "日志显示“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "报告称“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "报告写明“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "用户提到“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "用户反馈“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "用户告诉我“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "对方说“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "原文是“应该可以了”，我重新执行测试并映射新的零退出凭证。",
            "描述中说“应该可以了”，我重新执行测试并映射新的零退出凭证。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"cn-quote-marker-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary=summary,
                )

                self.assertIn("APPROVED", approved)

    def test_completion_gate_allows_quote_markers_across_supported_languages(self) -> None:
        cases = [
            'The user said "should pass now"; I reran pytest and mapped a fresh receipt.',
            '用户说“应该可以了”，我重新执行测试并映射新的零退出凭证。',
            'El usuario dijo "debería funcionar"; volví a ejecutar pytest y mapeé un recibo nuevo.',
            "L'utilisateur a dit \"devrait marcher\"; j'ai relancé pytest et mappé un nouveau reçu.",
            'Der Nutzer sagte "sollte funktionieren"; ich habe pytest erneut ausgeführt und einen frischen Beleg zugeordnet.',
            'O usuário disse "deveria funcionar"; eu executei pytest novamente e associei um recibo novo.',
            'ユーザーは言った「動くはず」; pytest を再実行して新しい証跡を対応付けた。',
            "사용자가 말했다 \"작동할 거예요\"; pytest를 다시 실행하고 새 증적을 연결했다.",
        ]
        for index, summary in enumerate(cases):
            task_id = f"i18n-quote-marker-completion-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary=summary,
                )

                self.assertIn("APPROVED", approved)

    def test_turn_end_gate_allows_chinese_quote_markers_with_fresh_evidence(self) -> None:
        cases = [
            "用户说“应该可以了”，我重新执行 pytest 并映射新的零退出凭证。",
            "日志写“应该可以了”，我重新执行 pytest 并映射新的零退出凭证。",
            "日志记录“应该可以了”，我重新执行 pytest 并映射新的零退出凭证。",
            "报告称“应该可以了”，我重新执行 pytest 并映射新的零退出凭证。",
            "报告指出“应该可以了”，我重新执行 pytest 并映射新的零退出凭证。",
            "报告称'probably fixed'，我重新执行 pytest 并映射新的零退出凭证。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"cn-quote-marker-turn-end-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                approved = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("APPROVED", approved)

    def test_turn_end_gate_rejects_chinese_quote_marker_with_trailing_assertion(
        self,
    ) -> None:
        cases = [
            "用户说“应该可以了”。应该可以了，所以我准备停下。",
            "日志写“应该可以了”。看起来对了，所以我准备停下。",
            "报告称“应该可以了”。我觉得没问题了，所以我准备停下。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"cn-quote-trailing-assertion-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_turn_end_gate_rejects_quote_markers_with_trailing_assertion_across_supported_languages(
        self,
    ) -> None:
        cases = [
            'The user said "should pass now". It should pass now, so I will stop.',
            '用户说“应该可以了”。应该可以了，所以我准备停下。',
            'El usuario dijo "should pass now". It should pass now, so I will stop.',
            "L'utilisateur a dit \"should pass now\". It should pass now, so I will stop.",
            'Der Nutzer sagte "should pass now". It should pass now, so I will stop.',
            'O usuário disse "should pass now". It should pass now, so I will stop.',
            'ユーザーは言った「should pass now」。It should pass now, so I will stop.',
            "사용자가 말했다 \"should pass now\". It should pass now, so I will stop.",
        ]
        for index, summary in enumerate(cases):
            task_id = f"i18n-quote-marker-turn-end-negative-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_completion_gate_rejects_chinese_quote_marker_with_trailing_assertion(
        self,
    ) -> None:
        cases = [
            "用户说“应该可以了”。应该可以了，所以我把任务标为完成。",
            "日志显示“应该可以了”。看起来对了，所以我把任务标为完成。",
            "报告写明“应该可以了”。我觉得没问题了，所以我把任务标为完成。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"cn-completion-quote-trailing-assertion-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary=summary,
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_completion_gate_allows_benign_terms_near_new_english_patterns(self) -> None:
        cases = [
            "The test plan includes likely failure modes and records the exact commands that were executed.",
            "The notes compare maybe-related upstream issues without using them as completion evidence.",
            "The report explains why a user might be confused and maps the criterion to a real receipt.",
            "The audit lists no reason why not as a quoted user phrase without adopting it as our conclusion.",
            "The notes ask whether there is no reason why a previous run would fail, then require a receipt.",
            "The audit lists nothing wrong with accepting as a quoted phrase, then maps the criterion to a real receipt.",
            "The report records no reason not to accept as source text without adopting it as completion evidence.",
            "I feel like the report documents the executed commands rather than claiming completion.",
        ]
        for index, summary in enumerate(cases):
            task_id = f"en-benign-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary=summary,
                )

                self.assertIn("APPROVED", approved)

    def test_turn_end_gate_allows_benign_terms_near_new_chinese_patterns(self) -> None:
        cases = [
            "已记录用户感觉与估计类措辞，并把这些原文当作待验证输入而不是完成依据。",
            "已对理论上和按说这类表达做分类，实际结论仍绑定到新的命令输出。",
            "已检查不出意外的话这句原文的上下文，当前停止原因来自已执行测试。",
            "已记录感觉差不多这句原文，并要求后续结论继续绑定真实凭证。",
            "已记录看不出有什么问题这句原文，并要求后续结论继续绑定真实凭证。",
            "已检查看不出有什么问题这个表达，当前停止原因来自已执行测试。",
            "已记录没有理由不接受这种表达，并把它当作待验证输入而不是完成依据。",
        ]
        for index, summary in enumerate(cases):
            task_id = f"cn-benign-edge-{index}"
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["tests pass"])
                receipt = self.bash_receipt(task_id)

                approved = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )

                self.assertIn("APPROVED", approved)


if __name__ == "__main__":
    unittest.main()
