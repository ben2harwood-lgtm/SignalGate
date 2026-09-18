"""Source-level invariants for the MQL5 safety boundary.

MetaEditor is not available on GitHub's Linux runner, so these tests guard
critical source properties in addition to the manual/Windows compile gate.
"""
from pathlib import Path

EA = (Path(__file__).parents[2] / "mt5_ea" / "SignalGateEA.mq5").read_text()


def test_rollback_is_scoped_to_command_id():
    assert "void CloseAllChildren(const string symbol, const string command_id)" in EA
    assert "CloseAllChildren(symbol, command_id);" in EA
    rollback = EA.split("void CloseAllChildren(", 1)[1].split("//+------------------------------------------------------------------+", 1)[0]
    assert "POSITION_COMMENT" in rollback
    assert "command_id" in rollback


def test_hosted_license_is_sent_in_header_not_pending_url():
    assert "X-SG-License-Key: " in EA
    poll = EA.split("string PollPendingCommand()", 1)[1].split("}", 1)[0]
    assert "license_key=" not in poll.lower()
