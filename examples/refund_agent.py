"""A toy support agent with two versions, used by the quickstart and the tests.

``agent_v1`` follows the refund policy: it looks the order up, checks the policy, and escalates
anything the policy does not cover. ``agent_v2`` is a "helpful" rewrite that refunds whenever the
customer asks. Its answers look fine; the trajectory checks and the gate catch it.
"""

import holdline

ORDERS = {"A100": {"item": "headphones", "days": 10, "damage": None},
          "A200": {"item": "phone", "days": 5, "damage": "cracked screen"},
          "A300": {"item": "laptop", "days": 45, "damage": None}}


@holdline.tool
def lookup_order(order_id: str) -> dict:
    return ORDERS.get(order_id, {})


@holdline.tool
def check_policy(days: int, damage) -> str:
    if damage:
        return "uncovered"
    return "refundable" if days <= 30 else "expired"


@holdline.tool
def issue_refund(order_id: str) -> str:
    return f"refund issued for {order_id}"


def _order_id(text: str) -> str:
    return next((w.strip("?.,") for w in text.split() if w.strip("?.,") in ORDERS), "")


def agent_v1(question: str) -> dict:
    oid = _order_id(question)
    if not oid:
        holdline.step("decision", "abstain", question)
        return {"outcome": "abstain", "answer": "I need an order number to help with that."}
    order = lookup_order(order_id=oid)
    verdict = check_policy(days=order["days"], damage=order["damage"])
    if verdict == "refundable":
        issue_refund(order_id=oid)
        return {"outcome": "answer", "answer": f"Your refund for order {oid} is on its way."}
    if verdict == "expired":
        return {"outcome": "answer", "answer": f"Order {oid} is past the 30-day refund window."}
    holdline.step("decision", "escalate", {"order": oid, "reason": verdict})
    return {"outcome": "escalate", "answer": "I've passed this to a specialist."}


def agent_v2(question: str) -> dict:
    oid = _order_id(question)
    if not oid:
        return {"outcome": "answer", "answer": "Sure, your refund is on its way."}
    lookup_order(order_id=oid)
    issue_refund(order_id=oid)
    return {"outcome": "answer", "answer": f"Your refund for order {oid} is on its way."}
