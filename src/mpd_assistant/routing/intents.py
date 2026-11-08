from enum import Enum


class Mode(str, Enum):
    TEMPLATED = "templated"
    GENERATED = "generated"
    REASONED = "reasoned"
    ESCALATE = "escalate"


class Agent(str, Enum):
    CONCIERGE = "concierge"
    LEAD_CONVERSION = "lead_conversion"
    SOLUTION_ARCHITECT = "solution_architect"
    QUOTE = "quote"
    COMMS_SCHEDULING = "comms_scheduling"
    ESCALATION = "escalation"
    PAYMENT = "payment"  # deterministic code node, not an LLM agent


class Intent(str, Enum):
    GREETING = "greeting"
    SMALL_TALK = "small_talk"
    FAQ = "faq"
    KNOWLEDGE_QUESTION = "knowledge_question"
    PROJECT_INQUIRY = "project_inquiry"
    SCOPE_REQUEST = "scope_request"
    QUOTE_REQUEST = "quote_request"
    BOOK_MEETING = "book_meeting"
    EMAIL_REQUEST = "email_request"
    PAYMENT_REQUEST = "payment_request"
    HUMAN_REQUEST = "human_request"
    COMPLAINT = "complaint"
    UNKNOWN = "unknown"


# Gated intents need a verified identity (policy D14, option B). Others work for anonymous visitors.
GATED_INTENTS = frozenset(
    {Intent.PROJECT_INQUIRY, Intent.SCOPE_REQUEST, Intent.QUOTE_REQUEST, Intent.BOOK_MEETING, Intent.EMAIL_REQUEST, Intent.PAYMENT_REQUEST}
)

INTENT_AGENT = {
    Intent.GREETING: Agent.CONCIERGE,
    Intent.SMALL_TALK: Agent.CONCIERGE,
    Intent.FAQ: Agent.CONCIERGE,
    Intent.KNOWLEDGE_QUESTION: Agent.CONCIERGE,
    Intent.PROJECT_INQUIRY: Agent.LEAD_CONVERSION,
    Intent.SCOPE_REQUEST: Agent.SOLUTION_ARCHITECT,
    Intent.QUOTE_REQUEST: Agent.QUOTE,
    Intent.BOOK_MEETING: Agent.COMMS_SCHEDULING,
    Intent.EMAIL_REQUEST: Agent.COMMS_SCHEDULING,
    Intent.PAYMENT_REQUEST: Agent.PAYMENT,
    Intent.HUMAN_REQUEST: Agent.ESCALATION,
    Intent.COMPLAINT: Agent.ESCALATION,
    Intent.UNKNOWN: Agent.CONCIERGE,
}

INTENT_DEFAULT_MODE = {
    Intent.GREETING: Mode.TEMPLATED,
    Intent.SMALL_TALK: Mode.GENERATED,
    Intent.FAQ: Mode.TEMPLATED,
    Intent.KNOWLEDGE_QUESTION: Mode.GENERATED,
    Intent.PROJECT_INQUIRY: Mode.GENERATED,
    Intent.SCOPE_REQUEST: Mode.REASONED,
    Intent.QUOTE_REQUEST: Mode.REASONED,
    Intent.BOOK_MEETING: Mode.REASONED,
    Intent.EMAIL_REQUEST: Mode.REASONED,
    Intent.PAYMENT_REQUEST: Mode.TEMPLATED,  # no model call: payment is code
    Intent.HUMAN_REQUEST: Mode.ESCALATE,
    Intent.COMPLAINT: Mode.ESCALATE,
    Intent.UNKNOWN: Mode.GENERATED,
}
