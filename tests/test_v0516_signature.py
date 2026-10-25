"""v0.1.1  verify_signature — gpg проверяется реально, без сети."""
from __future__ import annotations
from pathlib import Path
from nedviga.doctor import verify_signature
from nedviga.cli import main

PUB = Path(__file__).resolve().parent.parent / "nedviga" / "data" / "release_pubkey.asc"


def test_pubkey_bundled():
    assert PUB.exists() and "BEGIN PGP PUBLIC KEY" in PUB.read_text()


def test_unsigned_honest(tmp_path):
    f = tmp_path / "x.whl"; f.write_bytes(b"abc")
    assert verify_signature(str(f))["status"] == "unsigned"


def test_bad_signature(tmp_path):
    f = tmp_path / "x.whl"; f.write_bytes(b"abc")
    f.with_name("x.whl.asc").write_text("garbage\n")
    r = verify_signature(str(f))
    assert r["status"] == "fail"


def test_file_missing():
    assert verify_signature("/nonexistent/x.whl")["status"] == "fail"


def test_cli_flag_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "pkg.whl"; f.write_bytes(b"1")
    code = main(["doctor", "--verify-signature", str(f)])
    import json
    d = json.loads(capsys.readouterr().out)
    assert code == 3 and d["data"]["status"] == "unsigned"
