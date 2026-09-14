"""Every `_request` call must be protected, including the ones that never raise.

`_ensure_session` blocked every write on the reference MC7010 on 2026-09-14 and
contained no `raise` statement. It raised *through* `_request`, one call away,
so the AST sweep for `raise` sites that built the 2026-09-12 guard audit could
not see it. The audit rated the mechanism it belongs to tier 3 on that basis.

So the sweep here does not look for `raise`. It enumerates every `_request`
call in the component and asserts each one is covered by one of the four
protections that actually exist:

  * `classify=False` — the response is not scored for session state at all
  * `authenticated=False` — no session is claimed, so none can be judged lost
  * `_retry=False` **and** inside a `try` — a failure is handled by the caller
  * inside a `try` — the caller decides what a failure means

A call that is none of these can turn a healthy router into a refused command
without any `raise` appearing in the function that did it.

Only **reads** are swept. A write's own `POST` is the operation, and a failed
write is a failed write — it is supposed to reach its caller. The fault class
here is the opposite one: a read taken to *inform* a write, which then fails
it.

`_batch_get` is separate: it guards its own chunks with `_is_classifiable`
before a verdict can be reached, which is why the poll path is not listed here.
"""

import ast
import pathlib

API = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "zte_router_5g"
    / "api.py"
)

# Calls that are deliberately unprotected, each with the reason it is safe.
# A new entry here is a decision, not a formality: it says a failure of this
# request should stop whatever asked for it.
ALLOWED_UNPROTECTED = {
    # The poll path. A failed poll is a failed poll — the coordinator holds
    # last-known values and the health sensor reports the degradation.
    "_batch_get",
    "get_all_data",
    "get_extended_data",
    # Establishing a session. If this cannot run, nothing downstream can.
    "login",
    "_attempt_login",
    "get_ld",
    "try_set_protocol",
}


def _enclosing_function(tree: ast.Module) -> dict[int, str]:
    """Map every line number to the function that contains it."""
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner.setdefault(line, node.name)
    return owner


def _lines_inside_try(tree: ast.Module) -> set[int]:
    """Every line sitting inside a `try` body."""
    covered: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in node.body:
                for line in range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1):
                    covered.add(line)
    return covered


def _keyword(call: ast.Call, name: str) -> bool:
    """Whether `name=False` is passed explicitly."""
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            return kw.value.value is False
    return False


def test_every_request_call_is_protected() -> None:
    """No `_request` call may fail an operation it was only advising on."""
    tree = ast.parse(API.read_text(encoding="utf-8"))
    owner = _enclosing_function(tree)
    in_try = _lines_inside_try(tree)

    unprotected: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "_request"):
            continue
        method = node.args[0] if node.args else None
        if not (isinstance(method, ast.Constant) and method.value == "GET"):
            # A write's own request. Its failure is the operation's failure and
            # belongs to the caller.
            continue
        where = owner.get(node.lineno, "<module>")
        if where in ALLOWED_UNPROTECTED:
            continue
        if _keyword(node, "classify") or _keyword(node, "authenticated"):
            continue
        if node.lineno in in_try:
            continue
        unprotected.append(f"{where} (api.py:{node.lineno})")

    assert not unprotected, (
        "these `_request` calls can fail their caller with no `raise` in sight: "
        + ", ".join(sorted(unprotected))
    )


def test_the_session_check_does_not_manufacture_its_own_classifiability() -> None:
    """`_ensure_session` must not append a key to satisfy the guard it defeats.

    `_is_classifiable` asks whether a verdict *could* mean anything, and
    answers yes whenever an unauthenticated key is present. The pre-write check
    used to append one deliberately, satisfying the guard by construction while
    defeating its intent — the request was classifiable, and the verdict it
    produced was wrong.

    The check now reads the firmware's own session flag with `classify=False`,
    so no verdict is manufactured at all.
    """
    tree = ast.parse(API.read_text(encoding="utf-8"))
    checks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_ensure_session"
    ]
    assert len(checks) == 1, "_ensure_session not found, or defined more than once"

    manufactured = [
        call
        for call in ast.walk(checks[0])
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_session_check_request"
    ]
    assert not manufactured, (
        "the pre-write check builds its own classifiable request again"
    )
