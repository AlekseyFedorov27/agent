from .triage import triage
from .ask_user import ask_user
from .research import research
from .plan import plan, replan
from .budget_check import budget_check


NODES =  {
    "triage": triage,
    "ask_user": ask_user,
    "research": research,
    "plan": plan,
    "replan": replan,
    "budget_check": budget_check,
}